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

// candidateLogPaths returns an ordered list of log file paths to try, in
// priority order. The first one whose parent directory we can MkdirAll AND
// where OpenFile succeeds wins. The list always ends with stderr-only mode
// (an empty string) so the agent never refuses to start because of logging.
//
// Windows priority (chosen 2026-02 per user request to avoid ACL issues on
// %ProgramData% when the service runs as LocalSystem with restricted SACL):
//  1. $ARGUS_LOG_PATH (operator override)
//  2. %LOCALAPPDATA%\86NocAgent\logs\nocagent.log
//     - When the service runs as LocalSystem this resolves to
//       C:\Windows\System32\config\systemprofile\AppData\Local which is always
//       writable by SYSTEM.
//     - When started interactively (debug) it falls under the user's profile.
//  3. %USERPROFILE%\AppData\Local\86NocAgent\logs\nocagent.log
//     (fallback when LOCALAPPDATA is empty, e.g. some Win Server 2016 service hosts)
//  4. %ProgramData%\86NocAgent\logs\nocagent.log (legacy, kept for upgrade compat)
func candidateLogPaths() []string {
	if env := os.Getenv("ARGUS_LOG_PATH"); env != "" {
		return []string{env}
	}
	switch runtime.GOOS {
	case "windows":
		var out []string
		if lad := os.Getenv("LOCALAPPDATA"); lad != "" {
			out = append(out, filepath.Join(lad, "86NocAgent", "logs", "nocagent.log"))
		}
		if up := os.Getenv("USERPROFILE"); up != "" {
			out = append(out, filepath.Join(up, "AppData", "Local", "86NocAgent", "logs", "nocagent.log"))
		}
		if pd := os.Getenv("ProgramData"); pd != "" {
			out = append(out, filepath.Join(pd, "86NocAgent", "logs", "nocagent.log"))
		} else {
			out = append(out, `C:\ProgramData\86NocAgent\logs\nocagent.log`)
		}
		// Hard-coded systemprofile path as last-resort when LocalSystem service
		// has no env vars wired up at all (observed on some hardened Win10).
		out = append(out, `C:\Windows\System32\config\systemprofile\AppData\Local\86NocAgent\logs\nocagent.log`)
		return out
	case "darwin":
		return []string{"/var/log/86nocagent/nocagent.log"}
	default:
		return []string{"/var/log/86nocagent/nocagent.log"}
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

// openFirstWritableLog walks the candidate paths returned by candidateLogPaths
// and returns the first successfully opened file together with its absolute
// path. The returned path is empty if every candidate failed (stderr-only mode).
//
// We surface the resolved path so the logger's startup banner can record it as
// "log_path", crucial when diagnosing "where are my logs?" tickets remotely.
func openFirstWritableLog(candidates []string) (*os.File, string) {
	for _, p := range candidates {
		if f := openLogFile(p); f != nil {
			return f, p
		}
	}
	return nil, ""
}

// writeLogPathMarker drops a small text file at a well-known stable location so
// out-of-process tools (the tray UI nocui, the PowerShell installer, support
// scripts) can discover where the agent is actually writing logs. This matters
// now that the resolved path depends on which Windows account the service
// runs as: LocalSystem → %SystemProfile%, interactive admin → %LOCALAPPDATA%.
//
// We intentionally use %ProgramData% (machine-wide, always writable by SYSTEM)
// for the marker so the tray running as the interactive user can still read it
// even when the log file itself lives under SYSTEM's profile.
func writeLogPathMarker(resolvedLogPath string) {
	if resolvedLogPath == "" {
		return
	}
	if runtime.GOOS != "windows" {
		return
	}
	pd := os.Getenv("ProgramData")
	if pd == "" {
		pd = `C:\ProgramData`
	}
	markerDir := filepath.Join(pd, "86NocAgent")
	if err := os.MkdirAll(markerDir, 0o755); err != nil {
		return
	}
	marker := filepath.Join(markerDir, "log_path.txt")
	_ = os.WriteFile(marker, []byte(resolvedLogPath), 0o644)
}

// safeMultiWriter scrive su piu' Writer ma **ignora gli errori** di ciascuno e
// continua con quelli successivi. Necessario perche' quando l'agent gira come
// Windows Service il SCM chiude os.Stderr: una scrittura su stderr ritorna
// errore e l'std io.MultiWriter interromperebbe il fan-out al file di log.
type safeMultiWriter struct {
	writers []io.Writer
}

func (s *safeMultiWriter) Write(p []byte) (int, error) {
	for _, w := range s.writers {
		if w == nil {
			continue
		}
		_, _ = w.Write(p) // errori intenzionalmente ignorati
	}
	return len(p), nil
}

// New returns a root logger that writes JSON lines to **both** stderr and a
// rotating-friendly log file. The file sink path is selected at runtime from
// candidateLogPaths() — on Windows we now prefer %LOCALAPPDATA%\86NocAgent\logs
// (always writable by both LocalSystem and interactive users) and fall back to
// %USERPROFILE%, %ProgramData% and the systemprofile path before giving up.
//
// When the agent runs as a Windows service stderr is dropped by the SCM, so the
// file sink is the only persistent diagnostic channel. We MUST always succeed
// in opening at least one of the candidates, otherwise tickets like "agent
// crashes silently with no nocagent.log" become impossible to triage.
func New() *Logger {
	candidates := candidateLogPaths()
	fileSink, logPath := openFirstWritableLog(candidates)
	writers := []io.Writer{os.Stderr}
	if fileSink != nil {
		writers = append(writers, fileSink)
	}
	sink := &safeMultiWriter{writers: writers}
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
	// sta producendo il log. Tracciamo anche tutte le candidate provate per
	// rendere ovvio quale fallback ha vinto.
	resolved := logPath
	if resolved == "" {
		resolved = "(stderr-only, all file candidates failed)"
	}
	// Persist the resolved path so the tray UI and installer scripts can
	// locate the active log file even when the service runs as a different
	// account than the interactive user.
	writeLogPathMarker(logPath)
	l.With("startup").Info("logger initialized",
		"log_path", resolved,
		"candidates", fmt.Sprintf("%v", candidates),
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
