"""Parse a markdown note into cards.

Format (see README): cards are separated by a line of ``---``; the first line after it is the question
(``EQL: `` lines continue it), everything else is the answer. Headings become tags. A question that is
exactly ``Cloze`` makes a cloze card, ``Image Cloze`` an image-occlusion export.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from .constants import CODE_KEYWORDS
from .ids import parse_added
from .helpers.tag_handler import handle_tags, merge_tags

HEADING_RE = re.compile(r"^(#+)\s+(.*)$")
CLOZE_MARKER_RE = re.compile(r"\{\{c\d+::")
FENCE_RE = re.compile(r"^\s*```")

KIND_BASIC = "basic"
KIND_CLOZE = "cloze"
KIND_IMAGE_OCCLUSION = "image_occlusion"


@dataclass
class Diagnostic:
    file: Path
    line: int  # 1-based
    level: str  # "error" | "warning" | "info"
    message: str

    def __str__(self) -> str:
        return f"{self.level.upper():7} {self.file}:{self.line}: {self.message}"


@dataclass
class Card:
    file: Path
    line: int  # 1-based line number of the question
    question: str  # raw markdown; EQL lines joined with "\n"
    answer: str  # raw markdown
    tag: str  # merged hierarchical tag, e.g. SUTD::50.054_Compiler::Lectures::W01_Intro::Parsing
    kind: str = KIND_BASIC
    added: bool = False
    card_id: Optional[str] = None
    has_code: bool = False
    has_cloze_markers: bool = False
    extra_tags: List[str] = field(default_factory=list)

    @property
    def pending(self) -> bool:
        return not self.added

    @property
    def updatable(self) -> bool:
        """Already exported with an id, so it can be pushed again as an update."""
        return self.added and self.card_id is not None

    @property
    def location(self) -> str:
        return f"{self.file}:{self.line}"


def parse_lines(lines: List[str], file: Path, base_tag: str, file_tag: Optional[str] = None,
                diagnostics: Optional[List[Diagnostic]] = None) -> List[Card]:
    """Parse the lines of one note. ``base_tag`` is the tag hierarchy above the file (may be empty)."""
    diagnostics = diagnostics if diagnostics is not None else []
    if file_tag is None:
        file_tag = file.stem
    tags: List[str] = [t for t in [base_tag, file_tag] if t]
    fixed_levels = len(tags)  # tags that headings must never pop

    cards: List[Card] = []
    expecting_question = False
    in_code_block = False
    question_line = 0
    question: Optional[str] = None
    added = False
    card_id: Optional[str] = None
    answer_lines: List[str] = []
    orphan_answer: List[Tuple[int, str]] = []  # (line number, text) outside any card

    def flush() -> None:
        nonlocal question, answer_lines, orphan_answer, added, card_id
        if question is not None:
            cards.append(_make_card(file, question_line, question, "\n".join(answer_lines), merge_tags(tags),
                                    added, card_id, diagnostics))
        elif any(text.strip() for _, text in orphan_answer):
            first_line = next(number for number, text in orphan_answer if text.strip())
            diagnostics.append(Diagnostic(file, first_line, "error",
                                          "text outside a card (no question line after '---')"))
        question, answer_lines, orphan_answer, added, card_id = None, [], [], False, None

    for index, line in enumerate(lines, start=1):
        if FENCE_RE.match(line):
            in_code_block = not in_code_block

        heading = HEADING_RE.match(line) if not in_code_block else None
        if heading:
            flush()
            expecting_question = False
            level, text = len(heading.group(1)), heading.group(2).strip()
            tags = handle_tags_by_level(level, text, tags, fixed_levels)
        elif line.startswith("---") and not in_code_block:
            flush()
            expecting_question = True
            question_line = index + 1
        elif expecting_question:
            expecting_question = False
            if not line.strip():
                # blank line right after --- : an empty template slot, not a card. Anything that
                # follows before the next separator is an answer without a question.
                question = None
                orphan_answer.append((index, line))
                continue
            added, card_id, text = parse_added(line)
            question = text
            question_line = index
        elif line.startswith("EQL: ") and question is not None:
            question += "\n" + line[5:]
        elif question is not None:
            answer_lines.append(line)
        else:
            orphan_answer.append((index, line))

    flush()
    return cards


def handle_tags_by_level(level: int, text: str, tags: List[str], fixed_levels: int) -> List[str]:
    """Heading of ``level`` (# = 1) replaces every heading tag at that depth or deeper."""
    keep = fixed_levels + level - 1
    tags = tags[:keep] if len(tags) > keep else list(tags)
    tags.append(text)
    return tags


def _make_card(file: Path, line: int, question: str, answer: str, tag: str, added: bool,
               card_id: Optional[str], diagnostics: List[Diagnostic]) -> Card:
    answer = _strip_trailing_blank_lines(answer)
    key = question.strip().lower()
    kind = KIND_BASIC
    if key in ("cloze",):
        kind = KIND_CLOZE
    elif key in ("image cloze", "cloze image"):
        kind = KIND_IMAGE_OCCLUSION

    has_code = any(kw in question or kw in answer for kw in CODE_KEYWORDS)
    has_markers = bool(CLOZE_MARKER_RE.search(answer))

    if kind == KIND_BASIC and has_markers:
        diagnostics.append(Diagnostic(file, line, "warning",
                                      "cloze markers {{c1::...}} in a basic card; use 'Cloze' as the question"))
    if kind == KIND_IMAGE_OCCLUSION and "![[" not in answer:
        diagnostics.append(Diagnostic(file, line, "error", "image cloze without an image"))
    if kind == KIND_BASIC and not answer.strip():
        diagnostics.append(Diagnostic(file, line, "warning", "card has an empty answer"))

    return Card(file=file, line=line, question=question, answer=answer, tag=tag, kind=kind, added=added,
                card_id=card_id, has_code=has_code, has_cloze_markers=has_markers)


def _strip_trailing_blank_lines(text: str) -> str:
    lines = text.split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def parse_file(path: Path, base_tag: str, diagnostics: Optional[List[Diagnostic]] = None) -> List[Card]:
    text = path.read_text(encoding="utf-8")
    return parse_lines(text.split("\n"), path, base_tag, diagnostics=diagnostics)
