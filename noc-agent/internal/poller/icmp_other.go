//go:build !windows

package poller

import "os/exec"

// hideWindow is a no-op on non-Windows platforms. The Windows version
// (icmp_windows.go) sets the appropriate SysProcAttr to keep the cmd
// window from popping up when the agent runs as a desktop service.
func hideWindow(_ *exec.Cmd) {}
