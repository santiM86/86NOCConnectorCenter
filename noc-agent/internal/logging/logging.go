// Package logging provides a tiny structured logger that ships every entry
// both to stderr (human-readable) and to a channel that the WebSocket
// transport drains and forwards to the backend as agent.log frames.
package logging

import (
	"fmt"
	"log/slog"
	"os"
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

// New returns a root logger that writes JSON lines to stderr.
func New() *Logger {
	h := slog.NewJSONHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelInfo})
	return &Logger{
		slog: slog.New(h),
		buf:  make(chan Entry, 1024),
	}
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
