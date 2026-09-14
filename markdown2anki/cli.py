"""m2a - command line interface for Markdown2Anki."""
from __future__ import annotations

import argparse
import sys
from collections import OrderedDict
from pathlib import Path
from typing import List, Optional

from .build import build
from .config import CONFIG_FILE_NAME, Config, config_from_env, find_config, load_config, render_toml, sanitize_tag
from .flags import write_flags
from .parser import Card, Diagnostic
from .vault import discover, parse_sources


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="m2a", description="Convert Obsidian flashcard notes into Anki cards.")
    parser.add_argument("-c", "--config", type=Path, help=f"path to {CONFIG_FILE_NAME} (default: search upwards)")
    parser.add_argument("--vault", type=Path, help="override the vault directory from the config")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help=f"write a {CONFIG_FILE_NAME} (migrates a legacy .env if present)")
    p_init.add_argument("--vault", type=Path, dest="init_vault", help="vault directory to configure")
    p_init.add_argument("--force", action="store_true", help="overwrite an existing config")

    p_check = sub.add_parser("check", help="parse every note and report problems; changes nothing")
    p_check.add_argument("--course", help="only this course (folder name or tag; glob or substring)")
    p_check.add_argument("-v", "--verbose", action="store_true", help="also list every card")

    p_status = sub.add_parser("status", help="per course: cards total / added / pending")
    p_status.add_argument("--course", help="only this course")

    p_sync = sub.add_parser("sync", help="export pending cards and mark them as added")
    p_sync.add_argument("--course", help="only this course (folder name or tag; glob or substring)")
    p_sync.add_argument("--target", choices=["apkg", "anki"], default="apkg",
                        help="apkg: write a package file (default); anki: push via AnkiConnect")
    p_sync.add_argument("--update", action="store_true",
                        help="also re-export cards that were already added with an id (updates them in Anki)")
    p_sync.add_argument("-n", "--dry-run", action="store_true", help="show what would be exported, write nothing")
    p_sync.add_argument("--no-flag", action="store_true", help="export but do not write ADDED flags into the notes")
    p_sync.add_argument("-y", "--yes", action="store_true", help="do not ask before writing ADDED flags")
    p_sync.add_argument("-o", "--output", type=Path, help="apkg path (default: <output_dir>/<package_name>.apkg)")

    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            return cmd_init(args)
        cfg = _load(args)
        if args.command == "check":
            return cmd_check(cfg, args)
        if args.command == "status":
            return cmd_status(cfg, args)
        if args.command == "sync":
            return cmd_sync(cfg, args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


# ----------------------------------------------------------------------------------------------------------------------


def _load(args: argparse.Namespace) -> Config:
    cfg = load_config(args.config)
    if args.vault:
        cfg.vault = args.vault.expanduser()
    return cfg


def cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.config) if args.config else Path(CONFIG_FILE_NAME)
    if target.exists() and not args.force:
        print(f"{target} already exists (use --force to overwrite)")
        return 1

    env = Path(".env")
    if env.is_file():
        cfg = config_from_env(env)
        print(f"migrated settings from {env}")
    else:
        cfg = Config(vault=Path(args.init_vault or "."))

    if args.init_vault:
        cfg.vault = Path(args.init_vault)
    cfg.output_dir = Path("output")

    # Suggest display titles for the subjects so the card corner is not empty.
    if cfg.subjects:
        for folder, tag in cfg.subjects.items():
            cfg.display.setdefault(tag, folder)
    elif cfg.vault.is_dir():
        for folder in sorted(p.name for p in cfg.vault.iterdir() if p.is_dir() and not p.name.startswith(".")):
            if folder not in cfg.ignore:
                cfg.display.setdefault(sanitize_tag(folder), folder)

    target.write_text(render_toml(cfg), encoding="utf-8")
    print(f"wrote {target}")
    return 0


def _collect(cfg: Config, course: Optional[str]):
    diagnostics: List[Diagnostic] = []
    sources = discover(cfg, course, diagnostics)
    cards = parse_sources(sources, diagnostics)
    return sources, cards, diagnostics


def _print_diagnostics(diagnostics: List[Diagnostic], cfg: Config) -> int:
    errors = 0
    for d in sorted(diagnostics, key=lambda d: (str(d.file), d.line)):
        try:
            rel = d.file.relative_to(cfg.vault)
        except ValueError:
            rel = d.file
        location = f"{rel}:{d.line}" if d.line else str(rel)
        print(f"  {d.level:7} {location}: {d.message}")
        if d.level == "error":
            errors += 1
    return errors


