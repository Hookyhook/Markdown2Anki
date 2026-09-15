"""Configuration for the m2a CLI: a small TOML file (``m2a.toml``) next to the vault or repo.

Legacy ``.env`` files are still understood so existing setups keep working; ``m2a init`` migrates them.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

try:  # Python 3.11+
    import tomllib  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib  # type: ignore

CONFIG_FILE_NAME = "m2a.toml"

DEFAULT_SUBDIRECTORIES = {"Anki - Lectures": "Lectures", "Anki - Exercises": "Exercises"}
DEFAULT_IGNORE = [".git", ".obsidian", "Archive", "templates"]


@dataclass
class Config:
    vault: Path
    package_name: str = "Anki"
    base_tag: str = ""
    deck: str = ""
    output_dir: Path = Path(".")
    subjects: Dict[str, str] = field(default_factory=dict)  # folder name -> tag; empty = every folder
    subdirectories: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SUBDIRECTORIES))
    ignore: List[str] = field(default_factory=lambda: list(DEFAULT_IGNORE))
    display: Dict[str, str] = field(default_factory=dict)  # tag -> title shown on the card
    target: str = "apkg"  # default export target for `m2a sync`: "apkg" or "anki"
    anki_connect_url: str = "http://127.0.0.1:8765"
    anki_basic_model: str = "M2A Basic"  # note type names used by --target anki
    anki_cloze_model: str = "M2A Cloze"
    cloze_notes: bool = False  # True: 'Cloze' cards with {{c1::}} markers become real cloze notes
    source: Optional[Path] = None  # where the config was loaded from

    def __post_init__(self) -> None:
        self.vault = Path(self.vault).expanduser()
        self.output_dir = Path(self.output_dir).expanduser()
        if not self.deck:
            self.deck = self.package_name

    def subject_tag(self, folder_name: str) -> Optional[str]:
        """Tag for a top-level vault folder, or None if the folder is not a subject."""
        if folder_name in self.ignore:
            return None
        if self.subjects:
            return self.subjects.get(folder_name)
        return sanitize_tag(folder_name)


def sanitize_tag(name: str) -> str:
    """Make a folder or heading name usable as (part of) an Anki tag."""
    tag = name.strip().replace(". ", "_").replace(" ", "_")
    tag = re.sub(r"_+", "_", tag)
    return tag


def user_config_path() -> Path:
    """Global per-user location: $XDG_CONFIG_HOME/m2a/m2a.toml (default ~/.config/m2a/m2a.toml)."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "m2a" / CONFIG_FILE_NAME


def find_config(start: Optional[Path] = None) -> Optional[Path]:
    """Walk up from ``start`` (default: cwd) looking for m2a.toml, then fall back to the user config."""
    current = Path(start or os.getcwd()).resolve()
    for candidate in [current, *current.parents]:
        path = candidate / CONFIG_FILE_NAME
        if path.is_file():
            return path
    user = user_config_path()
    return user if user.is_file() else None


def load_config(path: Optional[Path] = None) -> Config:
    """Load m2a.toml (searching upwards if no path is given). Falls back to a legacy .env."""
    if path is None:
        path = find_config()
    if path is None:
        env = Path(".env")
        if env.is_file():
            return config_from_env(env)
        raise FileNotFoundError(f"no {CONFIG_FILE_NAME} found here, above, or at {user_config_path()} "
                                f"- run `m2a init --vault <path>`")

    with open(path, "rb") as f:
        data = tomllib.load(f)

    vault = data.get("vault")
    if not vault:
        raise ValueError(f"{path}: 'vault' is required")

    base = path.parent
    output_dir = Path(data.get("output_dir", "."))
    if not output_dir.is_absolute():
        output_dir = base / output_dir

    cfg = Config(
        vault=Path(vault),
        package_name=data.get("package_name", "Anki"),
        base_tag=data.get("base_tag", ""),
        deck=data.get("deck", ""),
        output_dir=output_dir,
        subjects=dict(data.get("subjects", {})),
        subdirectories=dict(data.get("subdirectories", DEFAULT_SUBDIRECTORIES)),
        ignore=list(data.get("ignore", DEFAULT_IGNORE)),
        display=dict(data.get("display", {})),
        target=data.get("target", "apkg"),
        anki_connect_url=data.get("anki_connect_url", "http://127.0.0.1:8765"),
        anki_basic_model=data.get("anki_basic_model", "M2A Basic"),
        anki_cloze_model=data.get("anki_cloze_model", "M2A Cloze"),
        cloze_notes=bool(data.get("cloze_notes", False)),
        source=path,
    )
    return cfg


