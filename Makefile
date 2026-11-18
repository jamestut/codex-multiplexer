.PHONY: build package

BINARY_NAMES := codex-multiplexer-linux-x64 codex-multiplexer-linux-arm64 codex-multiplexer-darwin-arm64
BINARY_ARCHIVES := $(addprefix dist/,$(addsuffix .tar.xz,$(BINARY_NAMES)))
PYTHON_SCRIPTS := $(wildcard scripts/*.py)

# Refresh release metadata on each run and share it across all binaries.
# Only use Git metadata when this project is the repository root.
build:
	@set -eu; \
	root_dir=$$(pwd -P); \
	dist_dir="$$root_dir/dist"; \
	build_time=$$(date -u '+%Y-%m-%dT%H:%M:%SZ'); \
	version=dev; \
	if git_root=$$(git rev-parse --show-toplevel 2>/dev/null) && [ "$$git_root" = "$$root_dir" ]; then \
		if { version=$$(git describe --tags --exact-match HEAD 2>/dev/null) || \
			version=$$(git rev-parse --short HEAD 2>/dev/null); } && \
			status=$$(git status --porcelain --untracked-files=all 2>/dev/null); then \
			if [ -n "$$status" ]; then \
				version="$${version}-dev"; \
			fi; \
		else \
			version=dev; \
		fi; \
	fi; \
	ldflags="-s -w -X main.version=$$version -X main.buildTime=$$build_time"; \
	mkdir -p "$$dist_dir"; \
	cd "$$root_dir/src"; \
	CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags="$$ldflags" -o "$$dist_dir/codex-multiplexer-linux-x64" .; \
	CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -trimpath -ldflags="$$ldflags" -o "$$dist_dir/codex-multiplexer-linux-arm64" .; \
	CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 go build -trimpath -ldflags="$$ldflags" -o "$$dist_dir/codex-multiplexer-darwin-arm64" .

package: $(BINARY_ARCHIVES) dist/scripts.tar.xz

# Binaries have no build rule, so packaging requires an explicit build first.
$(BINARY_ARCHIVES): dist/%.tar.xz: dist/%
	cd dist && tar -cJf "$(@F)" "$(*F)"

dist/scripts.tar.xz: $(PYTHON_SCRIPTS) | dist
	tar -cJf "$@" $(PYTHON_SCRIPTS)

dist:
	mkdir -p "$@"
