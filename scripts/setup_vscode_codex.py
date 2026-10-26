#!/usr/bin/env python3

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from codex_scripts_common import resolve_vscode_codex_path, validate_executable


class SetupError(Exception):
    pass


def absolute_path(value: str) -> str:
    if not os.path.isabs(value):
        raise argparse.ArgumentTypeError("must be an absolute path")
    return value


def default_temp_dir() -> str:
    return os.path.abspath(os.environ.get("TMPDIR") or "/tmp")


def build_parser() -> argparse.ArgumentParser:
    temp_dir = default_temp_dir()
    parser = argparse.ArgumentParser(
        description="Route the VS Code Codex executable through codex-multiplexer."
    )
    parser.add_argument("extensions_dir", type=Path, help="VS Code extensions directory")
    parser.add_argument(
        "multiplexer_path",
        help="absolute path to codex-multiplexer (used literally as the symlink target)",
    )
    parser.add_argument(
        "-l",
        "--log-path",
        type=absolute_path,
        default=os.path.join(temp_dir, "codex-app-server", "log.log"),
        help="absolute log file path",
    )
    parser.add_argument(
        "-r",
        "--runtime-dir",
        type=absolute_path,
        default=os.path.join(temp_dir, "codex-app-server", "state"),
        help="absolute runtime directory",
    )
    parser.add_argument(
        "-s",
        "--skip-config",
        action="store_true",
        help="skip config.json generation",
    )
    return parser


def rollback_install(
    codex_path: Path,
    original_codex_path: Path,
    config_path: Path,
    moved: bool,
    linked: bool,
    config_created: bool,
) -> list[str]:
    rollback_errors = []
    if config_created:
        try:
            config_path.unlink()
        except OSError as exc:
            rollback_errors.append(f"remove incomplete config {config_path}: {exc}")
    if linked:
        try:
            codex_path.unlink()
        except OSError as exc:
            rollback_errors.append(f"remove multiplexer symlink {codex_path}: {exc}")
    if moved:
        try:
            os.rename(original_codex_path, codex_path)
        except OSError as exc:
            rollback_errors.append(f"restore Codex executable to {codex_path}: {exc}")
    return rollback_errors


def install(args: argparse.Namespace) -> Path:
    if not os.path.isabs(args.multiplexer_path):
        raise SetupError("multiplexer_path must be an absolute path")
    try:
        validate_executable(args.multiplexer_path, "Multiplexer")
    except ValueError as exc:
        raise SetupError(str(exc)) from exc

    extensions_dir = args.extensions_dir
    try:
        codex_path = resolve_vscode_codex_path(extensions_dir)
    except ValueError as exc:
        raise SetupError(str(exc)) from exc
    if codex_path.is_symlink():
        raise SetupError(f"Refusing to replace an existing Codex symlink: {codex_path}")
    original_codex_path = codex_path.parent / "codex-original"
    if os.path.lexists(original_codex_path):
        raise SetupError(f"Refusing to overwrite existing file: {original_codex_path}")

    config_path = codex_path.parent / "config.json"
    if os.path.lexists(config_path):
        raise SetupError(f"Config already exists: {config_path}")

    log_path = args.log_path
    runtime_dir = args.runtime_dir
    if not args.skip_config:
        try:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            Path(runtime_dir).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SetupError(f"Create config directories: {exc}") from exc

    moved = False
    linked = False
    config_created = False
    try:
        os.rename(codex_path, original_codex_path)
        moved = True
        os.symlink(args.multiplexer_path, codex_path)
        linked = True

        if not args.skip_config:
            config = {
                "codex_path": "codex-original",
                "log_path": log_path,
                "runtime_dir": runtime_dir,
            }
            with config_path.open("x", encoding="utf-8") as config_file:
                config_created = True
                json.dump(config, config_file, indent=2)
                config_file.write("\n")
    except OSError as exc:
        rollback_errors = rollback_install(
            codex_path,
            original_codex_path,
            config_path,
            moved,
            linked,
            config_created,
        )
        message = f"Install failed: {exc}"
        if rollback_errors:
            message += "; rollback issues: " + "; ".join(rollback_errors)
        raise SetupError(message) from exc

    return codex_path


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        installed_path = install(args)
    except SetupError as exc:
        parser.error(str(exc))
    print(f"Installed codex-multiplexer at {installed_path}")
    if args.skip_config:
        print('Hint: set "codex_path" to "codex-original" in config.json.')
    return 0


if __name__ == "__main__":
    sys.exit(main())