def config_from_env(path: Path) -> Config:
    """Build a Config from the legacy .env format (KEY=VALUE with JSON blobs)."""
    values: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()

    def as_json(key: str, default):
        raw = values.get(key)
        if not raw:
            return default
        return json.loads(raw)

    subdirs = as_json("SUB_DIRECTORY_TAG_DICTIONARY", DEFAULT_SUBDIRECTORIES)
    ignore = as_json("IGNORE_DIRECTORIES", DEFAULT_IGNORE)
    # The legacy script checked IGNORE before the subdirectory map, silently dropping cards.
    ignore = [d for d in ignore if d not in subdirs and d not in subdirs.values()]

    return Config(
        vault=Path(values.get("OBSIDIAN_VAULT_DIRECTORY", ".")),
        package_name=values.get("PACKAGE_NAME", "Anki"),
        base_tag=values.get("BASE_TAG", ""),
        subjects=as_json("SUBJECT_TAG_DICTIONARY", {}),
        subdirectories=subdirs,
        ignore=ignore,
        source=path,
    )


def render_toml(cfg: Config) -> str:
    """Serialise a Config to m2a.toml text (no TOML writer needed for this flat shape)."""

    def quote(value: str) -> str:
        return json.dumps(value, ensure_ascii=False)

    def table(name: str, mapping: Dict[str, str], comment: str) -> str:
        lines = [f"# {comment}", f"[{name}]"]
        for key, value in mapping.items():
            lines.append(f"{quote(key)} = {quote(value)}")
        return "\n".join(lines)

    out = [
        "# Markdown2Anki configuration (m2a). Paths may use ~.",
        f"vault = {quote(str(cfg.vault))}",
        f"package_name = {quote(cfg.package_name)}",
        f"# Anki deck name; use :: for subdecks. Defaults to package_name.",
        f"deck = {quote(cfg.deck)}",
        f"# Top-level tag prepended to every card (may be empty).",
        f"base_tag = {quote(cfg.base_tag)}",
        f"# Where the .apkg and image-occlusion exports are written (relative to this file).",
        f"output_dir = {quote(str(cfg.output_dir))}",
        "# Default target for `m2a sync`: \"apkg\" writes a package file, \"anki\" pushes via AnkiConnect.",
        f"target = {quote(cfg.target)}",
        f"anki_connect_url = {quote(cfg.anki_connect_url)}",
        "# Note type names used with `sync --target anki` (created on first use if missing).",
        "# Set them to your existing note types to keep your own card styling.",
        f"anki_basic_model = {quote(cfg.anki_basic_model)}",
        f"anki_cloze_model = {quote(cfg.anki_cloze_model)}",
        "# false: 'Cloze' cards are exported as basic notes tagged TODO_PROCESS_CLOZES (legacy behaviour).",
        "# true: a 'Cloze' card whose answer contains {{c1::...}} becomes a real cloze note.",
        f"cloze_notes = {'true' if cfg.cloze_notes else 'false'}",
        "",
        "# Top-level vault folders that are NOT courses.",
        "ignore = " + json.dumps(cfg.ignore, ensure_ascii=False),
        "",
        table("subjects", cfg.subjects,
              "Course folder -> tag. Leave the table empty to export every non-ignored folder, tag = folder name."),
        "",
        table("subdirectories", cfg.subdirectories,
              "Folder inside a course -> tag. Notes in any other subfolder are reported as skipped."),
        "",
        table("display", cfg.display,
              "Tag -> title shown in the corner of the card. First match wins, so list specific tags first."),
        "",
    ]
    return "\n".join(out)
