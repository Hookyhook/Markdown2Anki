"""m2a - command line interface for Markdown2Anki."""
from __future__ import annotations

import argparse
import shutil
import sys
from collections import OrderedDict
from pathlib import Path
from typing import List, Optional

from . import ui
from .build import build
from .config import (CONFIG_FILE_NAME, Config, config_from_env, find_config, load_config, render_toml,
                     sanitize_tag, user_config_path)
from .flags import clear_flags, write_flags
from .parser import Card, Diagnostic
from .vault import discover, parse_sources


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="m2a", description="Convert Obsidian flashcard notes into Anki cards.")
    parser.add_argument("-c", "--config", type=Path, help=f"path to {CONFIG_FILE_NAME} (default: search upwards, "
                                                          f"then {user_config_path()})")
    parser.add_argument("--vault", type=Path, help="override the vault directory from the config")
    parser.add_argument("--trace", action="store_true", help="log each phase to stderr (also: M2A_TRACE=1)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help=f"write {CONFIG_FILE_NAME} for a vault (refuses to overwrite)")
    p_init.add_argument("--vault", type=Path, dest="init_vault", help="vault directory (required unless a legacy "
                                                                     ".env in the current directory names one)")
    p_init.add_argument("--here", action="store_true",
                        help=f"write ./{CONFIG_FILE_NAME} instead of the user config {user_config_path()}")
    p_init.add_argument("--force", action="store_true", help="overwrite an existing config (keeps a .bak copy)")

    sub.add_parser("config", help="show which config is in use and its contents")

    p_check = sub.add_parser("check", help="parse every note and report problems; changes nothing")
    p_check.add_argument("--course", help="only this course (folder name or tag; glob or substring)")
    p_check.add_argument("-v", "--verbose", action="store_true", help="also list every card")

    p_status = sub.add_parser("status", help="per course: cards total / added / pending")
    p_status.add_argument("--course", help="only this course")

    p_unflag = sub.add_parser("unflag", help="remove ADDED flags so cards are exported again as new cards")
    p_unflag.add_argument("--course", help="only this course (folder name or tag; glob or substring)")
    p_unflag.add_argument("--file", type=Path, help="only this note")
    p_unflag.add_argument("--legacy", action="store_true", help="only old `ADDED: ` flags without an id")
    p_unflag.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")

    p_sync = sub.add_parser("sync", help="export pending cards and mark them as added")
    p_sync.add_argument("--course", help="only this course (folder name or tag; glob or substring)")
    p_sync.add_argument("--target", choices=["apkg", "anki"], default=None,
                        help="apkg: write a package file; anki: push via AnkiConnect (default: 'target' in config)")
    p_sync.add_argument("--update", action="store_true",
                        help="also re-export cards that were already added with an id (updates them in Anki)")
    p_sync.add_argument("-n", "--dry-run", action="store_true", help="show what would be exported, write nothing")
    p_sync.add_argument("--no-flag", action="store_true", help="export but do not write ADDED flags into the notes")
    p_sync.add_argument("-y", "--yes", action="store_true", help="do not ask before writing ADDED flags")
    p_sync.add_argument("-o", "--output", type=Path, help="apkg path (default: <output_dir>/<package_name>.apkg)")

    args = parser.parse_args(argv)
    if args.trace:
        ui.enable_trace()
    try:
        sys.stdout.reconfigure(line_buffering=True)  # show output promptly even through a pipe
    except (AttributeError, ValueError):
        pass
    ui.trace(f"start: command={args.command} cwd={Path.cwd()}")
    try:
        if args.command == "init":
            return cmd_init(args)
        cfg = _load(args)
        if args.command == "config":
            return cmd_config(cfg)
        if args.command == "check":
            return cmd_check(cfg, args)
        if args.command == "status":
            return cmd_status(cfg, args)
        if args.command == "sync":
            return cmd_sync(cfg, args)
        if args.command == "unflag":
            return cmd_unflag(cfg, args)
    except (FileNotFoundError, ValueError) as exc:
        _error(str(exc))
        return 2
    except KeyboardInterrupt:
        print()
        print(ui.dim("aborted - nothing written"))
        return 130
    return 0


def _confirm(question: str) -> bool:
    print()
    try:
        answer = input(f"  {ui.bold(question)} [y/N] ")
    except EOFError:
        print()
        return False
    return answer.strip().lower() in ("y", "yes")


# ----------------------------------------------------------------------------------------------------------------------


def _error(message: str, hint: Optional[str] = None) -> None:
    print(f"{ui.red('error')} {message}", file=sys.stderr)
    if hint:
        print(f"{ui.dim('hint')}  {hint}", file=sys.stderr)


def _load(args: argparse.Namespace) -> Config:
    ui.trace("loading config")
    cfg = load_config(args.config)
    if args.vault:
        cfg.vault = args.vault.expanduser()
    ui.trace(f"config {cfg.source}  vault {cfg.vault}")
    return cfg


def _rel(path: Path, cfg: Config) -> str:
    try:
        return str(path.relative_to(cfg.vault))
    except ValueError:
        return str(path)


def _print_diagnostics(diagnostics: List[Diagnostic], cfg: Config, indent: str = "  ") -> int:
    errors = 0
    for d in sorted(diagnostics, key=lambda d: (str(d.file), d.line)):
        location = f"{_rel(d.file, cfg)}:{d.line}" if d.line else _rel(d.file, cfg)
        print(f"{indent}{ui.level(d.level)} {ui.cyan(location)}  {d.message}")
        if d.level == "error":
            errors += 1
    return errors


def _summary_line(diagnostics: List[Diagnostic]) -> str:
    errors = sum(1 for d in diagnostics if d.level == "error")
    warnings = sum(1 for d in diagnostics if d.level == "warning")
    if not errors and not warnings:
        return ui.green("✓ no problems")
    parts = []
    if errors:
        parts.append(ui.red(f"{errors} error{'s' if errors != 1 else ''}"))
    if warnings:
        parts.append(ui.yellow(f"{warnings} warning{'s' if warnings != 1 else ''}"))
    return "✗ " + ", ".join(parts)


def _collect(cfg: Config, course: Optional[str]):
    diagnostics: List[Diagnostic] = []
    ui.trace("discovering notes")
    sources = discover(cfg, course, diagnostics)
    ui.trace(f"parsing {len(sources)} note(s)")
    cards = []
    for source in sources:
        ui.trace(f"  {source.path}")
        cards.extend(parse_sources([source], diagnostics))
    ui.trace(f"{len(cards)} card(s)")
    return sources, cards, diagnostics


# ----------------------------------------------------------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    env = Path(".env")
    if env.is_file():
        cfg = config_from_env(env)
        migrated = True
    else:
        cfg = Config(vault=Path("."))
        migrated = False
    if args.init_vault:
        cfg.vault = Path(args.init_vault).expanduser()
    elif not migrated:
        _error("tell me where the vault is: m2a init --vault ~/Documents/obsidian")
        return 2

    if not cfg.vault.is_dir():
        _error(f"vault directory not found: {cfg.vault}")
        return 2
    courses = sorted(p.name for p in cfg.vault.iterdir()
                     if p.is_dir() and not p.name.startswith(".") and p.name not in cfg.ignore)
    if not courses:
        _error(f"no course folders in {cfg.vault}", "expected <vault>/<course>/Anki - Lectures/*.md")
        return 2

    target = Path(args.config) if args.config else (Path(CONFIG_FILE_NAME) if args.here else user_config_path())
    existing = find_config() if not args.config else (target if target.exists() else None)
    if existing and not args.force:
        _error(f"a config already exists: {existing}",
               "edit it, or re-run with --force to replace it (a .bak copy is kept)")
        return 1
    if target.exists() and args.force:
        backup = target.with_suffix(".toml.bak")
        shutil.copy2(target, backup)
        print(f"{ui.dim('backup')} {backup}")

    cfg.vault = cfg.vault.resolve()
    cfg.output_dir = Path("output") if args.here else Path("~/Downloads/Markdown2Anki")
    if cfg.subjects:
        for folder, tag in cfg.subjects.items():
            cfg.display.setdefault(tag, folder)
    else:
        for folder in courses:
            cfg.display.setdefault(sanitize_tag(folder), folder)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_toml(cfg), encoding="utf-8")
    print(f"{ui.green('✓')} wrote {ui.bold(str(target))}" + (ui.dim("  (migrated from .env)") if migrated else ""))
    print(f"  {ui.dim('vault')}   {cfg.vault}")
    print(f"  {ui.dim('courses')} {', '.join(courses)}")
    print(f"  {ui.dim('target')}  {cfg.target}")
    print()
    print("next:")
    print(f"  {ui.cyan('m2a check')}           see problems before exporting")
    print(f"  {ui.cyan('m2a status')}          counts per course")
    print(f"  {ui.cyan('m2a sync --dry-run')}  preview the first export")
    return 0


