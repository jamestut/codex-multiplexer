import json
import os
import platform
import stat
from pathlib import Path
from typing import Union


def discover_config_path(script_path: Path) -> Path:
    """Find the config.json file associated with a script, following symlink targets."""
    script_path = Path(os.path.abspath(script_path))
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


def load_launcher_config(script_path: Path) -> tuple[Path, dict[str, object]]:
    """Load and validate the launcher configuration associated with a script."""
    config_path = discover_config_path(script_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    allowed_keys = {"multiplexer_path", "extensions_dir"}
    if not isinstance(config, dict) or not set(config).issubset(allowed_keys):
        raise ValueError(f"{config_path} may contain only multiplexer_path and extensions_dir")
    return config_path, config


def resolve_configured_path(config_path: Path, key: str, value: object) -> Path:
    """Resolve a configured path relative to the directory containing its config."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"{config_path} key {key} must be a non-empty string")

    # Keep executable symlinks intact for config discovery and execution.
    configured_path = Path(value).expanduser()
    if not configured_path.is_absolute():
        configured_path = config_path.parent / configured_path
    return configured_path


def validate_executable(path: Union[str, Path], label: str) -> None:
    """Ensure that a path names an existing executable file."""
    if not os.path.isfile(path):
        raise ValueError(f"{label} executable not found: {path}")
    if not os.access(path, os.X_OK):
        raise ValueError(f"{label} executable is not executable: {path}")


def read_extensions_index(extensions_dir: Path) -> list[object]:
    """Read and validate the extensions.json array in an extensions directory."""
    index_path = extensions_dir / "extensions.json"
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Extensions index not found: {index_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {index_path}: {exc}") from exc

    if not isinstance(data, list):
        raise ValueError(f"Expected {index_path} to contain a JSON array")
    return data


def resolve_extension_dir(extensions_dir: Path) -> Path:
    """Locate the installed openai.chatgpt extension from the extensions index."""
    matches = []
    for entry in read_extensions_index(extensions_dir):
        if not isinstance(entry, dict):
            continue
        identifier = entry.get("identifier")
        if isinstance(identifier, dict) and identifier.get("id") == "openai.chatgpt":
            matches.append(entry)

    if not matches:
        raise ValueError(f"No openai.chatgpt entry found in {extensions_dir / 'extensions.json'}")
    if len(matches) > 1:
        raise ValueError(
            f"Multiple openai.chatgpt entries found in {extensions_dir / 'extensions.json'}"
        )

    entry = matches[0]
    relative_location = entry.get("relativeLocation")
    if isinstance(relative_location, str) and relative_location:
        resolved = extensions_dir / relative_location
        if resolved.is_dir():
            return resolved
        raise ValueError(f"Registered openai.chatgpt relativeLocation does not exist: {resolved}")

    location = entry.get("location")
    if isinstance(location, dict) and location.get("scheme") == "file":
        location_path = location.get("path")
        if isinstance(location_path, str) and location_path:
            resolved = Path(location_path)
            if resolved.is_dir():
                return resolved
            raise ValueError(f"Registered openai.chatgpt location does not exist: {resolved}")

    raise ValueError("The openai.chatgpt entry did not contain a usable location")


def resolve_binary_relative_path(extension_dir: Path) -> Path:
    """Select the Codex binary's relative path for the current platform."""
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
        raise ValueError(f"Executable bin directory not found: {bin_dir}")

    candidates = sorted(
        child
        for child in bin_dir.iterdir()
        if child.is_dir() and not child.name.startswith(".")
    )
    if not candidates:
        raise ValueError(f"No non-hidden platform directories found in: {bin_dir}")
    return Path("bin") / candidates[0].name / "codex"


def resolve_codex_path(extension_dir: Path) -> Path:
    """Return the validated path to the Codex executable in an extension."""
    codex_path = extension_dir / resolve_binary_relative_path(extension_dir)
    validate_executable(codex_path, "Codex")
    return codex_path


def resolve_vscode_codex_path(extensions_dir: Path) -> Path:
    """Find and validate the Codex executable in the VS Code extensions directory."""
    extension_dir = resolve_extension_dir(extensions_dir)
    return resolve_codex_path(extension_dir)
