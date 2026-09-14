"""Write ``ADDED[id]:`` prefixes back into notes after a successful export."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

from .ids import added_prefix, parse_added
from .parser import Card


def write_flags(cards: List[Tuple[Card, str]]) -> Tuple[int, List[str]]:
    """Mark ``cards`` (paired with their new id) as added, grouped per file.

    Each line is checked against the parsed question before it is touched, so a note edited between
    parsing and flagging is reported instead of corrupted. Returns (flagged, problems).
    """
    by_file: Dict[Path, List[Tuple[Card, str]]] = {}
    for card, card_id in cards:
        by_file.setdefault(card.file, []).append((card, card_id))

    flagged = 0
    problems: List[str] = []
    for path, entries in by_file.items():
        text = path.read_text(encoding="utf-8")
        lines = text.split("\n")
        changed = False
        for card, card_id in entries:
            index = card.line - 1
            if index >= len(lines):
                problems.append(f"{card.location}: line no longer exists, not flagged")
                continue
            _, existing_id, question = parse_added(lines[index])
            first_question_line = card.question.split("\n", 1)[0]
            if question != first_question_line:
                problems.append(f"{card.location}: question changed since parsing, not flagged")
                continue
            if existing_id == card_id:
                continue
            lines[index] = added_prefix(card_id) + question
            changed = True
            flagged += 1
        if changed:
            path.write_text("\n".join(lines), encoding="utf-8")
    return flagged, problems
