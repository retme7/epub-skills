#!/usr/bin/env python3
"""
EPUB Bilingual Builder — Patch-mode: preserves the original EPUB structure,
only inserting translation paragraphs after each original paragraph in XHTML files
that have translations, and appending bilingual CSS.
"""

import zipfile
import sys
import os
import json
import re
from html.parser import HTMLParser


def escape_xml(text):
    """Escape XML special characters."""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


# CSS to override vertical writing mode to horizontal (for CJK vertical EPUBs)
VERTICAL_TO_HORIZONTAL_CSS = '''

/* ===== Vertical → Horizontal Writing Mode Override ===== */

html, body {
    writing-mode: horizontal-tb !important;
    -webkit-writing-mode: horizontal-tb !important;
    -epub-writing-mode: horizontal-tb !important;
}

/* Neutralize text-orientation (only meaningful in vertical mode) */
* {
    text-orientation: mixed !important;
    -webkit-text-orientation: mixed !important;
    -epub-text-orientation: mixed !important;
}

/* Neutralize tate-chu-yoko / text-combine-upright (only meaningful in vertical mode) */
* {
    text-combine-upright: none !important;
    -webkit-text-combine-upright: none !important;
    -webkit-text-combine: none !important;
}
'''

# Bilingual CSS to append to the original stylesheet
BILINGUAL_CSS_APPEND = '''

/* ===== Bilingual Translation Styles (appended) ===== */

.bilingual-trans {
    margin: 0 0 0.8em 0;
    text-indent: 1.5em;
    color: #444;
    font-size: 0.95em;
    line-height: 1.7;
    font-family: "Songti SC", "STSong", "SimSun", "Noto Serif CJK SC", "PingFang SC", serif;
    border-left: 2px solid #ddd;
    padding-left: 0.8em;
    margin-left: 0.5em;
}

.bilingual-heading-cn {
    font-size: 0.9em;
    font-weight: normal;
    text-align: center;
    margin: 0 0 1.5em 0;
    color: #555;
    font-family: "Songti SC", "STSong", "SimSun", "Noto Serif CJK SC", "PingFang SC", serif;
}
'''


