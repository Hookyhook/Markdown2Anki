"""Discover notes in the vault: <vault>/<course>/<subdirectory>/*.md"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .config import Config, sanitize_tag
from .parser import Card, Diagnostic, parse_file


@dataclass
class SourceFile:
    path: Path
    course: str  # folder name
    subdirectory: str  # folder name
    base_tag: str  # tag hierarchy above the file

    @property
    def image_dir(self) -> Path:
        return self.path.parent


def discover(cfg: Config, course_filter: Optional[str] = None,
             diagnostics: Optional[List[Diagnostic]] = None) -> List[SourceFile]:
    diagnostics = diagnostics if diagnostics is not None else []
    vault = cfg.vault
    if not vault.is_dir():
        raise FileNotFoundError(f"vault directory not found: {vault}")

    sources: List[SourceFile] = []
    for course_dir in sorted(p for p in vault.iterdir() if p.is_dir()):
        name = course_dir.name
        if name.startswith("."):
            continue
        subject_tag = cfg.subject_tag(name)
        if subject_tag is None:
            if name not in cfg.ignore:
                diagnostics.append(Diagnostic(course_dir, 0, "info", "skipped folder (not in [subjects])"))
            continue
        if course_filter and not _matches(course_filter, name, subject_tag):
            continue

        for sub_dir in sorted(p for p in course_dir.iterdir() if p.is_dir()):
            if sub_dir.name.startswith(".") or sub_dir.name in cfg.ignore:
                continue
            sub_tag = cfg.subdirectories.get(sub_dir.name)
            if sub_tag is None:
                md_count = len(list(sub_dir.rglob("*.md")))
                if md_count:
                    diagnostics.append(Diagnostic(sub_dir, 0, "warning",
                                                  f"skipped {md_count} note(s) under '{sub_dir.name}': not in "
                                                  f"[subdirectories] (notes must be <course>/<subdirectory>/*.md)"))
                continue
            base_tag = "::".join(t for t in [cfg.base_tag, subject_tag, sub_tag] if t)
            for note in sorted(sub_dir.glob("*.md")):
                sources.append(SourceFile(note, name, sub_dir.name, base_tag))

        loose = list(course_dir.glob("*.md"))
        if loose:
            diagnostics.append(Diagnostic(course_dir, 0, "warning",
                                          f"skipped {len(loose)} note(s) directly in the course folder; "
                                          f"notes must be inside a subdirectory such as 'Anki - Lectures'"))
    return sources


def _matches(pattern: str, *candidates: str) -> bool:
    pattern = pattern.lower()
    for candidate in candidates:
        c = candidate.lower()
        if fnmatch.fnmatch(c, pattern) or pattern in c:
            return True
    return False


def parse_sources(sources: List[SourceFile], diagnostics: List[Diagnostic]) -> List[Card]:
    cards: List[Card] = []
    for source in sources:
        cards.extend(parse_file(source.path, source.base_tag, diagnostics))
    return cards
