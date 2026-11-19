#!/usr/bin/env python3
"""Launch Codex and connect to the shared app server when it is running.

For remote sessions, use the current directory unless the caller supplies
--cd or -C.

Set NOCM=1 to skip the automatic --remote and --cd flags. The launcher
still queries the multiplexer to locate Codex and passes your arguments unchanged.
Any non-empty NOCM value except the exact string "0" enables this mode.
"""

import json
import os
import subprocess
import sys
from itertools import takewhile
from pathlib import Path
from typing import Optional, Sequence, Union

sys.path.insert(0, str(Path(__file__).resolve().parent))

from codex_scripts_common import discover_config_path, load_launcher_config, resolve_configured_path


def load_multiplexer_path() -> Path:
    config_path, config = load_launcher_config(Path(__file__))
    if "multiplexer_path" not in config:
        raise ValueError(f"{config_path} is missing the key multiplexer_path")
    return resolve_configured_path(config_path, "multiplexer_path", config["multiplexer_path"])


def direct_codex_environment(multiplexer_path: Path) -> dict[str, str]:
    """Apply the multiplexer home settings to a standalone Codex process."""
    config_path = discover_config_path(multiplexer_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError(f"{config_path} must contain a JSON object")

    env = os.environ.copy()
    for key, name in (("codex_home", "CODEX_HOME"), ("codex_sqlite_home", "CODEX_SQLITE_HOME")):
        value = config.get(key)
        if value is not None:
            if not isinstance(value, str) or not os.path.isabs(value):
                raise ValueError(f"{config_path} key {key} must be an absolute path")
            env[name] = value
    return env


def launch(
    multiplexer_path: Optional[Union[str, Path]] = None,
    args: Optional[Sequence[str]] = None,
    *,
    fallback_to_path: bool = False,
) -> None:
    """Launch Codex through a multiplexer, optionally falling back to that executable."""
    selected_path = Path(multiplexer_path) if multiplexer_path is not None else load_multiplexer_path()
    forwarded_args = list(sys.argv[1:] if args is None else args)

    # Relay diagnostics directly, including failure JSON and the child exit status.
    if forwarded_args == ["--multiplexer-info"]:
        os.execv(str(selected_path), [str(selected_path), *forwarded_args])

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

    command = [codex_path]
    add_multiplexer_flags = os.environ.get("NOCM", "") in ("", "0")
    if info["running"] and add_multiplexer_flags:
        command.extend(["--remote", "unix://" + socket_path])
        # Arguments after -- are literal, even if they look like directory options.
        options = takewhile(lambda arg: arg != "--", forwarded_args)
        if not any(arg == "--cd" or arg.startswith(("--cd=", "-C")) for arg in options):
            command.extend(["--cd", os.getcwd()])
    command.extend(forwarded_args)
    # Explicit remote options also make this a client of an existing server.
    options = takewhile(lambda arg: arg != "--", forwarded_args)
    has_remote = any(arg == "--remote" or arg.startswith("--remote=") for arg in options)
    if (not info["running"] or not add_multiplexer_flags) and not has_remote:
        os.execve(codex_path, command, direct_codex_environment(selected_path))
    # Replace the launcher so Codex inherits the terminal, signals, and exit status.
    os.execv(codex_path, command)


def main() -> int:
    try:
        launch()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"codex-launcher: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
