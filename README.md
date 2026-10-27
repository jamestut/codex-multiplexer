# Codex app-server multiplexer

Share one persistent Codex app server between local clients, such as Codex IDE extensions. The first client starts the server. Later clients connect to the same server.

## Get started

Download and extract the binary for your system. The release archive also contains the Python scripts used below.

### Set up the VS Code extension

Install the Codex extension in VS Code, then run the setup script with your extensions directory and the absolute path to the multiplexer binary:

```sh
python3 scripts/setup_vscode_codex.py /path/to/vscode/extensions /absolute/path/to/codex-multiplexer
```

The script renames the extension's Codex executable to `codex-original` and replaces it with a symlink to the multiplexer. It also creates a `config.json` beside the symlink. Run `python3 scripts/setup_vscode_codex.py --help` to see the available options.

Start the Codex extension as usual. The first client starts the shared app server.

### Configure manually

To use another client, create a `config.json` beside the multiplexer executable:

```json
{
  "codex_path": "/absolute/path/to/codex",
  "log_path": "/absolute/path/to/codex-multiplexer.log",
  "runtime_dir": "/absolute/path/to/codex-multiplexer-state"
}
```

Set `codex_path` to the original Codex executable. Set `log_path` and `runtime_dir` to absolute paths. The log file's parent directory must already exist. The multiplexer creates the runtime directory if needed.

Optionally, add `"codex_home": "/absolute/path/to/codex-home"` to override `CODEX_HOME` when starting a server. Otherwise, Codex inherits the wrapper's environment. An already running server keeps its existing environment. Paths do not expand `~`.

Configure your client to run the multiplexer in place of Codex. The wrapper accepts `app-server` or `app-server --listen stdio://` as arguments. Keep the client's stdin open until it has received the responses it needs.

## Check the server

Run the multiplexer with no other arguments:

```sh
./codex-multiplexer --multiplexer-info
```

The output contains the original Codex path, the socket path, and a `running` value. `running` is `true` when the app server responds to a connection. Use the path through which your client invokes the multiplexer to check the same configuration.

## How it works

### Finding configuration

The multiplexer looks for `config.json` beside the executable used to start it. If that executable is a symlink and no config is found, it checks beside the symlink's target. It continues through the chain until it finds a config.

The first config found is used. An invalid or unreadable config causes an error.

A relative `codex_path` is resolved beside the executable used to start the multiplexer, even if the config is found elsewhere. A bare name is not looked up in `PATH`.

### Finding an existing server

The multiplexer checks the socket in the configured `runtime_dir`. It attempts a connection to confirm that the app server is responding.

If the server is available, the client connects to it. If the socket is unavailable, the multiplexer starts a new server. Other connection errors are reported.

The first invocation supplies the server's arguments, working directory, and environment. The server keeps running after clients disconnect. Wrapper errors and Codex output are appended to the log file.

## Python launchers

Use `scripts/codex_launcher.py` to launch the original Codex executable. When the multiplexer reports a running app server, the launcher connects Codex to that server.

Use `scripts/vscode_codex_launcher.py` to locate the Codex executable installed by the VS Code extension. It uses the multiplexer launcher when that executable reports valid multiplexer information. Otherwise, it runs the executable directly.

The launchers look for `config.json` beside the invoked script. If the script is a symlink, they also check each target until a config is found. An invalid or unreadable config causes an error.

Create a launcher config with the keys needed by the scripts you use:

```json
{
  "multiplexer_path": "/path/to/codex-multiplexer",
  "extensions_dir": "/path/to/vscode/extensions"
}
```

`codex_launcher.py` requires `multiplexer_path`. `vscode_codex_launcher.py` requires `extensions_dir`. Relative paths are resolved from the config's directory.

Keep both launchers and `codex_scripts_common.py` together when installing them elsewhere. You can also symlink the launcher commands into your `PATH`.

## Build from source

Install Go; see its [system requirements](https://go.dev/wiki/MinimumRequirements). From the repository root, run:

```sh
(cd src && go build -o ../codex-multiplexer .)
cp src/config.example.json config.json
```

Edit `config.json` for your environment before running the multiplexer.

To build release binaries, run `./dist-tool/build.sh`. To package them with the Python scripts, run `./dist-tool/package.sh` afterward. Both write their output to `dist/`; packaging requires `zip`.
