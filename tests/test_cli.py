import shutil
from pathlib import Path

import pytest

from markdown2anki.cli import main
from markdown2anki.config import load_config, render_toml, Config

NOTE = """---
---
# Parsing
---
What is a token?
A **lexical unit**
---
ADDED: already exported
answer
---
Cloze
A {{c1::grammar}} defines syntax
---
Code?
```c
#CODE#
int x;
```
"""


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    (v / "50.054 Compiler" / "Anki - Lectures").mkdir(parents=True)
    (v / "50.054 Compiler" / "Anki - Lectures" / "W01 Intro.md").write_text(NOTE, encoding="utf-8")
    (v / "50.054 Compiler" / "Unknown").mkdir()
    (v / "50.054 Compiler" / "Unknown" / "x.md").write_text("---\nq\na\n", encoding="utf-8")
    (v / "Archive" / "Old" / "Anki - Lectures").mkdir(parents=True)
    (v / "templates").mkdir()
    cfg = Config(vault=v, package_name="Test", base_tag="SUTD", output_dir=tmp_path / "out")
    cfg_path = tmp_path / "m2a.toml"
    cfg_path.write_text(render_toml(cfg), encoding="utf-8")
    return v, cfg_path


def run(*argv):
    return main([str(a) for a in argv])


def test_config_roundtrip(vault):
    v, cfg_path = vault
    cfg = load_config(cfg_path)
    assert cfg.vault == v and cfg.base_tag == "SUTD" and cfg.ignore == [".git", ".obsidian", "Archive", "templates"]
    assert cfg.subject_tag("50.054 Compiler") == "50.054_Compiler"
    assert cfg.subject_tag("Archive") is None


def test_check_and_status(vault, capsys):
    v, cfg_path = vault
    assert run("-c", cfg_path, "check") == 0
    out = capsys.readouterr().out
    assert "cards: 4" in out and "pending: 3" in out and "added: 1" in out
    assert "under 'Unknown'" in out

    run("-c", cfg_path, "status")
    out = capsys.readouterr().out
    assert "50.054 Compiler / Anki - Lectures" in out


def test_sync_dry_run_writes_nothing(vault, capsys):
    v, cfg_path = vault
    before = (v / "50.054 Compiler" / "Anki - Lectures" / "W01 Intro.md").read_text(encoding="utf-8")
    assert run("-c", cfg_path, "sync", "--dry-run") == 0
    assert "3 new" in capsys.readouterr().out
    assert (v / "50.054 Compiler" / "Anki - Lectures" / "W01 Intro.md").read_text(encoding="utf-8") == before
    assert not (cfg_path.parent / "out").exists()


def test_sync_apkg_flags_and_update(vault, capsys, tmp_path):
    v, cfg_path = vault
    note = v / "50.054 Compiler" / "Anki - Lectures" / "W01 Intro.md"
    assert run("-c", cfg_path, "sync", "--yes") == 0
    out = capsys.readouterr().out
    assert (tmp_path / "out" / "Test.apkg").is_file()
    assert "flagged 3 card(s)" in out

    text = note.read_text(encoding="utf-8")
    assert text.count("ADDED[") == 3 and "ADDED: already exported" in text
    assert text.split("What is a token?")[0].endswith("]: ") and "ADDED[" in text.split("What is a token?")[0][-18:]

    # second run: nothing pending
    assert run("-c", cfg_path, "sync", "--yes") == 0
    assert "nothing to export" in capsys.readouterr().out

    # --update re-exports the three cards with ids, but never the legacy one
    assert run("-c", cfg_path, "sync", "--yes", "--update", "--dry-run") == 0
    out = capsys.readouterr().out
    assert "3 update(s)" in out and "0 new" in out


def test_flag_guard_when_note_edited(vault, capsys, monkeypatch):
    from markdown2anki import flags as flags_module
    from markdown2anki.parser import Card
    v, cfg_path = vault
    note = v / "50.054 Compiler" / "Anki - Lectures" / "W01 Intro.md"
    card = Card(file=note, line=4, question="What is a token?", answer="", tag="t")
    note.write_text(NOTE.replace("What is a token?", "What is a lexeme?"), encoding="utf-8")
    flagged, problems = flags_module.write_flags([(card, "deadbeef")])
    assert flagged == 0 and problems and "changed since parsing" in problems[0]


def test_init_migrates_env(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        'BASE_TAG=SUTD\nOBSIDIAN_VAULT_DIRECTORY=/tmp/vault\nPACKAGE_NAME=SUTD-Anki\n'
        'SUBJECT_TAG_DICTIONARY={"50.020 Network Security": "50.020_NetSec"}\n'
        'SUB_DIRECTORY_TAG_DICTIONARY={"Anki - Lectures": "Lectures", "Anki - Exercises": "Exercises"}\n'
        'IGNORE_DIRECTORIES=[".git", "Archive", "Exercises"]\n', encoding="utf-8")
    assert run("init") == 0
    cfg = load_config(tmp_path / "m2a.toml")
    assert cfg.package_name == "SUTD-Anki"
    assert cfg.subjects == {"50.020 Network Security": "50.020_NetSec"}
    assert "Exercises" not in cfg.ignore
    assert cfg.display["50.020_NetSec"] == "50.020 Network Security"


def test_cloze_notes_is_opt_in(vault):
    from markdown2anki.build import MODEL_BASIC, MODEL_CLOZE, build
    from markdown2anki.parser import parse_lines
    from pathlib import Path
    cards = parse_lines(["---", "Cloze", "A {{c1::grammar}} defines syntax"], Path("n.md"), "B")
    legacy = build(cards, [])
    assert legacy.notes[0].model == MODEL_BASIC and "TODO_PROCESS_CLOZES" in legacy.notes[0].tags
    real = build(cards, [], cloze_notes=True)
    assert real.notes[0].model == MODEL_CLOZE and "TODO_PROCESS_CLOZES" not in real.notes[0].tags