def cmd_config(cfg: Config) -> int:
    print(f"{ui.dim('config')} {ui.bold(str(cfg.source))}")
    print(f"{ui.dim('vault')}  {cfg.vault}")
    print()
    if cfg.source and cfg.source.is_file():
        for line in cfg.source.read_text(encoding="utf-8").splitlines():
            print(ui.dim(line) if line.startswith("#") else line)
    return 0


def cmd_check(cfg: Config, args: argparse.Namespace) -> int:
    sources, cards, diagnostics = _collect(cfg, args.course)
    result = build([c for c in cards if c.pending], diagnostics, cfg.cloze_notes)

    print(ui.header("m2a check") + ui.dim(f"  {cfg.vault}"))
    print("  " + ui.kv([("notes", len(sources)), ("cards", len(cards)),
                        ("pending", sum(c.pending for c in cards)), ("added", sum(c.added for c in cards))]))
    if args.verbose and cards:
        print()
        rows = []
        for card in cards:
            state = ui.dim("added") if card.added else ui.green("pending")
            rows.append([state, f"{card.file.name}:{card.line}", card.tag.split("::", 1)[-1],
                         card.question.split("\n", 1)[0][:60]])
        print("  " + ui.table(rows, ["state", "where", "tag", "question"]).replace("\n", "\n  "))
    print()
    print("  " + _summary_line(diagnostics))
    errors = _print_diagnostics([d for d in diagnostics if d.level != "info"], cfg, indent="    ")
    if any(d.level == "info" for d in diagnostics):
        for d in diagnostics:
            if d.level == "info":
                print(f"    {ui.level('info')} {ui.cyan(_rel(d.file, cfg))}  {d.message}")
    if result.skipped:
        print(f"  {ui.yellow(str(len(result.skipped)))} pending card(s) would be skipped because of errors")
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

    print(ui.header("m2a status") + ui.dim(f"  {cfg.vault}"))
    table_rows = []
    for key, (total, added, pending) in rows.items():
        table_rows.append([key, str(total), str(added), ui.green(str(pending)) if pending else ui.dim("0")])
    totals = [sum(r[i] for r in rows.values()) for i in range(3)]
    table_rows.append([ui.bold("all"), ui.bold(str(totals[0])), ui.bold(str(totals[1])), ui.bold(str(totals[2]))])
    print("  " + ui.table(table_rows, ["course / folder", "total", "added", "pending"],
                          align_right=[1, 2, 3]).replace("\n", "\n  "))
    problems = [d for d in diagnostics if d.level != "info"]
    if problems:
        print(f"  {_summary_line(problems)}  {ui.dim('- run `m2a check`')}")
    return 0


