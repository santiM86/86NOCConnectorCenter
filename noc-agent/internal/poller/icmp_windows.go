//go:build windows

package poller

import (
	"os/exec"
	"syscall"
)

// hideWindow attaches SysProcAttr.HideWindow so the spawned ping.exe
// does not flash a console window when the agent runs interactively
// (it has no effect when running as a Windows service since the
// process is already non-interactive, but it's free safety).
func hideWindow(c *exec.Cmd) {
	if c.SysProcAttr == nil {
		c.SysProcAttr = &syscall.SysProcAttr{}
	}
	c.SysProcAttr.HideWindow = true
	// CREATE_NO_WINDOW = 0x08000000
	c.SysProcAttr.CreationFlags |= 0x08000000
}
