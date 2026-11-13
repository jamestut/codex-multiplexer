#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd "$SCRIPT_DIR/.." && pwd)
DIST_DIR=$ROOT_DIR/dist

for command in tar xz; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "$command command not found" >&2
        exit 1
    fi
done

BINARIES="codex-multiplexer-linux-x64 codex-multiplexer-linux-arm64 codex-multiplexer-darwin-arm64"
for binary in $BINARIES; do
    if [ ! -f "$DIST_DIR/$binary" ]; then
        echo "Required binary not found: $DIST_DIR/$binary" >&2
        echo "Run dist-tool/build.sh first." >&2
        exit 1
    fi
done

set -- "$ROOT_DIR"/scripts/*.py
if [ ! -f "$1" ]; then
    echo "No Python scripts found in $ROOT_DIR/scripts" >&2
    exit 1
fi

cd "$DIST_DIR"
for binary in $BINARIES; do
    tar -cJf "$binary.tar.xz" "$binary"
done

# Preserve the scripts/ directory in the separate archive.
cd "$ROOT_DIR"
tar -cJf "$DIST_DIR/scripts.tar.xz" scripts/*.py
