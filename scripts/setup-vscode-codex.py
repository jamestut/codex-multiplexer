#!/usr/bin/env python3

import argparse
import json
import os
import platform
import sys
from pathlib import Path


class SetupError(Exception):
    pass


def read_extensions_index(extensions_dir: Path) -> list[object]:
    index_path = extensions_dir / "extensions.json"
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SetupError(f"Extensions index not found: {index_path}") from exc
    except json.JSONDecodeError as exc:
        raise SetupError(f"Invalid JSON in {index_path}: {exc}") from exc

    if not isinstance(data, list):
        raise SetupError(f"Expected {index_path} to contain a JSON array")
    return data


def resolve_extension_dir(extensions_dir: Path) -> Path:
    matches = []
    for entry in read_extensions_index(extensions_dir):
        if not isinstance(entry, dict):
            continue
        identifier = entry.get("identifier")
        if isinstance(identifier, dict) and identifier.get("id") == "openai.chatgpt":
            matches.append(entry)

    if not matches:
        raise SetupError(f"No openai.chatgpt entry found in {extensions_dir / 'extensions.json'}")
    if len(matches) > 1:
        raise SetupError(
            f"Multiple openai.chatgpt entries found in {extensions_dir / 'extensions.json'}"
        )

    entry = matches[0]
    relative_location = entry.get("relativeLocation")
    if isinstance(relative_location, str) and relative_location:
        resolved = extensions_dir / relative_location
        if resolved.is_dir():
            return resolved
        raise SetupError(f"Registered openai.chatgpt relativeLocation does not exist: {resolved}")

    location = entry.get("location")
    if isinstance(location, dict) and location.get("scheme") == "file":
        location_path = location.get("path")
        if isinstance(location_path, str) and location_path:
            resolved = Path(location_path)
            if resolved.is_dir():
                return resolved
            raise SetupError(f"Registered openai.chatgpt location does not exist: {resolved}")

    raise SetupError("The openai.chatgpt entry did not contain a usable location")


def resolve_binary_relative_path(extension_dir: Path) -> Path:
    system = platform.system().lower()
    machine = platform.machine().lower()

    binary_map = {
        ("linux", "x86_64"): Path("bin/linux-x86_64/codex"),
        ("linux", "aarch64"): Path("bin/linux-aarch64/codex"),
        ("darwin", "arm64"): Path("bin/macos-aarch64/codex"),
    }

    binary_relative_path = binary_map.get((system, machine))
    if binary_relative_path is not None:
        return binary_relative_path

    bin_dir = extension_dir / "bin"
    if not bin_dir.is_dir():
        raise SetupError(f"Executable bin directory not found: {bin_dir}")

    candidates = sorted(
        child
        for child in bin_dir.iterdir()
        if child.is_dir() and not child.name.startswith(".")
    )
    if not candidates:
        raise SetupError(f"No non-hidden platform directories found in: {bin_dir}")
    return Path("bin") / candidates[0].name / "codex"


def resolve_codex_path(extension_dir: Path) -> Path:
    codex_path = extension_dir / resolve_binary_relative_path(extension_dir)
    if not codex_path.is_file():
        raise SetupError(f"Codex executable not found: {codex_path}")
    if not os.access(codex_path, os.X_OK):
        raise SetupError(f"Codex executable is not executable: {codex_path}")
    if codex_path.is_symlink():
        raise SetupError(f"Refusing to replace an existing Codex symlink: {codex_path}")
    return codex_path


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
    if not os.path.isfile(args.multiplexer_path):
        raise SetupError(f"Multiplexer executable not found: {args.multiplexer_path}")
    if not os.access(args.multiplexer_path, os.X_OK):
        raise SetupError(f"Multiplexer executable is not executable: {args.multiplexer_path}")

    extensions_dir = args.extensions_dir
    extension_dir = resolve_extension_dir(extensions_dir)
    codex_path = resolve_codex_path(extension_dir)
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
