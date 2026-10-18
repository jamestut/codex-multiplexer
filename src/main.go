package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/gorilla/websocket"
	"golang.org/x/sys/unix"
)

const (
	socketName       = "app-server.sock"
	startupLockName  = "startup.lock"
	startupTimeout   = 10 * time.Second
	startupRetryWait = 100 * time.Millisecond
)

type config struct {
	CodexPath  string  `json:"codex_path"`
	CodexHome  *string `json:"codex_home"`
	LogPath    string  `json:"log_path"`
	RuntimeDir string  `json:"runtime_dir"`
}

func main() {
	if err := run(); err != nil {
		os.Exit(1)
	}
}

func run() error {
	executable, err := invokedExecutablePath()
	if err != nil {
		return reportBootstrapError(err)
	}

	cfg, logFile, err := readConfigAndOpenLog(executable)
	if err != nil {
		return reportBootstrapError(err)
	}
	defer logFile.Close()
	logger := log.New(logFile, "", log.LstdFlags)
	// Capturing fd 2 also records runtime and panic diagnostics in the wrapper log.
	if err := unix.Dup2(int(logFile.Fd()), int(os.Stderr.Fd())); err != nil {
		logger.Printf("ERROR: redirect stderr to log: %v", err)
		return err
	}
	// Broken stdout pipes should become logged write errors instead of SIGPIPE exits.
	signal.Ignore(syscall.SIGPIPE)

	// Resolve relative Codex paths beside the originally invoked wrapper, preserving its symlink location.
	if cfg.CodexPath != "" && !filepath.IsAbs(cfg.CodexPath) {
		cfg.CodexPath = filepath.Join(filepath.Dir(executable), cfg.CodexPath)
	}
	if err := validateConfig(cfg); err != nil {
		logger.Printf("ERROR: %v", err)
		return err
	}
	args, err := codexArguments(os.Args[1:])
	if err != nil {
		logger.Printf("ERROR: %v", err)
		return err
	}

	conn, err := ensureServerConnection(cfg, args, logger, logFile)
	if err != nil {
		logger.Printf("ERROR: %v", err)
		return err
	}
	defer conn.Close()

	if err := bridge(conn); err != nil {
		logger.Printf("ERROR: %v", err)
		return err
	}
	return nil
}

func reportBootstrapError(err error) error {
	fmt.Fprintln(os.Stderr, "codex-multiplexer:", err)
	return err
}

// Preserve the invoked path because resolving the running executable loses symlink aliases.
func invokedExecutablePath() (string, error) {
	path := os.Args[0]
	if path == "" {
		return "", errors.New("locate wrapper executable: empty invocation path")
	}
	if !strings.ContainsRune(path, os.PathSeparator) {
		// A relative PATH match is valid here because the wrapper is already running.
		resolved, err := exec.LookPath(path)
		if err != nil && !errors.Is(err, exec.ErrDot) {
			return "", fmt.Errorf("locate wrapper executable: %w", err)
		}
		path = resolved
	}
	path, err := filepath.Abs(path)
	if err != nil {
		return "", fmt.Errorf("make wrapper path absolute: %w", err)
	}
	return path, nil
}