def cmd_check(cfg: Config, args: argparse.Namespace) -> int:
    sources, cards, diagnostics = _collect(cfg, args.course)
    result = build([c for c in cards if c.pending], diagnostics)

    print(f"vault: {cfg.vault}")
    print(f"notes: {len(sources)}   cards: {len(cards)}   pending: {sum(c.pending for c in cards)}   "
          f"added: {sum(c.added for c in cards)}")
    if args.verbose:
        for card in cards:
            state = "added" if card.added else "pending"
            first = card.question.split("\n", 1)[0]
            print(f"  [{state:7}] {card.tag}  {card.file.name}:{card.line}  {first[:70]}")
    if diagnostics:
        print("problems:")
        errors = _print_diagnostics(diagnostics, cfg)
    else:
        errors = 0
        print("problems: none")
    if result.skipped:
        print(f"{len(result.skipped)} pending card(s) would be skipped because of errors")
    return 1 if errors else 0


def cmd_status(cfg: Config, args: argparse.Namespace) -> int:
    sources, cards, diagnostics = _collect(cfg, args.course)
    rows: "OrderedDict[str, List[int]]" = OrderedDict()
    for source in sources:
        rows.setdefault(f"{source.course} / {source.subdirectory}", [0, 0, 0])
    for card in cards:
        key = f"{card.file.parent.parent.name} / {card.file.parent.name}"
        row = rows.setdefault(key, [0, 0, 0])
        row[0] += 1
        row[1 if card.added else 2] += 1

    width = max([len(k) for k in rows] + [10])
    print(f"{'course / folder':<{width}}  {'total':>5}  {'added':>5}  {'pending':>7}")
    for key, (total, added, pending) in rows.items():
        print(f"{key:<{width}}  {total:>5}  {added:>5}  {pending:>7}")
    total = sum(r[0] for r in rows.values())
    print(f"{'all':<{width}}  {total:>5}  {sum(r[1] for r in rows.values()):>5}  "
          f"{sum(r[2] for r in rows.values()):>7}")
    warnings = [d for d in diagnostics if d.level != "info"]
    if warnings:
        print(f"{len(warnings)} problem(s) - run `m2a check`")
    return 0


def cmd_sync(cfg: Config, args: argparse.Namespace) -> int:
    sources, cards, diagnostics = _collect(cfg, args.course)
    selected = [c for c in cards if c.pending or (args.update and c.updatable)]
    result = build(selected, diagnostics)

    errors = [d for d in diagnostics if d.level == "error"]
    if diagnostics:
        print("problems:")
        _print_diagnostics(diagnostics, cfg)
    n_new = sum(1 for n in result.notes if not n.card.added)
    n_upd = sum(1 for n in result.notes if n.card.added)
    print(f"cards: {n_new} new, {n_upd} update(s), {len(result.occlusions)} image occlusion(s), "
          f"{len(result.skipped)} skipped")

    if not result.notes and not result.occlusions:
        print("nothing to export")
        return 1 if errors else 0

    if args.dry_run:
        for note in result.notes:
            first = note.card.question.split("\n", 1)[0]
            state = "update" if note.card.added else "new"
            print(f"  [{state:6}] {note.card.tag}  {note.card.file.name}:{note.card.line}  {first[:70]}")
        print("dry run - nothing written")
        return 0

    if args.target == "anki":
        from .export.ankiconnect import AnkiConnectError, export_ankiconnect
        try:
            flags, added, updated = export_ankiconnect(result, cfg)
        except AnkiConnectError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"AnkiConnect: {added} added, {updated} updated in deck '{cfg.deck}'")
        if result.occlusions:
            print(f"{len(result.occlusions)} image occlusion(s) are not pushed via AnkiConnect; use --target apkg")
    else:
        from .export.apkg import export_apkg
        output = args.output or (cfg.output_dir / f"{cfg.package_name}.apkg")
        flags, occlusion_dir = export_apkg(result, cfg, output)
        print(f"wrote {output}  (deck '{cfg.deck}', {len(result.notes)} notes, "
              f"{sum(len(n.media) for n in result.notes)} media files)")
        if occlusion_dir:
            print(f"image occlusion sources copied to {occlusion_dir} (one folder per tag)")

    if args.no_flag:
        print("ADDED flags not written (--no-flag)")
        return 0

    new_flags = [(card, cid) for card, cid in flags if card.card_id != cid]
    if not new_flags:
        return 0
    files = {card.file for card, _ in new_flags}
    if not args.yes:
        answer = input(f"mark {len(new_flags)} card(s) in {len(files)} note(s) as ADDED? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("flags not written; re-run with --update later to avoid duplicates, or delete the export")
            return 0
    flagged, problems = write_flags(new_flags)
    print(f"flagged {flagged} card(s) in {len(files)} note(s)")
    for problem in problems:
        print(f"  warning {problem}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
