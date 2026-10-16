# Codex app-server multiplexer

Build the wrapper and prepare its config alongside the real executable:

```sh
go build -o codex-multiplexer .
cp config.example.json config.json
```

Edit `config.json` with the three absolute paths. The wrapper resolves symlinks before locating it; `~` is not expanded. The runtime directory is created automatically. The parent directory for the log file must already exist.

Run `./codex-multiplexer app-server` or `./codex-multiplexer app-server --listen stdio://`. The executable may be symlinked and invoked from another location. The first invocation starts Codex using its arguments, working directory, and environment; later invocations connect to that server. The server keeps running after wrapper clients exit. The log is appended with wrapper failures and Codex output.

Keep stdin open until you have received the responses you need; closing stdin disconnects that client.
