"""Turn parsed cards into rendered notes ready for an exporter."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from .constants import CLOZE_TAG, CODE_KEYWORDS, CODE_TAG
from .parser import KIND_CLOZE, KIND_IMAGE_OCCLUSION, Card, Diagnostic
from .render import render_markdown, strip_keyword_lines

IMAGE_RE = re.compile(r"!\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")

MODEL_BASIC = "basic"
MODEL_CLOZE = "cloze"


@dataclass
class RenderedNote:
    card: Card
    model: str
    fields: List[str]
    tags: List[str]
    media: List[Path] = field(default_factory=list)


@dataclass
class ImageOcclusion:
    card: Card
    images: List[Path]
    tag: str


@dataclass
class BuildResult:
    notes: List[RenderedNote] = field(default_factory=list)
    occlusions: List[ImageOcclusion] = field(default_factory=list)
    skipped: List[Card] = field(default_factory=list)


def _images(text: str, image_dir: Path, card: Card, diagnostics: List[Diagnostic]) -> Tuple[str, List[Path], bool]:
    """Replace ``![[name.png]]`` with <img> tags; return (text, media paths, all_found)."""
    media: List[Path] = []
    ok = True

    def repl(match: "re.Match[str]") -> str:
        nonlocal ok
        name = match.group(1).strip()
        path = image_dir / name
        if not path.is_file():
            ok = False
            diagnostics.append(Diagnostic(card.file, card.line, "error",
                                          f"image not found next to the note: {name}"))
        elif path not in media:
            media.append(path)
        return f'<img src="{name}">'

    return IMAGE_RE.sub(repl, text), media, ok


def _check_html(note: RenderedNote, diagnostics: List[Diagnostic]) -> None:
    """Flag text that a browser would swallow as a tag, e.g. ``<actual_type>`` written outside backticks."""
    import genanki

    for field_text in note.fields:
        bad = genanki.Note._find_invalid_html_tags_in_field(field_text)
        if bad:
            diagnostics.append(Diagnostic(note.card.file, note.card.line, "warning",
                                          "looks like an HTML tag and will not display: " + ", ".join(bad[:3])
                                          + " - wrap it in backticks or escape it"))
            return


def build(cards: List[Card], diagnostics: List[Diagnostic], cloze_notes: bool = False) -> BuildResult:
    """``cloze_notes``: export 'Cloze' cards with {{c1::}} markers as real cloze notes (default: legacy basic note)."""
    result = BuildResult()
    for card in cards:
        image_dir = card.file.parent
        tags = [card.tag] if card.tag else []

        if card.kind == KIND_IMAGE_OCCLUSION:
            names = IMAGE_RE.findall(card.answer)
            paths = [image_dir / n.strip() for n in names]
            missing = [p for p in paths if not p.is_file()]
            for p in missing:
                diagnostics.append(Diagnostic(card.file, card.line, "error", f"image not found: {p.name}"))
            if missing or not paths:
                result.skipped.append(card)
                continue
            result.occlusions.append(ImageOcclusion(card, paths, card.tag))
            continue

        question, answer = card.question, card.answer
        if card.has_code:
            tags.append(CODE_TAG)
            question = strip_keyword_lines(question, CODE_KEYWORDS)
            answer = strip_keyword_lines(answer, CODE_KEYWORDS)

        if card.kind == KIND_CLOZE:
            text, media, ok = _images(answer, image_dir, card, diagnostics)
            if not ok:
                result.skipped.append(card)
                continue
            rendered = render_markdown(text)
            if cloze_notes and card.has_cloze_markers:
                result.notes.append(RenderedNote(card, MODEL_CLOZE, [rendered, ""], tags, media))
            else:
                # Legacy behaviour: export as a basic note and let the user add the deletions in Anki.
                tags.append(CLOZE_TAG)
                result.notes.append(RenderedNote(card, MODEL_BASIC, [rendered, ""], tags, media))
            _check_html(result.notes[-1], diagnostics)
            continue

        q_text, q_media, q_ok = _images(question, image_dir, card, diagnostics)
        a_text, a_media, a_ok = _images(answer, image_dir, card, diagnostics)
        if not (q_ok and a_ok):
            result.skipped.append(card)
            continue
        media = q_media + [m for m in a_media if m not in q_media]
        result.notes.append(RenderedNote(card, MODEL_BASIC, [render_markdown(q_text), render_markdown(a_text)],
                                         tags, media))
        _check_html(result.notes[-1], diagnostics)
    return result
