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

This skill translates an EPUB ebook paragraph by paragraph into Chinese, then produces a bilingual EPUB where each original paragraph is immediately followed by its Chinese translation. The original EPUB formatting — cover, styles, images, fonts, layout — is fully preserved; only the translation paragraphs are inserted. If the source EPUB uses vertical writing mode (e.g., Japanese 縦書き books), the builder automatically overrides it to horizontal writing mode (横書き) to match Chinese reading habits.

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
- **For novels and literary works**: Polish the translation into natural, literary Chinese that captures the atmosphere and tone of the original. The goal is for the Chinese reader to feel the same mood and rhythm as a reader of the original — not a stiff, literal rendering, but prose that breathes and flows like it was originally written in Chinese. Pay attention to sentence rhythm, word choice, and stylistic consistency. Avoid translationese (翻译腔).
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

### Batch size limit per chapter

If a single content chapter contains **more than 200 paragraphs**, split it into smaller batches (up to 200 paragraphs per batch) before translating. Translating too many paragraphs at once can exceed context limits or cause failures.

**How to split:**
- Divide the chapter's paragraphs sequentially into batches of ~200. For example, a 450-paragraph chapter becomes three batches: paragraphs 0–199, 200–399, and 400–449.
- Translate each batch separately, preserving the original paragraph indices.
- Merge all batches of the same chapter into one chapter entry in the translations JSON.

**Example:** Chapter 5 has 450 paragraphs. After translating three batches, the merged translations JSON still uses a single chapter key `"5"`:

```json
{
  "5": {
    "0": "...",
    "1": "...",
    ...
    "199": "...",
    "200": "...",
    ...
    "449": "..."
  }
}
```

### Handling large books

For books with many paragraphs, work chapter by chapter (and batch by batch for large chapters) to avoid hitting context limits:

1. Read the parsed JSON.
2. For each content chapter, check its paragraph count. If it exceeds 200, split it into batches of ~200 paragraphs and translate each batch separately.
3. Accumulate translations and write the complete translations JSON after all chapters and batches are done.

If the book is very large (hundreds of paragraphs), you can translate a few chapters (or batches) at a time, accumulating results into the translations JSON file.

### Parallel translation with agent teams

For books with many content chapters (roughly 8+ chapters), use `TeamCreate` to spawn multiple translator agents that work on different chapters in parallel. This can significantly reduce total translation time.

**When to use team-based parallel translation:**
- The book has 8+ content chapters (after excluding nav/cover chapters)
- Each chapter has enough paragraphs to justify an agent (roughly 10+ paragraphs per chapter)
- The parsed JSON is available and has been read to identify content chapter indices

**Workflow:**

1. **Parse the EPUB** (as usual, single agent).
2. **Identify content chapters** from the parsed JSON — skip chapters with `"is_nav": true` or zero paragraphs.
3. **Determine translation units.** A unit is either:
   - A whole chapter with ≤ 200 paragraphs, or
   - A single batch of a large chapter (e.g., paragraphs 0–199, 200–399, etc.).
4. **Create a team** with `TeamCreate`.
5. **Split units among translator agents.** A reasonable split is 1–3 units per agent, depending on size. Assign each agent a disjoint set of units. For a chapter with 450 paragraphs, you might assign the three batches to three separate agents, or give all three batches to one agent if its context can handle ~450 paragraphs.
6. **Spawn translator agents** (one per batch), each running in the background. Each agent:
   - Reads the parsed JSON to get the paragraphs for its assigned units.
   - Translates only the paragraphs in its assigned units following the standard translation approach.
   - Writes its translations to a **separate file** named `translations_ch{chapter_index}_batch{batch_index}.json` (or `translations_ch{start}-{end}.json` for whole chapters) using `json.dump()` (not the Write tool). The file uses the same translations JSON structure, but only contains the chapters (and paragraph indices) that agent was assigned.
7. **Wait for all agents to complete.** Check the task list for completion status.
8. **Merge all partial translation files** into a single `translations.json` using Python:

```python
import json, glob

merged = {}
for path in sorted(glob.glob("translations_ch*.json")):
    with open(path, encoding="utf-8") as f:
        partial = json.load(f)
        for ch_idx, paras in partial.items():
            if ch_idx not in merged:
                merged[ch_idx] = {}
            merged[ch_idx].update(paras)

with open("translations.json", "w", encoding="utf-8") as f:
    json.dump(merged, f, ensure_ascii=False, indent=2)
```

9. **Build the bilingual EPUB** with the merged translations (as usual, single agent).
10. **Clean up** the team with `TeamDelete` and remove partial translation files.

**Prompt template for translator agents:**

Each spawned translator agent should receive a prompt like:

```
You are translating part of an EPUB book into Chinese.

Read the file {parsed_json_path}. From the "chapters" array, translate only the assigned units:
{unit_description}

Follow these translation rules:
- Translate paragraph by paragraph, preserving paragraph indices exactly as they appear in the source JSON.
- Aim for natural, readable Chinese. For literary works, produce polished prose that captures the atmosphere and tone — avoid translationese (翻译腔).
- Keep proper nouns in their commonly known Chinese form. If no established translation exists, transliterate and include the original in parentheses on first occurrence.
- Translate headings (h1-h6) as well.
- Skip very short decorative separators (under 5 characters, like "***" or "—").

Write the translations to {output_path} using json.dump() with ensure_ascii=False. The JSON structure must be:
{{"chapter_index_str": {{"paragraph_index_str": "翻译文本"}}}}

Use string keys for both chapter and paragraph indices. Only include chapters and paragraphs that you were assigned.
```

**Important considerations:**
- Each agent must write to its **own** output file to avoid conflicts. Never have multiple agents write to the same file.
- The merge step is sequential — do not build the EPUB until all agents finish and the merge is complete.
- Agent context limits still apply per-agent. If a single unit (e.g., 200 paragraphs) is too large for one agent, reduce the batch size to ~100 paragraphs.
- For consistency of tone and terminology across chapters, include the translation rules in every agent's prompt. If the book has a glossary or recurring proper nouns, include them in the prompt as well.

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

### Vertical → Horizontal Writing Mode

The builder automatically detects whether the source EPUB uses vertical writing mode (e.g., Japanese 縦書き with `writing-mode: vertical-rl`). When detected, it appends CSS overrides that force the entire book into horizontal writing mode (`writing-mode: horizontal-tb`) to match Chinese reading habits. This also neutralizes vertical-mode-only CSS properties like `text-orientation: sideways` and `text-combine-upright` (縦中横). The output will print `Vertical writing mode detected: overridden to horizontal-tb` when this conversion is applied.

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

### Parallel translation for large books

For books with 8+ content chapters, use an agent team to translate chapters in parallel. If a chapter exceeds 200 paragraphs, split it into batches and distribute the batches among agents:

```bash
# Parse once
python3 scripts/parse_epub.py input.epub parsed.json

# (Create team, spawn translator agents — each writes translations_ch*.json)

# Merge all partial files into one
python3 -c "
import json, glob
merged = {}
for p in sorted(glob.glob('translations_ch*.json')):
    with open(p, encoding='utf-8') as f:
        partial = json.load(f)
        for ch_idx, paras in partial.items():
            if ch_idx not in merged:
                merged[ch_idx] = {}
            merged[ch_idx].update(paras)
with open('translations.json', 'w', encoding='utf-8') as f:
    json.dump(merged, f, ensure_ascii=False, indent=2)
"

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
