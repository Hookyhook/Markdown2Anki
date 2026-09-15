"""Push rendered notes straight into a running Anki via the AnkiConnect add-on (https://foosoft.net/projects/anki-connect/).

Notes are added to the note types named in the config (``anki_basic_model`` / ``anki_cloze_model``), created
from the templates only if they do not exist yet. The Anki note id is stored in the markdown as ``ADDED[n<id>]:`` so later runs can update.
"""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Tuple

from ..build import MODEL_CLOZE, BuildResult, RenderedNote
from ..config import Config
from ..ids import anki_note_id, is_anki_note_id, new_card_id, search_query, with_marker
from ..parser import Diagnostic
from ..NoteTypes.note_types import BASIC_MODEL_ID, CLOZE_MODEL_ID, templates
from ..parser import Card



class AnkiConnectError(RuntimeError):
    pass


class AnkiConnect:
    def __init__(self, url: str) -> None:
        self.url = url

    def invoke(self, action: str, **params: Any) -> Any:
        payload = json.dumps({"action": action, "version": 6, "params": params}).encode("utf-8")
        request = urllib.request.Request(self.url, payload, {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.load(response)
        except urllib.error.URLError as exc:
            raise AnkiConnectError(f"cannot reach AnkiConnect at {self.url} - is Anki running with the add-on? "
                                   f"({exc.reason})") from exc
        if body.get("error"):
            raise AnkiConnectError(f"{action}: {body['error']}")
        return body.get("result")

    def resolve_models(self, cfg: Config, need_cloze: bool) -> Tuple[str, str]:
        """Return (basic, cloze) note type names to use.

        The note types that earlier .apkg imports created are found by their ids, so the same styling
        keeps being used even if a stock note type shares the name. Otherwise the configured names are
        used and created if missing. Existing note types are never modified.
        """
        names_and_ids: Dict[str, int] = self.invoke("modelNamesAndIds")
        by_id = {int(model_id): name for name, model_id in names_and_ids.items()}

        basic = by_id.get(BASIC_MODEL_ID, cfg.anki_basic_model)
        if basic not in names_and_ids:
            t = templates("Basic", cfg.display)
            self.invoke("createModel", modelName=basic, inOrderFields=["Front", "Back"], css=t["css"],
                        cardTemplates=[{"Name": "Card 1", "Front": t["qfmt"], "Back": t["afmt"]}])

        cloze = by_id.get(CLOZE_MODEL_ID, cfg.anki_cloze_model)
        if need_cloze and cloze not in names_and_ids:
            t = templates("Cloze", cfg.display)
            self.invoke("createModel", modelName=cloze, inOrderFields=["Text", "Back Extra"], css=t["css"],
                        isCloze=True, cardTemplates=[{"Name": "Cloze", "Front": t["qfmt"], "Back": t["afmt"]}])
        return basic, cloze

    def ensure_deck(self, name: str) -> None:
        self.invoke("createDeck", deck=name)

    def store_media(self, notes: List[RenderedNote]) -> None:
        seen = set()
        for note in notes:
            for path in note.media:
                if path in seen:
                    continue
                seen.add(path)
                data = base64.b64encode(path.read_bytes()).decode("ascii")
                self.invoke("storeMediaFile", filename=path.name, data=data)


def template_diff(cfg: Config) -> List[Dict[str, Any]]:
    """Compare the local templates with the note types in Anki. Returns one entry per note type that exists:
    {name, kind, changed: [what differs], local: {...}, remote: {...}}."""
    client = AnkiConnect(cfg.anki_connect_url)
    names_and_ids: Dict[str, int] = client.invoke("modelNamesAndIds")
    by_id = {int(v): k for k, v in names_and_ids.items()}
    out = []
    for kind, model_id, configured, card_name in (("Basic", BASIC_MODEL_ID, cfg.anki_basic_model, "Card 1"),
                                                  ("Cloze", CLOZE_MODEL_ID, cfg.anki_cloze_model, "Cloze")):
        name = by_id.get(model_id, configured)
        if name not in names_and_ids:
            continue
        local = templates(kind, cfg.display)
        remote_templates = client.invoke("modelTemplates", modelName=name)
        remote_css = client.invoke("modelStyling", modelName=name)["css"]
        remote_card = next(iter(remote_templates.values()))
        remote_card_name = next(iter(remote_templates.keys()))
        changed = []
        if remote_card.get("Front", "").strip() != local["qfmt"].strip():
            changed.append("front")
        if remote_card.get("Back", "").strip() != local["afmt"].strip():
            changed.append("back")
        if remote_css.strip() != local["css"].strip():
            changed.append("styling")
        out.append({"name": name, "kind": kind, "card": remote_card_name or card_name, "changed": changed,
                    "local": local, "client": client})
    return out


def push_templates(entry: Dict[str, Any]) -> None:
    """Overwrite one note type's card template and styling in Anki with the local version."""
    client: AnkiConnect = entry["client"]
    local = entry["local"]
    client.invoke("updateModelTemplates",
                  model={"name": entry["name"], "templates": {entry["card"]: {"Front": local["qfmt"],
                                                                              "Back": local["afmt"]}}})
    client.invoke("updateModelStyling", model={"name": entry["name"], "css": local["css"]})


def _fields(note: RenderedNote, card_id: str) -> Dict[str, str]:
    back = with_marker(note.fields[1], card_id)
    if note.model == MODEL_CLOZE:
        return {"Text": note.fields[0], "Back Extra": back}
    return {"Front": note.fields[0], "Back": back}


def _note_payload(note: RenderedNote, card_id: str, deck: str, basic_model: str, cloze_model: str) -> Dict[str, Any]:
    model = cloze_model if note.model == MODEL_CLOZE else basic_model
    return {"deckName": deck, "modelName": model, "fields": _fields(note, card_id), "tags": note.tags,
            "options": {"allowDuplicate": True}}


def _back_field(note: RenderedNote) -> str:
    return "Back Extra" if note.model == MODEL_CLOZE else "Back"


def export_ankiconnect(result: BuildResult, cfg: Config,
                       diagnostics: List[Diagnostic] = None) -> Tuple[List[Tuple[Card, str]], int, int]:
    """Add new notes; update already-exported ones in place. Returns (flags, added, updated).

    An exported card is found again either by the ``<!--m2a:id-->`` marker embedded in its back field
    (cards exported by this version, through either target) or, for cards flagged by the previous
    version, by the Anki note id stored as ``n<id>``. A card that cannot be found is skipped with a warning.
    """
    diagnostics = diagnostics if diagnostics is not None else []
    client = AnkiConnect(cfg.anki_connect_url)
    basic_model, cloze_model = client.resolve_models(cfg, need_cloze=any(n.model == MODEL_CLOZE
                                                                          for n in result.notes))
    client.ensure_deck(cfg.deck)
    client.store_media(result.notes)

    flags: List[Tuple[Card, str]] = []
    updated = 0
    to_add: List[Tuple[RenderedNote, str]] = []
    for note in result.notes:
        card_id = note.card.card_id
        if not note.card.added or not card_id:
            to_add.append((note, new_card_id()))
            continue
        if is_anki_note_id(card_id):
            # Flagged by the previous version with Anki's note id: update by id and migrate the card to a
            # short id (embedded now, re-flagged below) so it works like every other card from here on.
            note_ids = [anki_note_id(card_id)]
            card_id = new_card_id()
        else:
            note_ids = client.invoke("findNotes", query=search_query(_back_field(note), card_id)) or []
        if not note_ids:
            diagnostics.append(Diagnostic(note.card.file, note.card.line, "warning",
                                          "not found in Anki (deleted, other profile, or exported before ids "
                                          "were embedded) - `m2a unflag --file ...` to add it again; skipped"))
            continue
        client.invoke("updateNoteFields", note={"id": note_ids[0], "fields": _fields(note, card_id)})
        client.invoke("addTags", notes=note_ids[:1], tags=" ".join(note.tags))
        if card_id != note.card.card_id:
            flags.append((note.card, card_id))
        updated += 1

    added = 0
    if to_add:
        ids = client.invoke("addNotes", notes=[_note_payload(n, cid, cfg.deck, basic_model, cloze_model)
                                               for n, cid in to_add])
        for (note, card_id), note_id in zip(to_add, ids):
            if note_id is None:
                continue
            flags.append((note.card, card_id))
            added += 1
    return flags, added, updated