// Check each invoked path before following one symlink; only a missing config advances.
func discoverConfigPath(executable string) (string, error) {
	visited := make(map[string]struct{})
	for {
		if _, ok := visited[executable]; ok {
			return "", fmt.Errorf("resolve wrapper symlinks: cycle at %s", executable)
		}
		visited[executable] = struct{}{}

		configPath := filepath.Join(filepath.Dir(executable), "config.json")
		_, err := os.Stat(configPath)
		if err == nil {
			return configPath, nil
		}
		if !errors.Is(err, os.ErrNotExist) {
			return "", fmt.Errorf("inspect config %s: %w", configPath, err)
		}
		missingConfigErr := err

		info, err := os.Lstat(executable)
		if err != nil {
			return "", fmt.Errorf("inspect wrapper path %s: %w", executable, err)
		}
		if info.Mode()&os.ModeSymlink == 0 {
			return "", fmt.Errorf("inspect config %s: %w", configPath, missingConfigErr)
		}
		target, err := os.Readlink(executable)
		if err != nil {
			return "", fmt.Errorf("read wrapper symlink %s: %w", executable, err)
		}
		targetPath := target
		if !filepath.IsAbs(target) {
			targetPath = filepath.Dir(executable)
			if !strings.HasSuffix(targetPath, string(os.PathSeparator)) {
				targetPath += string(os.PathSeparator)
			}
			targetPath += target
		}
		// Keep the raw path until EvalSymlinks processes symlinked dirs and following ".." components.
		targetDir, targetName := filepath.Split(targetPath)
		unresolvedTargetDir := targetDir
		targetDir, err = filepath.EvalSymlinks(targetDir)
		if err != nil {
			return "", fmt.Errorf("resolve wrapper symlink target directory %s: %w", unresolvedTargetDir, err)
		}
		// Leave the target's final component unresolved for the next config check and symlink hop.
		executable = filepath.Join(targetDir, targetName)
	}
}

func readConfig(configPath string) (config, error) {
	data, err := os.ReadFile(configPath)
	if err != nil {
		return config{}, fmt.Errorf("read %s: %w", configPath, err)
	}
	var cfg config
	if err := json.Unmarshal(data, &cfg); err != nil {
		return config{}, fmt.Errorf("parse %s: %w", configPath, err)
	}
	if cfg.LogPath == "" {
		return cfg, fmt.Errorf("%s is missing mandatory key log_path", configPath)
	}
	if !filepath.IsAbs(cfg.LogPath) {
		return cfg, fmt.Errorf("%s key log_path must be an absolute path", configPath)
	}
	return cfg, nil
}

func readConfigAndOpenLog(executable string) (config, *os.File, error) {
	configPath, err := discoverConfigPath(executable)
	if err != nil {
		return config{}, nil, err
	}
	cfg, err := readConfig(configPath)
	if err != nil {
		return cfg, nil, err
	}

	// The log parent must already exist; creating it here could hide a bad config path.
	logFile, err := os.OpenFile(cfg.LogPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return cfg, nil, fmt.Errorf("open log %s: %w", cfg.LogPath, err)
	}
	return cfg, logFile, nil
}

func validateConfig(cfg config) error {
	for name, value := range map[string]string{
		"codex_path":  cfg.CodexPath,
		"log_path":    cfg.LogPath,
		"runtime_dir": cfg.RuntimeDir,
	} {
		if value == "" {
			return fmt.Errorf("config.json is missing mandatory key %s", name)
		}
		if !filepath.IsAbs(value) {
			return fmt.Errorf("config.json key %s must be an absolute path", name)
		}
	}
	if cfg.CodexHome != nil {
		if !filepath.IsAbs(*cfg.CodexHome) {
			return errors.New("config.json key codex_home must be an absolute path")
		}
	}
	return nil
}

func environmentWithOverride(env []string, name string, value string) []string {
	prefix := name + "="
	result := make([]string, 0, len(env)+1)
	for _, entry := range env {
		if !strings.HasPrefix(entry, prefix) {
			result = append(result, entry)
		}
	}
	return append(result, prefix+value)
}

func codexEnvironment(env []string, codexHome *string) []string {
	if codexHome == nil {
		return nil
	}
	return environmentWithOverride(env, "CODEX_HOME", *codexHome)
}

// Preserve all caller arguments except stdio transport flags, which the server replaces.
func codexArguments(args []string) ([]string, error) {
	result := make([]string, 0, len(args))
	foundAppServer := false
	for i := 0; i < len(args); i++ {
		arg := args[i]
		switch {
		case arg == "--listen":
			if i+1 >= len(args) {
				return nil, errors.New("--listen is missing its stdio value")
			}
			i++
			if !isStdioListen(args[i]) {
				return nil, fmt.Errorf("wrapper only supports stdio listen mode, got %q", args[i])
			}
		case strings.HasPrefix(arg, "--listen="):
			if !isStdioListen(strings.TrimPrefix(arg, "--listen=")) {
				return nil, fmt.Errorf("wrapper only supports stdio listen mode, got %q", arg)
			}
		case arg == "--stdio":
			// Some launchers express the stdio transport as a standalone flag.
		default:
			if arg == "app-server" {
				foundAppServer = true
			}
			result = append(result, arg)
		}
	}
	if !foundAppServer {
		return nil, errors.New("wrapper arguments must include app-server")
	}
	return result, nil
}

