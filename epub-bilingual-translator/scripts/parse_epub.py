#!/usr/bin/env python3
"""
EPUB Parser — Extracts structured content from an EPUB file.
Outputs a JSON manifest with chapters, paragraphs, and metadata.
"""

import zipfile
import sys
import os
import json
import re
from html.parser import HTMLParser
from xml.etree import ElementTree as ET

# EPUB XHTML namespace
NS = {
    'xhtml': 'http://www.w3.org/1999/xhtml',
    'epub': 'http://www.idpf.org/2007/ops',
    'opf': 'http://www.idpf.org/2007/opf',
    'dc': 'http://purl.org/dc/elements/1.1/',
}


class XHTMLParagraphExtractor(HTMLParser):
    """Extract text paragraphs from XHTML content, preserving structure."""

    BLOCK_TAGS = {'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'blockquote', 'td', 'th', 'dd', 'dt'}
    SKIP_TAGS = {'script', 'style', 'head'}

    def __init__(self):
        super().__init__()
        self.paragraphs = []
        self.current_text = []
        self.current_tag_stack = []
        self.in_block = False
        self.current_block_tag = None
        self.current_attrs = {}

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        self.current_tag_stack.append(tag)

        if tag in self.SKIP_TAGS:
            return

        if tag in self.BLOCK_TAGS:
            # Flush any inline text accumulated before this block
            if self.current_text:
                text = ''.join(self.current_text).strip()
                if text:
                    self.paragraphs.append({
                        'tag': 'inline',
                        'text': text,
                        'attrs': {},
                    })
                self.current_text = []

            self.in_block = True
            self.current_block_tag = tag
            self.current_attrs = dict(attrs)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self.current_tag_stack and self.current_tag_stack[-1] == tag:
            self.current_tag_stack.pop()

        if tag in self.BLOCK_TAGS and self.in_block:
            text = ''.join(self.current_text).strip()
            if text:
                self.paragraphs.append({
                    'tag': self.current_block_tag,
                    'text': text,
                    'attrs': self.current_attrs,
                })
            self.current_text = []
            self.in_block = False
            self.current_block_tag = None
            self.current_attrs = {}

    def handle_data(self, data):
        if self.current_tag_stack:
            for t in self.current_tag_stack:
                if t in self.SKIP_TAGS:
                    return
        self.current_text.append(data)

    def flush(self):
        if self.current_text:
            text = ''.join(self.current_text).strip()
            if text:
                self.paragraphs.append({
                    'tag': self.current_block_tag or 'inline',
                    'text': text,
                    'attrs': self.current_attrs,
                })
            self.current_text = []


def parse_xhtml(content_bytes):
    """Parse XHTML content and extract paragraphs."""
    try:
        text = content_bytes.decode('utf-8')
    except UnicodeDecodeError:
        text = content_bytes.decode('utf-8', errors='replace')

    extractor = XHTMLParagraphExtractor()
    try:
        extractor.feed(text)
    except Exception:
        # Fallback: strip tags and split by double newlines
        clean = re.sub(r'<[^>]+>', '\n', text)
        lines = [l.strip() for l in clean.split('\n') if l.strip()]
        return [{'tag': 'p', 'text': l, 'attrs': {}} for l in lines]

    extractor.flush()
    return extractor.paragraphs


def extract_opf_path(epub):
    """Find the OPF file path from META-INF/container.xml."""
    try:
        container_xml = epub.read('META-INF/container.xml')
        tree = ET.fromstring(container_xml)
        for rootfile in tree.iter():
            if rootfile.tag.endswith('rootfile'):
                return rootfile.get('full-path')
    except Exception:
        pass

    # Fallback: look for .opf files
    for name in epub.namelist():
        if name.endswith('.opf'):
            return name
    return None


def parse_opf(epub, opf_path):
    """Parse the OPF file to extract metadata and spine order."""
    opf_content = epub.read(opf_path)
    tree = ET.fromstring(opf_content)

    # Extract metadata
    metadata = {}
    for elem in tree.iter():
        tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
        if tag == 'title':
            metadata['title'] = elem.text or ''
        elif tag == 'creator':
            metadata['creator'] = elem.text or ''
        elif tag == 'language':
            metadata['language'] = elem.text or ''
        elif tag == 'identifier':
            metadata['identifier'] = elem.text or ''
        elif tag == 'publisher':
            metadata['publisher'] = elem.text or ''

    # Extract manifest (id -> href mapping)
    manifest = {}
    opf_dir = os.path.dirname(opf_path)
    for elem in tree.iter():
        tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
        if tag == 'item':
            item_id = elem.get('id')
            href = elem.get('href')
            media_type = elem.get('media-type', '')
            properties = elem.get('properties', '')
            if href and 'xhtml' in media_type or media_type == 'application/xhtml+xml':
                # Resolve relative path
                if opf_dir:
                    href = os.path.join(opf_dir, href)
                manifest[item_id] = {
                    'href': href,
                    'media_type': media_type,
                    'properties': properties,
                }

    # Extract spine order
    spine = []
    for elem in tree.iter():
        tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
        if tag == 'itemref':
            idref = elem.get('idref')
            if idref and idref in manifest:
                spine.append(idref)

    # Cover image
    cover_id = None
    for elem in tree.iter():
        tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
        if tag == 'meta' and elem.get('name') == 'cover':
            cover_id = elem.get('content')
    # Also check <meta property="cover">
    if not cover_id:
        for elem in tree.iter():
            tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if tag == 'meta' and elem.get('property') == 'cover-image':
                for item_id, item in manifest.items():
                    if 'cover-image' in item.get('properties', ''):
                        cover_id = item_id
                        break

    cover_href = None
    if cover_id and cover_id in manifest:
        cover_href = manifest[cover_id]['href']

    return {
        'metadata': metadata,
        'manifest': manifest,
        'spine': spine,
        'cover_id': cover_id,
        'cover_href': cover_href,
    }


def parse_epub(epub_path):
    """Parse an EPUB file and return structured content."""
    result = {
        'source': epub_path,
        'metadata': {},
        'chapters': [],
        'cover_path': None,
    }

    with zipfile.ZipFile(epub_path, 'r') as epub:
        # Parse OPF
        opf_path = extract_opf_path(epub)
        if not opf_path:
            print("Error: Could not find OPF file", file=sys.stderr)
            sys.exit(1)

        opf_data = parse_opf(epub, opf_path)
        result['metadata'] = opf_data['metadata']
        result['cover_path'] = opf_data.get('cover_href')

        # Extract chapters in spine order
        for idx, item_id in enumerate(opf_data['spine']):
            item = opf_data['manifest'][item_id]
            href = item['href']
            is_nav = 'nav' in item.get('properties', '')

            try:
                content = epub.read(href)
            except KeyError:
                # Try with different path separators
                try:
                    content = epub.read(href.replace('\\', '/'))
                except KeyError:
                    continue

            paragraphs = parse_xhtml(content)

            # Filter out very short paragraphs that are likely headers/nav
            content_paragraphs = []
            for p in paragraphs:
                text = p['text'].strip()
                if not text:
                    continue
                # Skip navigation items
                if is_nav and len(text) < 50:
                    continue
                content_paragraphs.append(p)

            chapter = {
                'id': item_id,
                'href': href,
                'index': idx,
                'title': f'Chapter {idx + 1}',
                'is_nav': is_nav,
                'paragraphs': content_paragraphs,
            }
            result['chapters'].append(chapter)

    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: parse_epub.py <epub_path> [output_json_path]", file=sys.stderr)
        sys.exit(1)

    epub_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None

    result = parse_epub(epub_path)

    # Statistics
    total_paragraphs = sum(len(ch['paragraphs']) for ch in result['chapters'])
    result['stats'] = {
        'total_chapters': len(result['chapters']),
        'content_chapters': len([ch for ch in result['chapters'] if not ch['is_nav']]),
        'total_paragraphs': total_paragraphs,
    }

    json_output = json.dumps(result, ensure_ascii=False, indent=2)

    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(json_output)
        print(f"Parsed {epub_path} -> {output_path}")
        print(f"  Chapters: {result['stats']['content_chapters']} content + {result['stats']['total_chapters'] - result['stats']['content_chapters']} nav")
        print(f"  Paragraphs: {total_paragraphs}")
    else:
        print(json_output)


if __name__ == '__main__':
    main()
