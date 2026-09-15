# Markdown2Anki

Turn flashcard notes written in Obsidian into Anki cards. One command exports everything that is new,
marks it as added in the notes, and can update cards later when you fix them.

## Getting started

```
git clone <this repo> && cd Markdown2Anki
python3 -m venv .venv && source .venv/bin/activate
pip install -e .                                  # gives you the `m2a` command
m2a init --vault ~/Documents/obsidian             # writes ~/.config/m2a/m2a.toml, lists the courses it found
m2a check                                         # parses every note, reports problems, changes nothing
m2a sync --dry-run                                # shows what the first export would contain
m2a sync                                          # exports, then asks before flagging the notes
```

Prefer `m2a` available from any terminal? `pipx install -e .` instead of the venv.

Two ways to get cards into Anki:

- **Package file** (`target = "apkg"`): `m2a sync` writes `output/<package_name>.apkg`; import it in Anki
  with File → Import. Re-importing a package with changed cards updates them (Anki matches the GUID).
- **AnkiConnect** (`target = "anki"`): install the
  [AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on (code `2055492159`), keep Anki
  open, and `m2a sync` pushes the cards straight into the deck - no import step.

Both targets embed the same id in the note, so a card can be updated through either one later.

**Trying it on a throw-away Anki profile first?** Run `m2a sync --no-flag`. Flags written against a test
profile carry ids that mean nothing in your real one.

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
Exported as a basic note tagged TODO_PROCESS_CLOZES, deletions added by hand in Anki.
With `cloze_notes = true` in the config, {{c1::deletions}} here become a real cloze note.

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
2. Export them - `.apkg`, or straight into a running Anki via `--target anki` (needs the
   [AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on). `target` in the config sets the default.
3. Ask, then flag each exported question: `ADDED: <question> %%k3f9qz%%`. The `%%…%%` part is an Obsidian
   comment (hidden in reading view) holding a short id; the same id is embedded invisibly in the Anki note.

```
m2a sync --dry-run            # list what would be exported
m2a sync --course compiler    # only courses whose folder or tag matches (glob or substring)
m2a sync --no-flag            # export without touching the notes
m2a sync --update             # re-export flagged cards too -> updates them in Anki
m2a unflag --course compiler  # drop ADDED flags -> cards go out again as NEW notes (--legacy / --file)
m2a sync --target anki -y     # push via AnkiConnect without asking
```

Flags are written only after the export succeeded, and only if the question line is still what was
parsed. Cards flagged by an older version (`ADDED: ` without id) are skipped and cannot be updated.

Updates work through either target: an `.apkg` re-import matches the note by GUID (derived from the id),
AnkiConnect finds it by the embedded `<!--m2a:id-->` marker. A card that is not in Anki any more (deleted,
other profile) is skipped with a warning.

To export a card **again as a new note** - after a test on a throw-away profile, after deleting it in
Anki, or to move old `ADDED:` cards to the new flow - remove its flag with `m2a unflag` (filters:
`--course`, `--file`, `--legacy`). It lists the cards and asks before touching the notes.

The deck id is derived from the deck name and note GUIDs from the card id, so re-importing an `.apkg`
updates notes instead of duplicating them.

## Configuration - `m2a.toml`

Created by `m2a init`, which refuses to overwrite an existing config (`--force` replaces it and keeps a
`.bak`). Lives in `~/.config/m2a/m2a.toml` so `m2a` works from any directory; `m2a init --here` writes it
to the current directory instead (a legacy `.env` there is migrated). Lookup order: `-c path`, then
`m2a.toml` in the current directory or any parent, then the user config. `m2a config` shows which one is
in use.

```toml
vault = "~/Documents/obsidian"
package_name = "SUTD-Anki"
deck = "SUTD-Anki"            # use :: for subdecks
base_tag = "SUTD"
output_dir = "output"
target = "anki"               # default for `m2a sync`; "apkg" writes a package file instead
cloze_notes = true            # {{c1::}} markers in a Cloze card -> real cloze note
ignore = [".git", ".obsidian", "Archive", "templates"]

[subjects]                    # folder -> tag; empty table = every folder, tag = folder name
"50.054 Compiler Design and Program Analysis" = "50.054_Compiler"

[subdirectories]              # folder inside a course -> tag
"Anki - Lectures" = "Lectures"
"Anki - Exercises" = "Exercises"

[display]                     # tag -> title shown in the corner of the card; first match wins
"50.054_Compiler" = "Compiler Design and Program Analysis"
```

## Card templates and note types - nothing changes unless you opt in

`markdown2anki/NoteTypes/{Basic,Cloze}/{front,back}.html` and `styling.css` are your personal templates,
git-ignored and used **verbatim** - the exported note types keep the same ids, names, fields, templates
and CSS as before. The bundled `*.sample.*` files are only used when a personal file is missing.

Optional: put `__M2A_SUBJECT_SCRIPT__` into a template and it is replaced with a script that shows the
`[display]` title for the card's tag. Without the placeholder nothing is injected.

`cloze_notes = false` (default) keeps the legacy behaviour: a `Cloze` card is exported as a basic note
tagged `TODO_PROCESS_CLOZES` for you to convert in Anki. Set it to `true` to export cards whose answer
already contains `{{c1::...}}` as real cloze notes.

`--target anki` first looks for the note types that earlier `.apkg` imports created (by their ids, so a
stock note type with the same name is never picked by mistake); otherwise it uses the names in
`anki_basic_model` / `anki_cloze_model`, creating them from the templates if missing. Existing note types
are never modified.

## Development

```
pip install -e .[dev]
pytest
```

`basic_adding_from_input.py` and `add_files_from_university_vault.py` are the pre-CLI scripts and still run
on the shared library code.