func isStdioListen(value string) bool {
	return value == "stdio://"
}

// Serialize the socket check and launch so concurrent wrappers share one server.
func ensureServerConnection(cfg config, args []string, logger *log.Logger, logFile *os.File) (*websocket.Conn, error) {
	if err := os.MkdirAll(cfg.RuntimeDir, 0o700); err != nil {
		return nil, fmt.Errorf("create runtime directory %s: %w", cfg.RuntimeDir, err)
	}

	socketPath := filepath.Join(cfg.RuntimeDir, socketName)
	lockPath := filepath.Join(cfg.RuntimeDir, startupLockName)
	lockFile, err := os.OpenFile(lockPath, os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return nil, fmt.Errorf("open startup lock %s: %w", lockPath, err)
	}
	defer lockFile.Close()

	if err := syscall.Flock(int(lockFile.Fd()), syscall.LOCK_EX); err != nil {
		return nil, fmt.Errorf("lock %s: %w", lockPath, err)
	}
	// Keep the lock until the WebSocket handshake succeeds so peers do not race startup.
	conn, connectErr := ensureLocked(cfg, args, socketPath, logger, logFile)
	unlockErr := syscall.Flock(int(lockFile.Fd()), syscall.LOCK_UN)
	if connectErr != nil {
		if conn != nil {
			conn.Close()
		}
		return nil, connectErr
	}
	if unlockErr != nil {
		conn.Close()
		return nil, fmt.Errorf("unlock %s: %w", lockPath, unlockErr)
	}
	return conn, nil
}

func ensureLocked(cfg config, args []string, socketPath string, logger *log.Logger, logFile *os.File) (*websocket.Conn, error) {
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	conn, err := dialUnix(ctx, socketPath)
	cancel()
	if err == nil {
		return conn, nil
	}
	if !isUnavailableSocketError(err) {
		return nil, fmt.Errorf("connect to existing app-server socket: %w", err)
	}

	// Append the Unix transport after preserving the caller's non-stdio arguments.
	commandArgs := append(append([]string(nil), args...), "--listen", "unix://"+socketPath)
	cmd := exec.Command(cfg.CodexPath, commandArgs...)
	cmd.Env = codexEnvironment(os.Environ(), cfg.CodexHome)
	// Passing the file directly avoids a wrapper-owned pipe that would close on exit.
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	// A new session keeps the daemon detached from wrapper and terminal signals.
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("start codex app-server: %w", err)
	}

	logger.Printf("started codex app-server pid=%d socket=%s", cmd.Process.Pid, socketPath)
	processDone := make(chan error, 1)
	go func() {
		waitErr := cmd.Wait()
		if waitErr != nil {
			logger.Printf("codex app-server exited: %v", waitErr)
		}
		processDone <- waitErr
	}()

	return waitForConnection(socketPath, processDone)
}

// Retry during startup only; process exit and explicit handshake rejection fail promptly.
func waitForConnection(socketPath string, processDone <-chan error) (*websocket.Conn, error) {
	deadline := time.Now().Add(startupTimeout)
	var lastErr error = errors.New("socket is not accepting connections")
	for time.Now().Before(deadline) {
		attemptCtx, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
		conn, dialErr := dialUnix(attemptCtx, socketPath)
		cancel()
		if dialErr == nil {
			return conn, nil
		}
		if !isUnavailableSocketError(dialErr) {
			return nil, fmt.Errorf("connect to app-server socket: %w", dialErr)
		}
		lastErr = dialErr

		select {
		case processErr := <-processDone:
			if processErr == nil {
				return nil, errors.New("codex app-server exited before its Unix socket became ready")
			}
			return nil, fmt.Errorf("codex app-server exited before its Unix socket became ready: %w", processErr)
		case <-time.After(startupRetryWait):
		}
	}
	return nil, fmt.Errorf("timed out waiting for app-server socket %s: %w", socketPath, lastErr)
}

