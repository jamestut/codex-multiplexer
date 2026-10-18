#!/usr/bin/env python3

import json
import os
import stat
import subprocess
import sys
from pathlib import Path


def discover_config_path(script_path: Path) -> Path:
    visited = set()
    while True:
        if script_path in visited:
            raise ValueError(f"Script symlink cycle at {script_path}")
        visited.add(script_path)

        config_path = script_path.parent / "config.json"
        # Only a missing config advances to the next symlink target.
        try:
            config_path.stat()
        except FileNotFoundError:
            if not stat.S_ISLNK(script_path.lstat().st_mode):
                raise
        else:
            return config_path

        target = Path(os.readlink(script_path))
        if not target.is_absolute():
            target = script_path.parent / target
        # Resolve directory symlinks and "..", leaving the final link for the next config check.
        script_path = target.parent.resolve(strict=True) / target.name


def load_multiplexer_path() -> Path:
    config_path = discover_config_path(Path(os.path.abspath(__file__)))
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or set(config) != {"multiplexer_path"}:
        raise ValueError(f"{config_path} must contain only the key multiplexer_path")
    value = config["multiplexer_path"]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{config_path} key multiplexer_path must be a non-empty string")

    # Keep the executable's symlink intact for the multiplexer's own config discovery.
    multiplexer_path = Path(value)
    if not multiplexer_path.is_absolute():
        multiplexer_path = config_path.parent / multiplexer_path
    return multiplexer_path


def launch() -> None:
    result = subprocess.run(
        [str(load_multiplexer_path()), "--multiplexer-info"],
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

    args = [codex_path]
    if info["running"]:
        socket_path = info.get("socket_path")
        if not isinstance(socket_path, str) or not socket_path:
            raise ValueError("Multiplexer info must contain a non-empty socket_path")
        args.extend(["--remote", "unix://" + socket_path])
    args.extend(sys.argv[1:])
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
