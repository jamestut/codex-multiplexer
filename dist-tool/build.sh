#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd "$SCRIPT_DIR/.." && pwd)
DIST_DIR=$ROOT_DIR/dist

mkdir -p "$DIST_DIR"
cd "$ROOT_DIR/src"

CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags='-s -w' -o "$DIST_DIR/codex-multiplexer-linux-x64" .
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -trimpath -ldflags='-s -w' -o "$DIST_DIR/codex-multiplexer-linux-arm64" .
CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 go build -trimpath -ldflags='-s -w' -o "$DIST_DIR/codex-multiplexer-darwin-arm64" .
