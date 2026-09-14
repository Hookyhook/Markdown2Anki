"""Export rendered notes as an .apkg file via genanki."""
from __future__ import annotations

import hashlib
import shutil
import warnings
from pathlib import Path
from typing import Dict, List, Tuple

import genanki

from ..build import MODEL_CLOZE, BuildResult
from ..config import Config
from ..ids import is_anki_note_id, new_card_id
from ..parser import Diagnostic
from ..NoteTypes.note_types import BasicNoteType, ClozeNoteType, get_basic_model, get_cloze_model
from ..parser import Card


def stable_deck_id(name: str) -> int:
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()
    return (1 << 30) + int(digest[:8], 16) % (1 << 30)


def export_apkg(result: BuildResult, cfg: Config, output_path: Path,
                diagnostics: List[Diagnostic] = None) -> Tuple[List[Tuple[Card, str]], Path]:
    """Write the package. Returns ((card, id) pairs to flag, occlusion directory or None).

    Cards that were pushed through AnkiConnect (``n<id>``) have no GUID an .apkg import could match, so an
    update is impossible here; they are skipped with a warning instead of being imported as duplicates.
    """
    diagnostics = diagnostics if diagnostics is not None else []
    kept = []
    for note in result.notes:
        if note.card.added and is_anki_note_id(note.card.card_id):
            diagnostics.append(Diagnostic(note.card.file, note.card.line, "warning",
                                          "pushed via AnkiConnect earlier; cannot be updated through an .apkg "
                                          "(use `--target anki --update`), skipped"))
            continue
        kept.append(note)
    result.notes = kept
    basic_model = get_basic_model(cfg.display)
    cloze_model = get_cloze_model(cfg.display)
    deck = genanki.Deck(stable_deck_id(cfg.deck), cfg.deck)

    flags: List[Tuple[Card, str]] = []
    media: List[str] = []
    for note in result.notes:
        card_id = note.card.card_id or new_card_id()
        cls = ClozeNoteType if note.model == MODEL_CLOZE else BasicNoteType
        model = cloze_model if note.model == MODEL_CLOZE else basic_model
        deck.add_note(cls(model=model, fields=note.fields, tags=note.tags, card_id=card_id))
        for path in note.media:
            if str(path) not in media:
                media.append(str(path))
        flags.append((note.card, card_id))

    package = genanki.Package(deck)
    package.media_files = media
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", module="genanki", message="^Field contained the following invalid HTML tags")
        package.write_to_file(str(output_path))

    occlusion_dir = None
    if result.occlusions:
        occlusion_dir = output_path.parent / "occlusions"
        occlusion_dir.mkdir(parents=True, exist_ok=True)
        for occ in result.occlusions:
            card_id = occ.card.card_id or new_card_id()
            target_dir = occlusion_dir / occ.tag.replace("::", "__")
            target_dir.mkdir(parents=True, exist_ok=True)
            for image in occ.images:
                shutil.copy2(image, target_dir / image.name)
            flags.append((occ.card, card_id))
    return flags, occlusion_dir
