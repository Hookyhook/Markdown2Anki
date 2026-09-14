# Markdown2Anki

Turn flashcard notes written in Obsidian into Anki cards. One command exports everything that is new,
marks it as added in the notes, and can update cards later when you fix them.

```
pip install -e .          # once; gives you the `m2a` command
m2a init --vault ~/Documents/obsidian
m2a check                 # parse everything, report problems, change nothing
m2a status                # per course: total / added / pending
m2a sync                  # export pending cards -> output/<package>.apkg, then flag them
```

## How the vault is read

```
<vault>/
├── 50.054 Compiler Design and Program Analysis/     course  -> subject tag
│   ├── Anki - Lectures/                             folder  -> category tag
│   │   ├── W01 Introduction.md                      note    -> tag, one card per block
│   │   └── Pasted image 2026....png                 images live next to the note
│   └── Anki - Exercises/
├── Archive/                                         ignored
└── templates/                                       ignored
```

Exactly two levels: `<course>/<subdirectory>/*.md`. Every top-level folder that is not in `ignore` is a
course (or list them explicitly in `[subjects]`); every subfolder must be in `[subdirectories]`, anything
else is reported by `m2a check`. Cards are tagged `base_tag::subject::category::note::heading::subheading`.

## Note format

```markdown
# Heading                        -> extra tag; ## nests below it
---
A question on the first line
EQL: an extra question line
The answer: any markdown - **bold**, lists, `code`, $x^2$, $$display math$$, ![[image.png]]

---
Cloze
Text with {{c1::deletions}} becomes a real cloze note.
Without markers it is exported as a basic note tagged TODO_PROCESS_CLOZES (legacy).

---
Image Cloze
![[diagram.png]]                 -> image copied to output/occlusions/<tag>/ for manual occlusion

---
Question about code?
```c
#CODE#                           -> tagged TODO_PROCESS_CODE; the marker line is removed
int x = 1;
```
```

Rules: a line of `---` starts a card; the next non-empty line is the question; everything up to the next
separator or heading is the answer. Blank slots (`---` followed by blank lines) are ignored. Fenced code,
inline code and math are never touched by symbol replacement or the markdown parser; `->` and `=>` in
prose become `→` and `⇒`. `$5 and $10` is prose, `$x$` is math.

## What `sync` does

1. Parse all notes, build the pending cards (and, with `--update`, the already-added ones that have an id).
2. Export them - `.apkg` by default, or straight into a running Anki with `--target anki` (needs the
   [AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on).
3. Ask, then write `ADDED[<id>]: ` in front of each exported question, so the next run skips it.

```
m2a sync --dry-run            # list what would be exported
m2a sync --course compiler    # only courses whose folder or tag matches (glob or substring)
m2a sync --no-flag            # export without touching the notes
m2a sync --update             # re-export flagged cards too -> updates them in Anki (same id, same GUID)
m2a sync --target anki -y     # push via AnkiConnect without asking
```

Flags are written only after the export succeeded, and only if the question line is still what was
parsed. Cards flagged by an older version (`ADDED: ` without id) are skipped and cannot be updated.

The deck id is derived from the deck name and note GUIDs from the card id, so re-importing an `.apkg`
updates notes instead of duplicating them.

## Configuration - `m2a.toml`

Created by `m2a init` (migrates a legacy `.env` if one exists) and searched for upwards from the current
directory; `-c path` overrides.

```toml
vault = "~/Documents/obsidian"
package_name = "SUTD-Anki"
deck = "SUTD-Anki"            # use :: for subdecks
base_tag = "SUTD"
output_dir = "output"
ignore = [".git", ".obsidian", "Archive", "templates"]

[subjects]                    # folder -> tag; empty table = every folder, tag = folder name
"50.054 Compiler Design and Program Analysis" = "50.054_Compiler"

[subdirectories]              # folder inside a course -> tag
"Anki - Lectures" = "Lectures"
"Anki - Exercises" = "Exercises"

[display]                     # tag -> title shown in the corner of the card; first match wins
"50.054_Compiler" = "Compiler Design and Program Analysis"
```

## Card templates

`markdown2anki/NoteTypes/{Basic,Cloze}/{front,back}.html` and `styling.css` are yours to customise and are
git-ignored; the bundled `*.sample.*` files are used when they are missing. `__M2A_SUBJECT_SCRIPT__` in a
template is replaced with the script that shows the `[display]` title.

## Development

```
pip install -e .[dev]
pytest
```

`basic_adding_from_input.py` and `add_files_from_university_vault.py` are the pre-CLI scripts and still run
on the shared library code.
