# CODEBUDDY.md

This file provides guidance to CodeBuddy Code when working with code in this repository.

## Project Overview

This repo contains `epub-bilingual-translator`, a CodeBuddy Code skill that translates EPUB ebooks paragraph-by-paragraph into Chinese, producing a bilingual EPUB with original text and Chinese translation side by side. It operates as a CodeBuddy user skill installed at `~/.codebuddy/skills/epub-bilingual-translator/`.

## Skill Architecture

The skill follows a **Parse → Translate → Build** three-phase pipeline:

### Phase 1: `scripts/parse_epub.py`
Unzips the EPUB (which is a ZIP archive), reads `META-INF/container.xml` to find the OPF file, parses the OPF for spine order and metadata, then extracts paragraph text from each XHTML chapter using an `HTMLParser` subclass. Outputs a JSON manifest with chapter indices, paragraph indices, and text content.

### Phase 2: AI Translation (no script)
The AI model reads the parsed JSON, translates each paragraph to Chinese, and writes a translations JSON. Translation JSON structure: `{chapter_index_str: {paragraph_index_str: "翻译文本"}}`. String keys are mandatory.

### Phase 3: `scripts/build_bilingual_epub.py`
Operates in **patch mode** — copies the entire original EPUB as-is, then only modifies XHTML chapter files that have translations. For each translated paragraph, it finds the closing `</p>` tag in the raw XHTML and inserts a `<p class="bilingual-trans">` element right after it. Appends bilingual CSS to the original stylesheet. Everything else (cover, images, fonts, metadata, original CSS classes) is preserved unchanged.

### Key design decisions
- **Patch mode, not rebuild**: The builder modifies the original EPUB in-place rather than reconstructing it from scratch. This preserves original formatting, cover images, embedded fonts, and complex CSS that would be lost in a rebuild.
- **Tag-stripping fallback for paragraph matching**: XHTML paragraphs can contain inline tags like `<span>` that split the text. The builder first tries a simple substring match (fast path), and falls back to searching in a tag-stripped version of the XHTML to locate the paragraph, then maps back to find the closing block tag.
- **Reverse-order insertion**: When inserting multiple translation paragraphs, the builder sorts insertions by position in reverse order so earlier insertions don't shift the character offsets of later ones.

## Running the Scripts

```bash
# Parse an EPUB into a JSON manifest
python3 epub-bilingual-translator/scripts/parse_epub.py input.epub parsed.json

# Build a bilingual EPUB (source EPUB path is required)
python3 epub-bilingual-translator/scripts/build_bilingual_epub.py parsed.json translations.json output.epub input.epub
```

No external Python dependencies — both scripts use only the standard library (`zipfile`, `json`, `html.parser`, `xml.etree.ElementTree`, `re`).

## Testing

There is no automated test suite. Manual testing workflow:

1. Use the sample EPUB at `test/The_Last_Lantern.epub` (generated from `test/txt/test.md`)
2. Parse → Translate → Build
3. Validate the output EPUB: check it's a valid ZIP with correct `mimetype`, contains Chinese characters, preserves original English text and CSS classes, and the `bilingual-trans` class appears in translated chapters

```bash
# Quick validation of an EPUB
python3 -c "
import zipfile
with zipfile.ZipFile('output.epub') as zf:
    assert zf.read('mimetype').decode().strip() == 'application/epub+zip'
    print('Valid EPUB structure')
"
```

## File Layout

```
epub-bilingual-translator/       # The skill directory
├── SKILL.md                     # Skill description + workflow instructions for the AI
├── scripts/
│   ├── parse_epub.py            # Phase 1: EPUB → JSON
│   └── build_bilingual_epub.py  # Phase 3: JSON + translations → bilingual EPUB
├── evals/
│   └── evals.json               # Eval test cases for skill quality
├── assets/                      # Empty (placeholder)
└── references/                  # Empty (placeholder)

test/                            # Test data
├── txt/test.md                  # Source markdown for sample EPUB
├── The_Last_Lantern.epub        # Sample EPUB generated from test.md
└── ...                          # Other test artifacts
```

## Installing/Updating the Skill

The skill must be synced to `~/.codebuddy/skills/epub-bilingual-translator/` after changes:

```bash
cp -r epub-bilingual-translator/* ~/.codebuddy/skills/epub-bilingual-translator/
```

## Important Implementation Details

- **Translations JSON must use `json.dump()`**, not the Write tool — Chinese quotation marks ("") and other special characters break JSON when written as raw text.
- **Paragraph matching with `<span>` tags**: Some EPUBs wrap text fragments in `<span class="...">` for emphasis. The parser strips these during extraction, but the raw XHTML retains them. The builder's `find_paragraph_block_end()` function handles this via tag-stripping fallback.
- **Short paragraphs**: Single-character headings like `<h1>1</h1>` are intentionally skipped during translation insertion because the text is too short for reliable matching.
- **CSS is appended, not replaced**: The `BILINGUAL_CSS_APPEND` constant in `build_bilingual_epub.py` is appended to the first CSS file found in the OPF manifest, preserving all original styles.
- **Vertical→Horizontal writing mode**: When the source EPUB uses vertical writing mode (e.g., Japanese 縦書き with `writing-mode: vertical-rl`), the builder detects it via `is_vertical_writing_epub()` and appends `VERTICAL_TO_HORIZONTAL_CSS` before the bilingual CSS. This overrides `writing-mode` to `horizontal-tb` and neutralizes vertical-only properties (`text-orientation`, `text-combine-upright`) using `!important`.
