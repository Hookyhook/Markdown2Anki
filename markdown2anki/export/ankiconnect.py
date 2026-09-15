"""Push rendered notes straight into a running Anki via the AnkiConnect add-on (https://foosoft.net/projects/anki-connect/).

Notes are added with the "M2A Basic" / "M2A Cloze" note types, created on first use from the bundled
templates. The Anki note id is stored in the markdown as ``ADDED[n<id>]:`` so later runs can update.
"""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Tuple

from ..build import MODEL_CLOZE, BuildResult, RenderedNote
from ..config import Config
from ..ids import anki_note_id, is_anki_note_id
from ..NoteTypes.note_types import templates
from ..parser import Card

BASIC_MODEL = "M2A Basic"
CLOZE_MODEL = "M2A Cloze"


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

    def ensure_models(self, cfg: Config) -> None:
        existing = set(self.invoke("modelNames"))
        if BASIC_MODEL not in existing:
            t = templates("Basic", cfg.display)
            self.invoke("createModel", modelName=BASIC_MODEL, inOrderFields=["Front", "Back"], css=t["css"],
                        cardTemplates=[{"Name": "Card 1", "Front": t["qfmt"], "Back": t["afmt"]}])
        if CLOZE_MODEL not in existing:
            t = templates("Cloze", cfg.display)
            self.invoke("createModel", modelName=CLOZE_MODEL, inOrderFields=["Text", "Back Extra"], css=t["css"],
                        isCloze=True, cardTemplates=[{"Name": "Cloze", "Front": t["qfmt"], "Back": t["afmt"]}])

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


def _note_payload(note: RenderedNote, deck: str) -> Dict[str, Any]:
    if note.model == MODEL_CLOZE:
        return {"deckName": deck, "modelName": CLOZE_MODEL,
                "fields": {"Text": note.fields[0], "Back Extra": note.fields[1]}, "tags": note.tags,
                "options": {"allowDuplicate": True}}
    return {"deckName": deck, "modelName": BASIC_MODEL,
            "fields": {"Front": note.fields[0], "Back": note.fields[1]}, "tags": note.tags,
            "options": {"allowDuplicate": True}}


def export_ankiconnect(result: BuildResult, cfg: Config) -> Tuple[List[Tuple[Card, str]], int, int]:
    """Add new notes and update notes that already carry an Anki note id. Returns (flags, added, updated)."""
    client = AnkiConnect(cfg.anki_connect_url)
    client.ensure_models(cfg)
    client.ensure_deck(cfg.deck)
    client.store_media(result.notes)

    to_add: List[RenderedNote] = []
    to_update: List[RenderedNote] = []
    for note in result.notes:
        if is_anki_note_id(note.card.card_id):
            to_update.append(note)
        else:
            to_add.append(note)

    flags: List[Tuple[Card, str]] = []
    updated = 0
    for note in to_update:
        note_id = anki_note_id(note.card.card_id)  # type: ignore[arg-type]
        payload = _note_payload(note, cfg.deck)
        client.invoke("updateNoteFields", note={"id": note_id, "fields": payload["fields"]})
        client.invoke("addTags", notes=[note_id], tags=" ".join(note.tags))
        updated += 1

    added = 0
    if to_add:
        ids = client.invoke("addNotes", notes=[_note_payload(n, cfg.deck) for n in to_add])
        for note, note_id in zip(to_add, ids):
            if note_id is None:
                continue
            flags.append((note.card, f"n{note_id}"))
            added += 1
    return flags, added, updated
