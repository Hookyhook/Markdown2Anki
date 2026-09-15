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
    cfg = Config(vault=v, package_name="Test", base_tag="SUTD", output_dir=tmp_path / "out", target="apkg")
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
    assert "cards 4" in out and "pending 3" in out and "added 1" in out
    assert "under 'Unknown'" in out

    run("-c", cfg_path, "status")
    out = capsys.readouterr().out
    assert "50.054 Compiler / Anki - Lectures" in out


def test_sync_dry_run_writes_nothing(vault, capsys):
    v, cfg_path = vault
    before = (v / "50.054 Compiler" / "Anki - Lectures" / "W01 Intro.md").read_text(encoding="utf-8")
    assert run("-c", cfg_path, "sync", "--dry-run") == 0
    assert "new 3" in capsys.readouterr().out
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
    import re
    assert len(re.findall(r"%%[0-9a-z]{6}%%", text)) == 3 and "ADDED: already exported\n" in text
    assert re.search(r"^ADDED: What is a token\? %%[0-9a-z]{6}%%$", text, re.M)

    # second run: nothing pending
    assert run("-c", cfg_path, "sync", "--yes") == 0
    assert "nothing to export" in capsys.readouterr().out

    # --update re-exports the three cards with ids, but never the legacy one
    assert run("-c", cfg_path, "sync", "--yes", "--update", "--dry-run") == 0
    out = capsys.readouterr().out
    assert "updates 3" in out and "new 0" in out


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
    (tmp_path / "vault" / "50.020 Network Security" / "Anki - Lectures").mkdir(parents=True)
    (tmp_path / ".env").write_text(
        f'BASE_TAG=SUTD\nOBSIDIAN_VAULT_DIRECTORY={tmp_path / "vault"}\nPACKAGE_NAME=SUTD-Anki\n'
        'SUBJECT_TAG_DICTIONARY={"50.020 Network Security": "50.020_NetSec"}\n'
        'SUB_DIRECTORY_TAG_DICTIONARY={"Anki - Lectures": "Lectures", "Anki - Exercises": "Exercises"}\n'
        'IGNORE_DIRECTORIES=[".git", "Archive", "Exercises"]\n', encoding="utf-8")
    assert run("init", "--here") == 0
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


def test_target_comes_from_config(vault, capsys, monkeypatch):
    v, cfg_path = vault
    cfg_path.write_text(cfg_path.read_text(encoding="utf-8").replace('target = "apkg"', 'target = "anki"'), encoding="utf-8")
    from markdown2anki.export import ankiconnect

    def boom(self, action, **params):
        raise ankiconnect.AnkiConnectError("cannot reach AnkiConnect")
    monkeypatch.setattr(ankiconnect.AnkiConnect, "invoke", boom)
    assert run("-c", cfg_path, "sync", "--yes") == 2
    assert "cannot reach AnkiConnect" in capsys.readouterr().err
    assert run("-c", cfg_path, "sync", "--yes", "--target", "apkg") == 0


def test_init_refuses_a_vault_without_courses(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "empty").mkdir()
    assert run("init", "--vault", tmp_path / "empty") == 2
    assert "no course folders" in capsys.readouterr().err
    assert not (tmp_path / "m2a.toml").exists()


def test_update_across_targets_is_refused(vault, capsys, monkeypatch):
    v, cfg_path = vault
    note = v / "50.054 Compiler" / "Anki - Lectures" / "W01 Intro.md"
    note.write_text(note.read_text(encoding="utf-8").replace("What is a token?", "ADDED[n4242]: What is a token?"),
                    encoding="utf-8")
    assert run("-c", cfg_path, "sync", "--yes", "--update", "--no-flag") == 0
    out = capsys.readouterr().out
    assert "an .apkg cannot update it" in out and "new 2" in out


def test_init_writes_user_config_by_default_and_refuses_twice(tmp_path, monkeypatch, capsys):
    import os
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vault" / "50.020 Network Security" / "Anki - Lectures").mkdir(parents=True)
    assert run("init", "--vault", tmp_path / "vault") == 0
    written = Path(os.environ["XDG_CONFIG_HOME"]) / "m2a" / "m2a.toml"
    assert written.is_file()
    assert "next:" in capsys.readouterr().out
    # found from any directory
    monkeypatch.chdir(tmp_path / "vault")
    assert run("status") == 0
    # a second init refuses...
    assert run("init", "--vault", tmp_path / "vault") == 1
    assert "already exists" in capsys.readouterr().err
    # ...unless forced, which keeps a backup
    assert run("init", "--vault", tmp_path / "vault", "--force") == 0
    assert written.with_suffix(".toml.bak").is_file()


def test_init_needs_a_vault(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert run("init") == 2
    assert "--vault" in capsys.readouterr().err


def test_unflag(vault, capsys):
    v, cfg_path = vault
    note = v / "50.054 Compiler" / "Anki - Lectures" / "W01 Intro.md"
    assert run("-c", cfg_path, "sync", "--yes", "--target", "apkg") == 0
    assert note.read_text(encoding="utf-8").count("%%") == 6
    # --legacy touches only the old-style flag
    assert run("-c", cfg_path, "unflag", "--legacy", "--yes") == 0
    text = note.read_text(encoding="utf-8")
    assert "ADDED: already exported" not in text and text.count("%%") == 6
    # without a filter every flagged card is cleared; they are pending again
    assert run("-c", cfg_path, "unflag", "--yes") == 0
    assert "ADDED" not in note.read_text(encoding="utf-8")
    run("-c", cfg_path, "status")
    assert "4" in capsys.readouterr().out


def test_relative_vault_resolves_against_config_file(tmp_path, monkeypatch):
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "vault" / "C" / "Anki - Lectures").mkdir(parents=True)
    (tmp_path / "cfg" / "m2a.toml").write_text('vault = "vault"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)  # a different cwd
    cfg = load_config(tmp_path / "cfg" / "m2a.toml")
    assert cfg.vault == (tmp_path / "cfg" / "vault").resolve()
    assert cfg.target == "anki"


def test_tilde_in_output_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "v" / "C" / "Anki - Lectures").mkdir(parents=True)
    (tmp_path / "m2a.toml").write_text('vault = "v"\noutput_dir = "~/Downloads/M2A"\n', encoding="utf-8")
    cfg = load_config(tmp_path / "m2a.toml")
    assert cfg.output_dir == tmp_path / "Downloads" / "M2A"
