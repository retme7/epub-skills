# EPUB Bilingual Translator

A CodeBuddy Code skill that translates EPUB ebooks paragraph-by-paragraph into Chinese, producing a bilingual EPUB with the original text and Chinese translation side by side.

The original EPUB formatting — cover, styles, images, fonts, layout — is fully preserved. Only translation paragraphs are inserted after each original. Vertical writing mode (e.g., Japanese 縦書き) is automatically converted to horizontal mode to match Chinese reading habits.

## How It Works

The workflow follows a **Parse → Translate → Build** pipeline:

1. **Parse** — Extract all paragraphs and metadata from the source EPUB into a JSON manifest.
2. **Translate** — Translate each paragraph to Chinese and build a translations JSON.
3. **Build** — Patch the original EPUB by inserting translation paragraphs and bilingual CSS.

Steps 1 and 3 are handled by Python scripts (no external dependencies). Step 2 is done by the AI model.

## Usage

```bash
# Phase 1: Parse the EPUB
python3 epub-bilingual-translator/scripts/parse_epub.py input.epub parsed.json

# Phase 2: Translate (AI produces translations.json)
# Use json.dump() to write the file — manual writing can break with Chinese characters

# Phase 3: Build the bilingual EPUB
python3 epub-bilingual-translator/scripts/build_bilingual_epub.py \
  parsed.json translations.json output.epub input.epub
```

### Translation JSON format

```json
{
  "0": {
    "0": "那是最好的时代……",
    "1": "下一段的翻译……"
  },
  "1": {
    "0": "第一章的翻译……"
  }
}
```

Both chapter and paragraph indices must be **string keys**.

### Translating specific chapters only

Include only the chapters you want translated in the JSON. Untranslated chapters remain untouched in the output.

## Requirements

- Python 3 (standard library only — no pip install needed)

## File Layout

```
epub-bilingual-translator/
├── SKILL.md                          # Skill instructions for the AI
├── scripts/
│   ├── parse_epub.py                 # EPUB → JSON
│   └── build_bilingual_epub.py       # JSON + translations → bilingual EPUB
├── evals/
│   └── evals.json                    # Eval test cases
├── assets/
└── references/
```

## Installing as a CodeBuddy Skill

```bash
cp -r epub-bilingual-translator/* ~/.codebuddy/skills/epub-bilingual-translator/
```

## License

MIT
