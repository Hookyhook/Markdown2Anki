"""Small terminal styling helpers - no dependencies, colours only on a TTY (and never with NO_COLOR set)."""
from __future__ import annotations

import os
import re
import sys
from typing import Iterable, List, Sequence

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def visible_len(text: str) -> int:
    return len(_ANSI_RE.sub("", text))


def pad(text: str, width: int, right: bool = False) -> str:
    """ljust/rjust that ignores colour codes."""
    fill = " " * max(0, width - visible_len(text))
    return fill + text if right else text + fill


def _enabled() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return sys.stdout.isatty()


def _wrap(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _enabled() else text


def bold(text: str) -> str:
    return _wrap("1", text)


def dim(text: str) -> str:
    return _wrap("2", text)


def red(text: str) -> str:
    return _wrap("31", text)


def green(text: str) -> str:
    return _wrap("32", text)


def yellow(text: str) -> str:
    return _wrap("33", text)


def cyan(text: str) -> str:
    return _wrap("36", text)


def level(name: str) -> str:
    """Coloured, fixed-width diagnostic level."""
    text = f"{name:7}"
    return {"error": red, "warning": yellow, "info": dim}.get(name, str)(text)


def header(text: str) -> str:
    return bold(text)


def kv(pairs: Sequence[tuple]) -> str:
    """'notes 2 · cards 9 · pending 9' with the values emphasised."""
    return dim(" · ").join(f"{dim(str(k))} {bold(str(v))}" for k, v in pairs)


def table(rows: List[Sequence[str]], headers: Sequence[str], align_right: Iterable[int] = ()) -> str:
    """Plain aligned table with an underlined header; ``align_right`` lists column indexes."""
    right = set(align_right)
    cols = len(headers)
    widths = [visible_len(str(h)) for h in headers]
    for row in rows:
        for i in range(cols):
            widths[i] = max(widths[i], visible_len(str(row[i])))

    def fmt(row: Sequence[str], style=lambda s: s) -> str:
        cells = [pad(style(str(row[i])), widths[i], right=i in right) for i in range(cols)]
        return "  ".join(cells).rstrip()

    lines = [fmt(headers, bold), dim("  ".join("─" * w for w in widths))]
    lines.extend(fmt(r) for r in rows)
    return "\n".join(lines)