def cmd_unflag(cfg: Config, args: argparse.Namespace) -> int:
    sources, cards, diagnostics = _collect(cfg, args.course)
    chosen = [c for c in cards if c.added]
    if args.file:
        wanted = args.file.expanduser().resolve()
        chosen = [c for c in chosen if c.file.resolve() == wanted]
    if args.legacy:
        chosen = [c for c in chosen if c.card_id is None]

    print(ui.header("m2a unflag") + ui.dim(f"  {cfg.vault}"))
    if not chosen:
        print(f"  {ui.dim('no flagged cards match')}")
        return 0
    rows = []
    for card in chosen:
        rows.append([ui.dim(card.card_id or "legacy"), f"{_rel(card.file, cfg)}:{card.line}",
                     card.question.split("\n", 1)[0][:60]])
    print("  " + ui.table(rows, ["id", "where", "question"]).replace("\n", "\n  "))
    print()
    print(f"  {ui.yellow('note:')} unflagged cards are exported again as {ui.bold('new')} notes; "
          f"delete the old ones in Anki yourself if they were imported.")
    if not args.yes and not _confirm(f"remove the flag from {len(chosen)} card(s)?"):
        print(f"  {ui.dim('nothing changed')}")
        return 0
    cleared, problems = clear_flags(chosen)
    print(f"  {ui.green('✓')} unflagged {ui.bold(str(cleared))} card(s)")
    for problem in problems:
        print(f"    {ui.level('warning')} {problem}")
    return 0


