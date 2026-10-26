#!/usr/bin/env python3

import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import codex_launcher
from codex_scripts_common import load_launcher_config, resolve_configured_path, resolve_vscode_codex_path


def load_extensions_dir() -> Path:
    config_path, config = load_launcher_config(Path(__file__))
    return resolve_configured_path(config_path, "extensions_dir", config.get("extensions_dir"))


def launch(args: Optional[list[str]] = None) -> None:
    extensions_dir = load_extensions_dir()
    codex_path = resolve_vscode_codex_path(extensions_dir)
    codex_launcher.launch(
        multiplexer_path=codex_path,
        args=sys.argv[1:] if args is None else args,
        fallback_to_path=True,
    )


def main() -> int:
    try:
        launch()
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"vscode-codex-launcher: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
