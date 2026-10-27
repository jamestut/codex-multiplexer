#!/usr/bin/env python3

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence, Union

sys.path.insert(0, str(Path(__file__).resolve().parent))

from codex_scripts_common import load_launcher_config, resolve_configured_path


def load_multiplexer_path() -> Path:
    config_path, config = load_launcher_config(Path(__file__))
    if "multiplexer_path" not in config:
        raise ValueError(f"{config_path} is missing the key multiplexer_path")
    return resolve_configured_path(config_path, "multiplexer_path", config["multiplexer_path"])


def launch(
    multiplexer_path: Optional[Union[str, Path]] = None,
    args: Optional[Sequence[str]] = None,
    *,
    fallback_to_path: bool = False,
) -> None:
    """Launch Codex through a multiplexer, optionally falling back to that executable."""
    selected_path = Path(multiplexer_path) if multiplexer_path is not None else load_multiplexer_path()
    forwarded_args = list(sys.argv[1:] if args is None else args)

    try:
        result = subprocess.run(
            [str(selected_path), "--multiplexer-info"],
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            check=True,
        )
        info = json.loads(result.stdout)
        if not isinstance(info, dict) or not isinstance(info.get("running"), bool):
            raise ValueError("Multiplexer info must contain a boolean running field")
        codex_path = info.get("codex_path")
        if not isinstance(codex_path, str) or not codex_path:
            raise ValueError("Multiplexer info must contain a non-empty codex_path")
        socket_path = info.get("socket_path")
        if info["running"] and (not isinstance(socket_path, str) or not socket_path):
            raise ValueError("Multiplexer info must contain a non-empty socket_path")
    except (OSError, ValueError, subprocess.CalledProcessError):
        if not fallback_to_path:
            raise
        os.execv(str(selected_path), [str(selected_path), *forwarded_args])

    if forwarded_args == ["--multiplexer-info"]:
        print(json.dumps(info, indent=2))
        return

    args = [codex_path]
    if info["running"]:
        args.extend(["--remote", "unix://" + socket_path])
    args.extend(forwarded_args)
    # Replace the launcher so Codex inherits the terminal, signals, and exit status.
    os.execv(codex_path, args)


def main() -> int:
    try:
        launch()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"codex-launcher: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
