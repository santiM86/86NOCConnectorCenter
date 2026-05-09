//go:build !windows

package main

import "syscall"

const (
	sigTerm = syscall.SIGTERM
	sigKill = syscall.SIGKILL
	sigZero = syscall.Signal(0)
)

func signalProcess(pid int, sig syscall.Signal) error {
	return syscall.Kill(pid, sig)
}
