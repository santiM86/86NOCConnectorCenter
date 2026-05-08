//go:build windows

package main

import (
	"os"
	"syscall"
)

// On Windows we don't have POSIX signals; we use os.Process.Kill which
// terminates abruptly. signal_zero == FindProcess success heuristic.
const (
	sigTerm = syscall.Signal(15)
	sigKill = syscall.Signal(9)
	sigZero = syscall.Signal(0)
)

func signalProcess(pid int, sig syscall.Signal) error {
	p, err := os.FindProcess(pid)
	if err != nil {
		return err
	}
	if sig == sigZero {
		// On Windows, FindProcess always succeeds; probe with a no-op kill
		// of a sentinel value would lie. Use a low-level OpenProcess query
		// elsewhere if precision matters; for the watchdog mtime is the
		// real signal, this is just escalation.
		return nil
	}
	return p.Kill()
}
