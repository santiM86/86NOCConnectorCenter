package logging

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// TestCandidateLogPathsEnvOverride verifies that ARGUS_LOG_PATH takes absolute
// priority over every platform default. Operators rely on this to redirect
// logs onto a different volume (e.g. SAN) without recompiling.
func TestCandidateLogPathsEnvOverride(t *testing.T) {
	t.Setenv("ARGUS_LOG_PATH", "/tmp/custom-log/agent.log")
	got := candidateLogPaths()
	if len(got) != 1 || got[0] != "/tmp/custom-log/agent.log" {
		t.Fatalf("env override not honoured: %v", got)
	}
}

// TestCandidateLogPathsWindowsOrder verifies the priority chain on Windows:
// LOCALAPPDATA first, then USERPROFILE, then ProgramData, then systemprofile.
// This ordering is the heart of the fix for the "no nocagent.log when service
// runs as LocalSystem" bug — regressions here would silently break logging.
func TestCandidateLogPathsWindowsOrder(t *testing.T) {
	if runtime.GOOS != "windows" {
		t.Skip("Windows-specific ordering")
	}
	t.Setenv("ARGUS_LOG_PATH", "")
	t.Setenv("LOCALAPPDATA", `C:\Users\foo\AppData\Local`)
	t.Setenv("USERPROFILE", `C:\Users\foo`)
	t.Setenv("ProgramData", `C:\ProgramData`)

	got := candidateLogPaths()
	if len(got) < 4 {
		t.Fatalf("expected at least 4 candidates, got %d: %v", len(got), got)
	}
	if !strings.Contains(got[0], `AppData\Local\86NocAgent\logs`) {
		t.Errorf("expected LOCALAPPDATA first, got %q", got[0])
	}
	if !strings.Contains(got[1], `C:\Users\foo\AppData\Local\86NocAgent\logs`) {
		t.Errorf("expected USERPROFILE second, got %q", got[1])
	}
	if !strings.Contains(got[2], `C:\ProgramData\86NocAgent\logs`) {
		t.Errorf("expected ProgramData third, got %q", got[2])
	}
	if !strings.Contains(got[len(got)-1], `systemprofile`) {
		t.Errorf("expected systemprofile last, got %q", got[len(got)-1])
	}
}

// TestOpenFirstWritableLogPicksFirstWorking confirms that the helper walks the
// candidate list and stops at the first writable path. This is what guarantees
// the agent never falls through to stderr-only mode when at least one location
// is reachable.
func TestOpenFirstWritableLogPicksFirstWorking(t *testing.T) {
	tmp := t.TempDir()
	good := filepath.Join(tmp, "good", "agent.log")
	// On non-Windows hosts a path under a non-existent root cannot be
	// MkdirAll'd because permissions would fail; pick something obviously
	// invalid instead.
	bad := string([]byte{0}) // NUL byte → invalid argument on every OS

	candidates := []string{bad, good}
	f, resolved := openFirstWritableLog(candidates)
	if f == nil {
		t.Fatal("expected a writable file, got nil")
	}
	defer f.Close()
	if resolved != good {
		t.Errorf("expected resolved=%q, got %q", good, resolved)
	}
	// Sanity: directory was created.
	if _, err := os.Stat(filepath.Dir(good)); err != nil {
		t.Errorf("log dir not created: %v", err)
	}
}

// TestOpenFirstWritableLogAllFailReturnsEmpty ensures we degrade gracefully to
// stderr-only mode when no path is usable, matching the "agent must never
// refuse to start because of logging" invariant.
func TestOpenFirstWritableLogAllFailReturnsEmpty(t *testing.T) {
	candidates := []string{string([]byte{0})}
	f, resolved := openFirstWritableLog(candidates)
	if f != nil {
		f.Close()
		t.Fatal("expected nil file for impossible path")
	}
	if resolved != "" {
		t.Errorf("expected empty resolved, got %q", resolved)
	}
}
