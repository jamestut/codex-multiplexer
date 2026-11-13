#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd -P)
ROOT_DIR=$(CDPATH= cd "$SCRIPT_DIR/.." && pwd -P)
DIST_DIR=$ROOT_DIR/dist

build_time=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
version=dev

# Only use metadata from this project, not an enclosing repository.
if git_root=$(git -C "$ROOT_DIR" rev-parse --show-toplevel 2>/dev/null) && [ "$git_root" = "$ROOT_DIR" ]; then
	if version=$(git -C "$ROOT_DIR" describe --tags --exact-match HEAD 2>/dev/null); then
		git_metadata=1
	elif version=$(git -C "$ROOT_DIR" rev-parse --short HEAD 2>/dev/null); then
		git_metadata=1
	else
		version=dev
		git_metadata=0
	fi
	if [ "$git_metadata" -eq 1 ]; then
		if status=$(git -C "$ROOT_DIR" status --porcelain --untracked-files=all 2>/dev/null); then
			if [ -n "$status" ]; then
				version="${version}-dev"
			fi
		else
			version=dev
		fi
	fi
fi

ldflags="-s -w -X main.version=$version -X main.buildTime=$build_time"
mkdir -p "$DIST_DIR"
cd "$ROOT_DIR/src"

CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags="$ldflags" -o "$DIST_DIR/codex-multiplexer-linux-x64" .
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -trimpath -ldflags="$ldflags" -o "$DIST_DIR/codex-multiplexer-linux-arm64" .
CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 go build -trimpath -ldflags="$ldflags" -o "$DIST_DIR/codex-multiplexer-darwin-arm64" .
