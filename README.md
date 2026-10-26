# Codex app-server multiplexer

This project lets multiple local Codex app server clients that typically uses stdio transport (e.g. Codex IDE extensions) share one persistent Codex app-server process. The wrapper starts the server on the first invocation and connects later clients through a Unix socket.

## Build and configuration

For a native build from the repository root, put the executable and its config together:

```sh
(cd src && go build -o ../codex-multiplexer .)
cp src/config.example.json config.json
```

Edit `config.json` before running `./codex-multiplexer app-server`. Set `log_path` and `runtime_dir` to absolute paths. `codex_path` may be absolute or relative. Optionally set `codex_home` to an absolute path to override `CODEX_HOME` for Codex processes the wrapper starts. If omitted, Codex inherits the wrapper's environment. The override applies when a server starts; an already running server keeps its existing environment. `~` is not expanded. The runtime directory is created automatically. The parent directory for the log file must already exist.

To build release artifacts, run `./dist-tool/build.sh` from the repository root, or invoke that script by its path from another working directory. It writes these files under the repository's `dist/` directory:

- `codex-multiplexer-linux-x64`
- `codex-multiplexer-linux-arm64`
- `codex-multiplexer-darwin-arm64`

The release builds use `CGO_ENABLED=0`, `-trimpath`, and `-ldflags='-s -w'`. Go's default optimizations remain enabled. The symbol table and DWARF debug information are stripped, with no separate debug artifact; `-trimpath` removes local build paths from compiled file metadata.

To package each release binary with the Python scripts, run `./dist-tool/package.sh` after building. It writes one ZIP per binary under `dist/`; each ZIP contains the binary at its root and the Python files under `scripts/`. The script can also be invoked by its path from another working directory and requires the `zip` command.

For example, to run the Linux x64 artifact, place its config beside the executable and update the paths for your environment:

```sh
cp src/config.example.json dist/config.json
./dist/codex-multiplexer-linux-x64 app-server
```

The supported macOS version depends on the Go compiler. According to the [Go minimum requirements](https://go.dev/wiki/MinimumRequirements), Go 1.26, including 1.26.7, requires macOS 12 or later, while Go 1.27 requires macOS 13 or later. Cross-compiling from Linux does not lower the minimum macOS version.

## Runtime behavior

Config lookup checks beside the invoked path first, including when it is a symlink, then checks beside each symlink target one hop at a time through the real executable. The first config found is used; only a missing config advances lookup, while an unreadable or invalid config stops with an error. For example, if `/a/codex-multiplexer` points to `/b/codex-multiplexer`, which points to the real executable at `/c/codex-multiplexer`, lookup order is `/a/config.json`, `/b/config.json`, then `/c/config.json`.

A relative `codex_path` is resolved from the directory of the originally invoked wrapper path, without following wrapper symlinks. This is independent of the working directory and the directory containing the selected config. For example, if `/a/codex-multiplexer` points to `/b/codex-multiplexer` and the config is found in `/b`, either `./codex` or `codex` as `codex_path` means `/a/codex`; a bare `codex` is not looked up in `PATH`.

Run `./codex-multiplexer app-server` or `./codex-multiplexer app-server --listen stdio://`. The executable may be symlinked and invoked from another location. The first invocation starts Codex using its arguments, working directory, and environment; later invocations connect to that server. The server keeps running after wrapper clients exit. The log is appended with wrapper failures and Codex output.

Keep stdin open until you have received the responses you need; closing stdin disconnects that client.

## Diagnostic information

Run `./codex-multiplexer --multiplexer-info` with no other arguments to print a JSON object to stdout and exit:

```json
{
  "codex_path": "/path/to/original/codex",
  "socket_path": "/path/to/runtime/app-server.sock",
  "running": true
}
```

`running` reports whether the configured Codex app server socket responds to a WebSocket handshake.

## Python launchers

`scripts/codex_launcher.py` queries the configured multiplexer and launches the original Codex executable used by it. If the multiplexer reports that the Codex app server is running, it makes `codex` connect to that existing app server instead.

`scripts/vscode_codex_launcher.py` finds the registered VS Code Codex extension and selects its binary using explicit mappings for Linux x86_64, Linux aarch64, and macOS arm64. On other platforms, it selects `codex` from the alphabetically first non-hidden directory under the extension's `bin` directory, which may not match the current platform. It uses the multiplexer launcher when that binary reports valid multiplexer information; otherwise, it runs the binary directly.

Both scripts look for `config.json` beside the invoked script, and then beside each symlink target, one hop at a time. The first config found is used; only a missing config advances lookup, while an unreadable or invalid config stops with an error. Their config keys are:

```json
{
  "multiplexer_path": "/path/to/codex-multiplexer",
  "extensions_dir": "/path/to/vscode/extensions"
}
```

`multiplexer_path` is required by `codex_launcher.py` and `extensions_dir` is required by `vscode_codex_launcher.py`. Relative values are resolved from the selected config's directory. When installing elsewhere, keep `codex_launcher.py`, `vscode_codex_launcher.py`, and their shared helper `codex_scripts_common.py` together, or symlink the launcher commands into your `PATH`.