def cmd_sync(cfg: Config, args: argparse.Namespace) -> int:
    sources, cards, diagnostics = _collect(cfg, args.course)
    selected = [c for c in cards if c.pending or (args.update and c.updatable)]
    result = build(selected, diagnostics, cfg.cloze_notes)
    target = args.target or cfg.target

    print(ui.header("m2a sync") + ui.dim(f"  {cfg.vault}  →  {target}"))
    errors = [d for d in diagnostics if d.level == "error"]
    problems = [d for d in diagnostics if d.level != "info"]
    if problems:
        print("  " + _summary_line(problems))
        _print_diagnostics(problems, cfg, indent="    ")
    n_new = sum(1 for n in result.notes if not n.card.added)
    n_upd = sum(1 for n in result.notes if n.card.added)
    print("  " + ui.kv([("new", n_new), ("updates", n_upd), ("image occlusions", len(result.occlusions)),
                        ("skipped", len(result.skipped))]))

    if not result.notes and not result.occlusions:
        print(f"  {ui.dim('nothing to export')}")
        return 1 if errors else 0

    if args.dry_run:
        print()
        rows = []
        for note in result.notes:
            state = ui.yellow("update") if note.card.added else ui.green("new")
            rows.append([state, f"{note.card.file.name}:{note.card.line}", note.card.tag.split("::", 1)[-1],
                         note.card.question.split("\n", 1)[0][:60]])
        print("  " + ui.table(rows, ["", "where", "tag", "question"]).replace("\n", "\n  "))
        print()
        print(f"  {ui.dim('dry run - nothing written')}")
        return 0

    n_before_export = len(diagnostics)
    if target == "anki":
        from .export.ankiconnect import AnkiConnectError, export_ankiconnect
        try:
            flags, added, updated = export_ankiconnect(result, cfg, diagnostics)
        except AnkiConnectError as exc:
            _error(str(exc), "open Anki (with the AnkiConnect add-on) and retry, or use `m2a sync --target apkg`")
            return 2
        print(f"  {ui.green('✓')} AnkiConnect: {ui.bold(str(added))} added, {ui.bold(str(updated))} updated "
              f"in deck {ui.bold(cfg.deck)}")
        if result.occlusions:
            print(f"  {ui.yellow('!')} {len(result.occlusions)} image occlusion(s) are not pushed via AnkiConnect; "
                  f"use --target apkg")
    else:
        from .export.apkg import export_apkg
        output = args.output or (cfg.output_dir / f"{cfg.package_name}.apkg")
        flags, occlusion_dir = export_apkg(result, cfg, output, diagnostics)
        media = sum(len(n.media) for n in result.notes)
        print(f"  {ui.green('✓')} wrote {ui.bold(str(output))}  {ui.dim(f'deck {cfg.deck}, {len(result.notes)} notes, {media} media files')}")
        if occlusion_dir:
            print(f"  {ui.dim('image occlusion sources:')} {occlusion_dir}  {ui.dim('(one folder per tag)')}")

    _print_diagnostics(diagnostics[n_before_export:], cfg, indent="    ")

    if args.no_flag:
        print(f"  {ui.dim('ADDED flags not written (--no-flag)')}")
        return 0

    new_flags = [(card, cid) for card, cid in flags if card.card_id != cid]
    if not new_flags:
        return 0
    files = {card.file for card, _ in new_flags}
    if not args.yes and not _confirm(f"mark {len(new_flags)} card(s) in {len(files)} note(s) as ADDED?"):
        print(f"  {ui.yellow('flags not written')} - the same cards will be exported again next time; "
              f"re-run with --update if they were imported")
        return 0
    flagged, problems_written = write_flags(new_flags)
    print(f"  {ui.green('✓')} flagged {ui.bold(str(flagged))} card(s) in {len(files)} note(s)")
    for problem in problems_written:
        print(f"    {ui.level('warning')} {problem}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