func isUnavailableSocketError(err error) bool {
	return errors.Is(err, os.ErrNotExist) || errors.Is(err, syscall.ECONNREFUSED)
}

// Codex uses WebSocket frames over its Unix socket, not raw JSON lines.
func dialUnix(ctx context.Context, socketPath string) (*websocket.Conn, error) {
	dialer := websocket.Dialer{
		NetDialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
			return (&net.Dialer{}).DialContext(ctx, "unix", socketPath)
		},
	}
	conn, response, err := dialer.DialContext(ctx, "ws://localhost/rpc", nil)
	if err != nil {
		if response != nil && response.Body != nil {
			_ = response.Body.Close()
		}
		return nil, err
	}
	return conn, nil
}

func bridge(conn *websocket.Conn) error {
	// Separate goroutines keep stdin requests and socket responses flowing concurrently.
	stdinDone := make(chan error, 1)
	socketDone := make(chan error, 1)
	go func() { stdinDone <- copyStdinToSocket(conn) }()
	go func() { socketDone <- copySocketToStdout(conn) }()

	select {
	case err := <-socketDone:
		return err
	case err := <-stdinDone:
		if err != nil {
			return err
		}
		closeErr := conn.WriteMessage(websocket.CloseMessage, websocket.FormatCloseMessage(websocket.CloseNormalClosure, ""))
		if closeErr != nil && !isNormalClose(closeErr) {
			return fmt.Errorf("close app-server socket after stdin EOF: %w", closeErr)
		}
		// Codex may close the local socket without a WebSocket close frame after EOF.
		err = <-socketDone
		if isAbnormalClose(err) {
			return nil
		}
		return err
	}
}

// ReadBytes avoids Scanner's fixed token-size limit for large app-server requests.
func copyStdinToSocket(conn *websocket.Conn) error {
	reader := bufio.NewReader(os.Stdin)
	for {
		line, err := reader.ReadBytes('\n')
		if len(line) > 0 {
			line = bytes.TrimSuffix(line, []byte{'\n'})
			if len(bytes.TrimSpace(line)) > 0 {
				if writeErr := conn.WriteMessage(websocket.TextMessage, line); writeErr != nil {
					return fmt.Errorf("write request to app-server socket: %w", writeErr)
				}
			}
		}
		if err != nil {
			if errors.Is(err, io.EOF) {
				return nil
			}
			return fmt.Errorf("read request from stdin: %w", err)
		}
	}
}

// Each server text message is one JSON-RPC item, so restore its JSONL newline.
func copySocketToStdout(conn *websocket.Conn) error {
	for {
		messageType, message, err := conn.ReadMessage()
		if err != nil {
			if isNormalClose(err) {
				return nil
			}
			return fmt.Errorf("read response from app-server socket: %w", err)
		}
		if messageType != websocket.TextMessage {
			return fmt.Errorf("app-server socket sent unsupported WebSocket message type %d", messageType)
		}
		if _, err := os.Stdout.Write(message); err != nil {
			return fmt.Errorf("write response to stdout: %w", err)
		}
		if len(message) == 0 || message[len(message)-1] != '\n' {
			if _, err := os.Stdout.Write([]byte{'\n'}); err != nil {
				return fmt.Errorf("write response newline to stdout: %w", err)
			}
		}
	}
}

func isNormalClose(err error) bool {
	return errors.Is(err, io.EOF) || errors.Is(err, net.ErrClosed) || errors.Is(err, websocket.ErrCloseSent) || websocket.IsCloseError(err, websocket.CloseNormalClosure, websocket.CloseGoingAway)
}

func isAbnormalClose(err error) bool {
	var closeErr *websocket.CloseError
	return errors.As(err, &closeErr) && closeErr.Code == websocket.CloseAbnormalClosure
}
