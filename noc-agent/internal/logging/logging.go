// Package logging provides a tiny structured logger that ships every entry
// both to stderr (human-readable) and to a channel that the WebSocket
// transport drains and forwards to the backend as agent.log frames.
package logging

import (
	"fmt"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"runtime"
	"sync"
	"time"
)

// Entry is the in-process representation of a log line. It mirrors
// proto.AgentLog but lives outside that package to avoid an import cycle.
type Entry struct {
	Time   time.Time
	Level  string
	Module string
	Msg    string
	Fields map[string]string
}

// Logger is a thread-safe ring-bufferless logger. Backend shipping happens
// via the channel returned by Stream(), drained by the transport layer.
type Logger struct {
	slog *slog.Logger

	mu     sync.Mutex
	buf    chan Entry
	module string
}

// defaultLogPath returns the platform-default log file path. On Windows this
// goes under %ProgramData%\86NocAgent\logs so it survives uninstall and is
// readable from the tray menu's "Apri cartella log" action. On Linux/macOS we
// fall back to /var/log or the user cache dir.
func defaultLogPath() string {
	if env := os.Getenv("ARGUS_LOG_PATH"); env != "" {
		return env
	}
	switch runtime.GOOS {
	case "windows":
		base := os.Getenv("ProgramData")
		if base == "" {
			base = `C:\ProgramData`
		}
		return filepath.Join(base, "86NocAgent", "logs", "nocagent.log")
	case "darwin":
		return "/var/log/86nocagent/nocagent.log"
	default:
		return "/var/log/86nocagent/nocagent.log"
	}
}

// openLogFile creates the directory and opens the log file in append+create
// mode. Returns nil if it can't be opened (we degrade gracefully to stderr-only
// logging — the agent must never fail to start because of a logging issue).
func openLogFile(path string) *os.File {
	if path == "" {
		return nil
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return nil
	}
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return nil
	}
	return f
}

// New returns a root logger that writes JSON lines to **both** stderr and a
// rotating-friendly log file (default %ProgramData%\86NocAgent\logs\nocagent.log
// on Windows). When the agent runs as a Windows service stderr is dropped by
// the SCM, so the file sink is the only persistent diagnostic channel.
//
// IMPORTANT: il file log e' fondamentale per il troubleshooting in produzione:
// lo usiamo per capire perche' un connector non si aggancia al WS, o perche'
// l'SNMP polling fallisce su un device.
func New() *Logger {
	logPath := defaultLogPath()
	var sink io.Writer = os.Stderr
	if f := openLogFile(logPath); f != nil {
		sink = io.MultiWriter(os.Stderr, f)
	}
	level := slog.LevelInfo
	if lv := os.Getenv("ARGUS_LOG_LEVEL"); lv != "" {
		switch lv {
		case "debug", "DEBUG":
			level = slog.LevelDebug
		case "warn", "WARN":
			level = slog.LevelWarn
		case "error", "ERROR":
			level = slog.LevelError
		}
	}
	h := slog.NewJSONHandler(sink, &slog.HandlerOptions{
		Level:     level,
		AddSource: false,
	})
	l := &Logger{
		slog: slog.New(h),
		buf:  make(chan Entry, 1024),
	}
	// Banner di avvio: con questa entry sempre presente in cima a ogni
	// rotazione l'admin sa subito quale path / pid / versione runtime
	// sta producendo il log.
	l.With("startup").Info("logger initialized",
		"log_path", logPath,
		"goos", runtime.GOOS,
		"goarch", runtime.GOARCH,
		"pid", fmt.Sprintf("%d", os.Getpid()),
		"level", level.String(),
	)
	return l
}

// With returns a child logger that tags every entry with the given module.
func (l *Logger) With(module string) *Logger {
	return &Logger{slog: l.slog, buf: l.buf, module: module}
}

// Stream returns the channel that the transport drains to ship logs to the
// backend. Drops are silent: stderr always receives the line.
func (l *Logger) Stream() <-chan Entry { return l.buf }

func (l *Logger) emit(level, msg string, fields map[string]string) {
	e := Entry{Time: time.Now().UTC(), Level: level, Module: l.module, Msg: msg, Fields: fields}
	// Build slog attrs from fields so they appear in stderr too.
	attrs := []any{"module", l.module}
	for k, v := range fields {
		attrs = append(attrs, k, v)
	}
	switch level {
	case "debug":
		l.slog.Debug(msg, attrs...)
	case "warn":
		l.slog.Warn(msg, attrs...)
	case "error":
		l.slog.Error(msg, attrs...)
	default:
		l.slog.Info(msg, attrs...)
	}
	select {
	case l.buf <- e:
	default:
		// channel full - drop on the floor, stderr already has it
	}
}

func (l *Logger) Info(msg string, fields ...string)  { l.emit("info", msg, kv(fields)) }
func (l *Logger) Warn(msg string, fields ...string)  { l.emit("warn", msg, kv(fields)) }
func (l *Logger) Error(msg string, fields ...string) { l.emit("error", msg, kv(fields)) }
func (l *Logger) Debug(msg string, fields ...string) { l.emit("debug", msg, kv(fields)) }

// Errorf is a convenience for formatted error logging.
func (l *Logger) Errorf(format string, args ...any) {
	l.emit("error", fmt.Sprintf(format, args...), nil)
}

func kv(parts []string) map[string]string {
	if len(parts) == 0 {
		return nil
	}
	m := make(map[string]string, len(parts)/2)
	for i := 0; i+1 < len(parts); i += 2 {
		m[parts[i]] = parts[i+1]
	}
	return m
}
