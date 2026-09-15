from pathlib import Path

from markdown2anki.build import RenderedNote
from markdown2anki.config import Config
from markdown2anki.export import ankiconnect
from markdown2anki.parser import Card


class FakeAnki:
    """Records AnkiConnect calls; answers the few queries the exporter makes."""

    def __init__(self, models):
        self.models = models  # name -> id
        self.calls = []

    def invoke(self, action, **params):
        self.calls.append((action, params))
        if action == "modelNamesAndIds":
            return dict(self.models)
        if action == "addNotes":
            return [1000 + i for i, _ in enumerate(params["notes"])]
        if action == "createModel":
            self.models[params["modelName"]] = 1
        return None


def _card(line, added=False, card_id=None):
    return Card(file=Path("n.md"), line=line, question="q", answer="a", tag="T", added=added, card_id=card_id)


def _export(monkeypatch, fake, cfg, notes):
    monkeypatch.setattr(ankiconnect.AnkiConnect, "invoke", lambda self, action, **p: fake.invoke(action, **p))
    from markdown2anki.build import BuildResult
    return ankiconnect.export_ankiconnect(BuildResult(notes=notes), cfg)


def test_uses_the_imported_note_type_by_id_even_if_name_collides(monkeypatch):
    fake = FakeAnki({"Basic": 1234, "Basic-m2a": ankiconnect.BASIC_MODEL_ID})
    cfg = Config(vault=Path("."), deck="D", anki_basic_model="Basic")
    flags, added, updated = _export(monkeypatch, fake, cfg, [RenderedNote(_card(3), "basic", ["<b>q</b>", "a"], ["T"])])
    add_call = next(p for a, p in fake.calls if a == "addNotes")
    assert add_call["notes"][0]["modelName"] == "Basic-m2a"
    assert not any(a == "createModel" for a, _ in fake.calls)
    assert len(flags[0][1]) == 6 and added == 1 and updated == 0
    assert add_call["notes"][0]["fields"]["Back"] == f"a<!--m2a:{flags[0][1]}-->"


def test_creates_configured_model_when_missing_and_updates_by_note_id(monkeypatch):
    fake = FakeAnki({"Basic": 1234})
    cfg = Config(vault=Path("."), deck="D", anki_basic_model="M2A Basic")
    notes = [RenderedNote(_card(3), "basic", ["q", "a"], ["T"]),
             RenderedNote(_card(9, added=True, card_id="n555"), "basic", ["q2", "a2"], ["T"])]
    flags, added, updated = _export(monkeypatch, fake, cfg, notes)
    assert ("createModel", ) == tuple(a for a, p in fake.calls if a == "createModel")[:1]
    assert next(p for a, p in fake.calls if a == "createModel")["modelName"] == "M2A Basic"
    upd = next(p for a, p in fake.calls if a == "updateNoteFields")
    assert upd["note"]["id"] == 555 and upd["note"]["fields"]["Front"] == "q2"
    assert upd["note"]["fields"]["Back"].startswith("a2<!--m2a:")
    assert added == 1 and updated == 1
    assert len(flags) == 2 and all(len(cid) == 6 for _, cid in flags)  # new card + migrated legacy card


def test_update_finds_note_by_embedded_marker(monkeypatch):
    fake = FakeAnki({"Basic": 1234})
    calls = fake.invoke

    def invoke(action, **params):
        if action == "findNotes":
            fake.calls.append((action, params))
            return [777] if "m2a:abc123-->" in params["query"] else []
        return calls(action, **params)
    fake.invoke = invoke
    cfg = Config(vault=Path("."), deck="D")
    notes = [RenderedNote(_card(3, added=True, card_id="abc123"), "basic", ["q", "a"], ["T"]),
             RenderedNote(_card(9, added=True, card_id="zzz999"), "basic", ["q", "a"], ["T"])]
    diags = []
    monkeypatch.setattr(ankiconnect.AnkiConnect, "invoke", lambda self, action, **p: fake.invoke(action, **p))
    from markdown2anki.build import BuildResult
    flags, added, updated = ankiconnect.export_ankiconnect(BuildResult(notes=notes), cfg, diags)
    assert updated == 1 and added == 0 and flags == []
    assert next(p for a, p in fake.calls if a == "updateNoteFields")["note"]["id"] == 777
    assert len(diags) == 1 and "not found in Anki" in diags[0].message and diags[0].line == 9