class ParagraphLocator(HTMLParser):
    """Locate <p> and <h1>-<h6> tags in XHTML and record their positions.
    We use this to find where to insert translation paragraphs.
    """

    BLOCK_TAGS = {'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}
    SKIP_TAGS = {'script', 'style', 'head'}

    def __init__(self):
        super().__init__()
        self.blocks = []  # list of (tag, text, start_pos, end_pos)
        self._tag_stack = []
        self._skip_depth = 0
        self._current_tag = None
        self._current_attrs = {}
        self._text_start = None
        self._tag_start = None
        self._full_text = ''
        # We need the raw HTML to get positions
        self.raw_html = ''

    def feed_with_raw(self, raw_html):
        self.raw_html = raw_html
        self.feed(raw_html)
        # After feeding, locate closing tags for each block
        self._locate_positions()

    def _locate_positions(self):
        """After parsing, find the exact character positions of each block tag
        in the raw HTML by matching the text content."""
        # For each block, find the closing </tag> position
        for i, block in enumerate(self.blocks):
            tag = block['tag']
            text = block['text']
            # Find the tag by searching for the text content within <tag...>...</tag>
            # We'll find the closing tag position
            self.blocks[i]['end_pos'] = self._find_closing_tag(tag, text, i)

    def _find_closing_tag(self, tag, text, block_index):
        """Find the position after the closing </tag> in raw HTML."""
        # Search for the text snippet to locate the tag, then find </tag> after it
        # Use a short unique prefix of the text
        search_text = text[:60].strip() if len(text) > 60 else text.strip()
        if not search_text:
            return -1

        pos = self.raw_html.find(search_text)
        if pos == -1:
            # Try with escaped entities
            search_escaped = escape_xml(text[:60]).strip() if len(text) > 60 else escape_xml(text).strip()
            pos = self.raw_html.find(search_escaped)
        if pos == -1:
            return -1

        # Find the closing tag after the text
        close_tag = f'</{tag}>'
        close_pos = self.raw_html.find(close_tag, pos)
        if close_pos == -1:
            return -1

        return close_pos + len(close_tag)

    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        self._tag_stack.append(tag_lower)

        if tag_lower in self.SKIP_TAGS:
            self._skip_depth += 1
            return

        if self._skip_depth > 0:
            return

        if tag_lower in self.BLOCK_TAGS:
            self._current_tag = tag_lower
            self._current_attrs = dict(attrs)

    def handle_endtag(self, tag):
        tag_lower = tag.lower()
        if self._tag_stack and self._tag_stack[-1] == tag_lower:
            self._tag_stack.pop()

        if tag_lower in self.SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return

        if self._skip_depth > 0:
            return

        if tag_lower in self.BLOCK_TAGS and self._current_tag == tag_lower:
            # Block complete — we don't capture text here since we locate by position
            self._current_tag = None

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        if self._current_tag and self._current_tag in self.BLOCK_TAGS:
            text = data.strip()
            if text:
                # Check if this is a new block or continuation
                existing = [b for b in self.blocks if b.get('_tag_active')]
                if existing:
                    # Append to existing block
                    existing[-1]['text'] += ' ' + text
                else:
                    self.blocks.append({
                        'tag': self._current_tag,
                        'text': text,
                        'attrs': self._current_attrs,
                        '_tag_active': True,
                    })


def strip_html_tags(html):
    """Remove all HTML tags from a string, leaving only text content."""
    return re.sub(r'<[^>]+>', '', html)


def find_paragraph_block_end(xhtml_content, para_text, para_tag, search_start=0):
    """Find the position after the closing </tag> for a paragraph containing the given text.

    Handles inline tags like <span> that split the text within a paragraph.
    Strategy: search in the tag-stripped version to locate the text, then map
    back to the original HTML to find the closing block tag.
    """
    # Build a stripped-text index: map each character position in the original
    # to the corresponding position in the stripped text.
    # We do this lazily — only strip the portion we need to search.

    # First try simple substring match (fast path, works when no inline tags)
    snippet = para_text.strip()
    if len(snippet) > 60:
        snippet = snippet[:60]

    pos = xhtml_content.find(snippet, search_start)
    if pos == -1:
        pos = xhtml_content.find(escape_xml(snippet), search_start)
    if pos >= 0:
        # Found directly — find the closing tag
        close_tag = f'</{para_tag}>'
        close_pos = xhtml_content.find(close_tag, pos)
        if close_pos >= 0:
            return close_pos + len(close_tag)

    # Fallback: search in tag-stripped text to handle <span> and other inline tags
    # Build a mapping from stripped-text positions to original positions
    stripped = []
    orig_map = []  # stripped_index -> original_index
    in_tag = False
    for i, ch in enumerate(xhtml_content):
        if ch == '<':
            in_tag = True
            continue
        if in_tag:
            if ch == '>':
                in_tag = False
            continue
        stripped.append(ch)
        orig_map.append(i)

    stripped_text = ''.join(stripped)

    # Search for the paragraph text in the stripped version
    search_text = para_text.strip()
    stripped_pos = stripped_text.find(search_text)
    if stripped_pos == -1:
        # Try shorter prefix
        search_text = para_text.strip()[:40]
        stripped_pos = stripped_text.find(search_text)
    if stripped_pos == -1:
        return -1

    # Map back to original position
    orig_pos = orig_map[stripped_pos]

    # Find the closing block tag after this position
    close_tag = f'</{para_tag}>'
    close_pos = xhtml_content.find(close_tag, orig_pos)
    if close_pos >= 0:
        return close_pos + len(close_tag)

    return -1


def insert_translations_into_xhtml(xhtml_content, translations, chapter_paragraphs):
    """Insert translation paragraphs into original XHTML content.

    Strategy: For each paragraph that has a translation, find the closing </p>
    tag and insert a new <p class="bilingual-trans">translation</p> right after it.
    Handles paragraphs that contain inline tags like <span> by searching in
    the tag-stripped version of the XHTML.
    """
    if not translations:
        return xhtml_content

    # Build ordered list of (para_index, tag, translation) to process
    para_translations = []
    for i, para in enumerate(chapter_paragraphs):
        trans = translations.get(str(i), '')
        if trans:
            para_translations.append((i, para['tag'], para['text'], trans))

    if not para_translations:
        return xhtml_content

    # Find the closing tag position for each paragraph, tracking the last
    # search position to avoid matching the same block twice
    insertions = []
    last_search_pos = 0

    for para_idx, para_tag, para_text, translation in para_translations:
        end_pos = find_paragraph_block_end(xhtml_content, para_text, para_tag, last_search_pos)
        if end_pos < 0:
            # Try from the beginning (might be out of order)
            end_pos = find_paragraph_block_end(xhtml_content, para_text, para_tag, 0)
        if end_pos < 0:
            continue

        last_search_pos = end_pos

        # Determine indentation from surrounding context
        line_start = xhtml_content.rfind('\n', 0, end_pos)
        indent = ''
        if line_start >= 0:
            # Look at the line that contains the opening tag — go back further
            # to find the line start of the <p> tag
            open_tag = f'<{para_tag}'
            open_pos = xhtml_content.rfind(open_tag, max(0, end_pos - 2000), end_pos)
            if open_pos >= 0:
                p_line_start = xhtml_content.rfind('\n', 0, open_pos)
                if p_line_start >= 0:
                    line_content = xhtml_content[p_line_start+1:open_pos]
                    indent_match = re.match(r'^(\s*)', line_content)
                    if indent_match:
                        indent = indent_match.group(1)

        # Build the translation paragraph
        if para_tag.startswith('h'):
            trans_html = f'\n{indent}<{para_tag} class="bilingual-heading-cn">{escape_xml(translation)}</{para_tag}>'
        else:
            trans_html = f'\n{indent}<p class="bilingual-trans">{escape_xml(translation)}</p>'

        insertions.append((end_pos, trans_html))

    # Sort insertions by position in reverse order to preserve offsets
    insertions.sort(key=lambda x: x[0], reverse=True)

    # Apply insertions
    result = xhtml_content
    for pos, html in insertions:
        result = result[:pos] + html + result[pos:]

    return result


def is_vertical_writing_epub(src_zip):
    """Detect if the EPUB uses vertical writing mode by checking CSS files."""
    for item in src_zip.infolist():
        name = item.filename
        if not name.endswith('.css'):
            continue
        try:
            css = src_zip.read(name).decode('utf-8')
        except Exception:
            continue
        if re.search(r'writing-mode\s*:\s*vertical-', css):
            return True
    return False


def find_css_files(opf_content, opf_dir=''):
    """Find CSS file paths referenced in the OPF manifest."""
    css_files = []
    # Look for <item ... media-type="text/css" .../>
    for match in re.finditer(r'<item[^>]+media-type=["\']text/css["\'][^>]*/?\s*>', opf_content):
        item = match.group()
        href_match = re.search(r'href=["\']([^"\']+)["\']', item)
        if href_match:
            href = href_match.group(1)
            if opf_dir:
                href = opf_dir + '/' + href
            css_files.append(href)
    return css_files


def build_bilingual_epub(parsed_data, translations_data, output_path, source_epub_path):
    """Build bilingual EPUB by patching the original — preserving all original formatting."""

    chapters = parsed_data.get('chapters', [])
    chapter_map = {}  # href -> chapter data
    for ch in chapters:
        chapter_map[ch['href']] = ch

    with zipfile.ZipFile(source_epub_path, 'r') as src_zip:
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as dst_zip:
            # mimetype must be first and uncompressed
            mt_data = src_zip.read('mimetype')
            dst_zip.writestr('mimetype', mt_data, compress_type=zipfile.ZIP_STORED)

            # Detect vertical writing mode
            is_vertical = is_vertical_writing_epub(src_zip)

            # Find the OPF path
            container_xml = src_zip.read('META-INF/container.xml').decode()
            opf_match = re.search(r'full-path=["\']([^"\']+)["\']', container_xml)
            opf_path = opf_match.group(1) if opf_match else 'OEBPS/content.opf'
            opf_dir = os.path.dirname(opf_path)

            # Read the OPF to find CSS files
            opf_content = src_zip.read(opf_path).decode()
            css_files = find_css_files(opf_content, opf_dir)

            # Track which CSS files we've already patched
            patched_css = set()

            translated_count = 0

            for item in src_zip.infolist():
                name = item.filename

                # Skip mimetype (already written)
                if name == 'mimetype':
                    continue

                # Read the file
                try:
                    data = src_zip.read(name)
                except Exception:
                    continue

                # Check if this is an XHTML chapter that needs translation
                if name in chapter_map and (name.endswith('.xhtml') or name.endswith('.html')):
                    ch = chapter_map[name]
                    ch_index = str(ch['index'])
                    ch_translations = translations_data.get(ch_index, {})

                    if ch_translations:
                        # This chapter has translations — insert them
                        try:
                            xhtml_content = data.decode('utf-8')
                        except UnicodeDecodeError:
                            xhtml_content = data.decode('utf-8', errors='replace')

                        modified = insert_translations_into_xhtml(
                            xhtml_content, ch_translations, ch['paragraphs']
                        )

                        if modified != xhtml_content:
                            translated_count += 1
                            data = modified.encode('utf-8')

                # Check if this is a CSS file — append overrides and bilingual styles
                if name in css_files and name not in patched_css:
                    try:
                        css_content = data.decode('utf-8')
                        if 'bilingual-trans' not in css_content:
                            if is_vertical:
                                css_content += VERTICAL_TO_HORIZONTAL_CSS
                            css_content += BILINGUAL_CSS_APPEND
                            data = css_content.encode('utf-8')
                            patched_css.add(name)
                    except UnicodeDecodeError:
                        pass

                # Write the file (possibly modified)
                dst_zip.writestr(item, data)

    return output_path, translated_count, is_vertical


def main():
    if len(sys.argv) < 5:
        print("Usage: build_bilingual_epub.py <parsed_json> <translations_json> <output_epub> <source_epub>", file=sys.stderr)
        sys.exit(1)

    parsed_path = sys.argv[1]
    translations_path = sys.argv[2]
    output_path = sys.argv[3]
    source_epub = sys.argv[4]

    with open(parsed_path, 'r', encoding='utf-8') as f:
        parsed_data = json.load(f)

    with open(translations_path, 'r', encoding='utf-8') as f:
        translations_data = json.load(f)

    result_path, translated_count, is_vertical = build_bilingual_epub(
        parsed_data, translations_data, output_path, source_epub
    )
    print(f"Bilingual EPUB created: {result_path}")
    print(f"  Chapters with translations inserted: {translated_count}")
    if is_vertical:
        print(f"  Vertical writing mode detected: overridden to horizontal-tb")
    print(f"  Original formatting preserved: yes")


if __name__ == '__main__':
    main()
