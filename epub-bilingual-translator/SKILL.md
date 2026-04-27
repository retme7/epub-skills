---
name: epub-bilingual-translator
description: >
  Translate an EPUB ebook paragraph-by-paragraph into Chinese and produce a new bilingual
  EPUB with original text and Chinese translation side by side. Use this skill whenever the
  user mentions translating an EPUB, creating a bilingual ebook, making a parallel-text EPUB,
  converting an English ebook to Chinese, or wants 原文/中文对照 or 中英对照 output from an
  EPUB file. Also trigger when the user mentions "epub翻译", "双语epub", "对照阅读", or
  wants paragraph-level translation of any ebook format.
---

# EPUB Bilingual Translator

This skill translates an EPUB ebook paragraph by paragraph into Chinese, then produces a bilingual EPUB where each original paragraph is immediately followed by its Chinese translation. The original EPUB formatting — cover, styles, images, fonts, layout — is fully preserved; only the translation paragraphs are inserted.

## How It Works

The workflow has three phases: **Parse → Translate → Build**. Two Python scripts handle the deterministic parts (parsing EPUB structure, patching the EPUB archive), while you (the AI) handle the translation itself. The scripts deal with the finicky ZIP+XML structure so you can focus on producing good translations.

## Phase 1: Parse the EPUB

Run the parser script to extract all paragraphs and metadata from the source EPUB:

```bash
python3 <skill-path>/scripts/parse_epub.py <input.epub> <output.json>
```

This produces a JSON file with this structure:

```json
{
  "source": "path/to/book.epub",
  "metadata": { "title": "...", "creator": "...", "language": "en" },
  "chapters": [
    {
      "id": "chapter1",
      "href": "OEBPS/chapter1.xhtml",
      "index": 0,
      "title": "Chapter 1",
      "is_nav": false,
      "paragraphs": [
        { "tag": "p", "text": "It was the best of times...", "attrs": {} },
        { "tag": "p", "text": "The next paragraph...", "attrs": {} }
      ]
    }
  ],
  "stats": { "total_chapters": 12, "total_paragraphs": 847 }
}
```

Read the output JSON. Chapters with `"is_nav": true` are navigation pages — skip them for translation. Also skip chapters with zero paragraphs (cover pages, blank pages).

## Phase 2: Translate

This is the core work. For each content chapter, translate every paragraph from its source language into Chinese.

### Translation approach

- Translate paragraph by paragraph, preserving the paragraph index so translations can be matched back to originals.
- Aim for natural, readable Chinese rather than word-for-word literal translation. The reader is trying to understand the original text, so faithfulness to meaning matters more than preserving syntax.
- Keep proper nouns in their commonly known Chinese form (e.g., "London" → "伦敦", "Elizabeth" → "伊丽莎白"). If a name has no established Chinese translation, transliterate and include the original in parentheses on first occurrence.
- For headings (h1-h6), translate them as well — the builder will insert a Chinese sub-heading after the original.
- If a paragraph is very short (under 5 characters) and appears to be a decorative separator like "***" or "—", you may skip translating it.

### Building the translations JSON

Create a JSON file with this structure — chapter indices as keys, each containing paragraph-index-to-translation mappings:

```json
{
  "0": {
    "0": "那是最美好的时代……",
    "1": "下一段的翻译……"
  },
  "1": {
    "0": "第一章的翻译……"
  }
}
```

The outer keys are chapter indices (as strings), the inner keys are paragraph indices within that chapter (as strings), and the values are the Chinese translations.

Important: use Python's `json.dump()` to write the translations JSON, not the Write tool. Chinese quotation marks ("") and other special characters can break JSON if written manually. Example:

```python
import json
translations = {"3": {"1": "翻译内容...", "2": "更多翻译..."}}
with open("translations.json", "w", encoding="utf-8") as f:
    json.dump(translations, f, ensure_ascii=False, indent=2)
```

### Handling large books

For books with many paragraphs, work in batches per chapter to avoid hitting context limits:

1. Read the parsed JSON.
2. For each content chapter, translate all its paragraphs and write the translations.
3. After translating all chapters, write the complete translations JSON.

If the book is very large (hundreds of paragraphs), you can translate a few chapters at a time, accumulating results into the translations JSON file.

## Phase 3: Build the Bilingual EPUB

Once the translations JSON is complete, run the builder script:

```bash
python3 <skill-path>/scripts/build_bilingual_epub.py \
  <parsed.json> \
  <translations.json> \
  <output.epub> \
  <source.epub>
```

The source EPUB path (fourth argument) is required. The builder operates in **patch mode**: it copies the entire original EPUB as-is, then only modifies the XHTML chapter files that have translations, inserting `<p class="bilingual-trans">` paragraphs after each original. It also appends bilingual CSS styles to the original stylesheet. Everything else — cover image, fonts, images, original CSS classes, layout, metadata — is preserved unchanged.

The result is a valid EPUB where:
- The original formatting, cover, and images are intact
- Each translated paragraph is inserted right after its original, styled with a subtle left border accent and CJK serif font
- Heading translations appear as smaller sub-headings below the originals
- Untranslated chapters remain exactly as they were

## Visual Layout

In the output EPUB, each paragraph pair looks like this:

```
It was the best of times, it was the worst of times...
  那是最美好的时代，那是最糟糕的时代……

In the year 1775, there was a king...
  一七七五年，有一位国王……
```

The original paragraph keeps its original CSS class and styling. The Chinese translation follows immediately, using the `bilingual-trans` class: slightly smaller text, gray color, left border accent, and a CJK serif font family. This creates a clear visual hierarchy.

## Common Patterns

### Quick one-shot translation

For a short EPUB (under ~50 paragraphs total), you can translate everything in one go:

```bash
# Parse
python3 scripts/parse_epub.py input.epub parsed.json

# (Translate all paragraphs, write translations.json via json.dump)

# Build
python3 scripts/build_bilingual_epub.py parsed.json translations.json output.epub input.epub
```

### Chapter-by-chapter for long books

For longer works, process chapters sequentially and accumulate translations:

```bash
# Parse once
python3 scripts/parse_epub.py input.epub parsed.json

# Translate chapter 0, write to translations.json
# Translate chapter 1, append to translations.json
# ...continue until done

# Build
python3 scripts/build_bilingual_epub.py parsed.json translations.json output.epub input.epub
```

### Translating only specific chapters

To translate just the first chapter (for testing or incremental work), only provide translations for that chapter's index in the translations JSON. Other chapters will remain untouched in the output.

## Troubleshooting

- **Parser finds no paragraphs**: The EPUB may use non-standard XHTML. Read the raw XHTML file from the EPUB (it's a ZIP archive) and examine the structure to adjust.
- **Missing translations in output**: Ensure the translations JSON uses string keys for both chapter and paragraph indices ("0", not 0).
- **Some paragraphs not matched**: The builder matches paragraphs by their text content. If the parser extracted different text (e.g., HTML entities decoded differently), the match may fail. Check the parsed JSON text against the raw XHTML.
- **Encoding issues**: Both scripts expect UTF-8. If the source EPUB uses a different encoding, the parser will attempt fallback decoding.
