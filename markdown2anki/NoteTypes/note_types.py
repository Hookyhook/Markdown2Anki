"""Anki note types (models). Template HTML lives next to this file; the subject label script is injected."""
from __future__ import annotations

import json
import os
from typing import Dict, Optional

import genanki

BASIC_MODEL_ID = 1633854805146
CLOZE_MODEL_ID = 1633854805150
BASIC_MODEL_NAME = "Basic"
CLOZE_MODEL_NAME = "Basic (Cloze)"

# Legacy subject titles from the original hard-coded template; config [display] entries take precedence.
DEFAULT_DISPLAY: Dict[str, str] = {
    "IN0019_NumProg": "Numerisches Programmieren",
    "IN0018_DWT": "Diskrete Wahrscheinlichkeitstheorie",
    "IN0010_GRVS": "Grundlagen Rechnernetze und Verteilte Systeme",
    "MA0902_Analysis": "Analysis",
    "IN0042_ITSec": "IT-Sicherheit",
    "IN0009_GBS": "Grundlagen Betriebssysteme",
    "IN0008_GDB": "Grundlagen Datenbanken",
    "IN0011_Theo": "Einführung in die Theoretische Informatik",
    "IN0006_EIST": "Einführung in die Softwaretechnik",
    "IN0007_GAD": "Algorithmen und Datenstrukturen",
    "IN0003_FPV": "Funktionale Programmierung",
    "IN0002_PGdP": "PGdP",
    "IN0005_GRA": "GRA",
    "MA0901_LinAlg": "Lineare Algebra",
    "IN0015_DS": "Diskrete Strukturen",
    "IN0004_ERA": "Einführung in die Rechnerarchitektur",
    "IN0001_EIDI": "Einführung in die Informatik",
    "IN0000_Mathematics_Preparatory_Course": "Vorkurs Mathematik",
    "01_University": "Uni (NICHT Klassifiziert)",
}

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class BasicNoteType(genanki.Note):
    """Basic note whose GUID is derived from the card id when one exists, else from its content."""

    def __init__(self, *args, card_id: Optional[str] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.card_id = card_id

    @property
    def guid(self):
        if self.card_id:
            return genanki.guid_for("m2a", self.card_id)
        return genanki.guid_for(self.fields[0], self.fields[1])


class ClozeNoteType(BasicNoteType):
    @property
    def guid(self):
        if self.card_id:
            return genanki.guid_for("m2a", self.card_id)
        return genanki.guid_for(self.fields[0])


def _read(*parts: str) -> str:
    """Read a template file; a personal (git-ignored) copy wins over the bundled ``.sample`` version."""
    path = os.path.join(_BASE_DIR, *parts)
    if not os.path.isfile(path):
        stem, ext = os.path.splitext(path)
        path = f"{stem}.sample{ext}"
    with open(path, encoding="utf-8") as f:
        return f.read()


def subject_script(display: Optional[Dict[str, str]] = None) -> str:
    merged: Dict[str, str] = dict(display or {})
    for key, value in DEFAULT_DISPLAY.items():
        merged.setdefault(key, value)
    return _read("subject_script.html").replace("__M2A_SUBJECTS__", json.dumps(merged, ensure_ascii=False))


def templates(kind: str, display: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Return {"qfmt", "afmt", "css"} for "Basic" or "Cloze" with the subject script injected."""
    script = subject_script(display)
    return {
        "qfmt": _read(kind, "front.html").replace("__M2A_SUBJECT_SCRIPT__", script),
        "afmt": _read(kind, "back.html").replace("__M2A_SUBJECT_SCRIPT__", script),
        "css": _read(kind, "styling.css"),
    }


def get_basic_model(display: Optional[Dict[str, str]] = None) -> genanki.Model:
    t = templates("Basic", display)
    return genanki.Model(
        BASIC_MODEL_ID, BASIC_MODEL_NAME,
        fields=[{"name": "Front", "font": "Arial"}, {"name": "Back", "font": "Arial"}],
        templates=[{"name": "Card 1", "qfmt": t["qfmt"], "afmt": t["afmt"]}],
        css=t["css"],
    )


def get_cloze_model(display: Optional[Dict[str, str]] = None) -> genanki.Model:
    t = templates("Cloze", display)
    return genanki.Model(
        CLOZE_MODEL_ID, CLOZE_MODEL_NAME,
        model_type=genanki.Model.CLOZE,
        fields=[{"name": "Text", "font": "Arial"}, {"name": "Back Extra", "font": "Arial"}],
        templates=[{"name": "Cloze", "qfmt": t["qfmt"], "afmt": t["afmt"]}],
        css=t["css"],
    )
