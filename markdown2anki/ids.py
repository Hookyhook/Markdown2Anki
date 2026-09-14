"""Card identity: the ``ADDED[id]:`` prefix that marks an exported card and lets it be updated later.

Two prefixes exist in notes:

* ``ADDED: question``        legacy - exported by an older version, no id, can only be skipped
* ``ADDED[7f3a9c2e]: question`` exported via .apkg; the Anki GUID is derived from the id
* ``ADDED[n1694687123456]: question`` exported via AnkiConnect; the id is Anki's note id
"""
from __future__ import annotations

import re
import secrets
from typing import Optional, Tuple

ADDED_PREFIX_RE = re.compile(r"^ADDED(?:\[(?P<id>[0-9a-f]{8}|n\d+)\])?: ")


def parse_added(line: str) -> Tuple[bool, Optional[str], str]:
    """Return (is_added, card_id, question_text_without_prefix)."""
    match = ADDED_PREFIX_RE.match(line)
    if not match:
        return False, None, line
    return True, match.group("id"), line[match.end():]


def new_card_id() -> str:
    return secrets.token_hex(4)


def added_prefix(card_id: str) -> str:
    return f"ADDED[{card_id}]: "


def is_anki_note_id(card_id: Optional[str]) -> bool:
    return bool(card_id) and card_id.startswith("n")


def anki_note_id(card_id: str) -> int:
    return int(card_id[1:])
