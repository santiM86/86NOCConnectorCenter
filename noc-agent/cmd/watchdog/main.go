// 86NocWatchdog — companion process that supervises 86NocAgent.
//
// Why a separate binary: the agent runs many goroutines that talk to the
// network. If a syscall or library deadlocks, the agent process is alive
// but stuck — exactly the failure mode the legacy PowerShell connector
// suffered. The watchdog lives in its own address space and can never
// be deadlocked by the agent's bugs.
//
// What it does:
//  1. Reads the same agent.yaml to learn the heartbeat file path.
//  2. Every 15s, checks the mtime of that file.
//  3. If the file is older than cfg.Watchdog.StaleAfter, the watchdog
//     escalates: SIGTERM the agent process; if still stuck after 10s,
//     SIGKILL; finally re-exec the configured RestartCmd (defaults to
//     re-spawning the agent binary in the same directory).
package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/86bit/noc-agent/internal/config"
	"github.com/86bit/noc-agent/internal/logging"
)

var Version = "4.0.0-dev"

func main() {
	cfgPath := flag.String("config", "", "path to agent.yaml")
	pidFile := flag.String("pidfile", defaultPidFile(), "agent pid file")
	showVersion := flag.Bool("version", false, "print version and exit")
	flag.Parse()

	if *showVersion {
		fmt.Printf("86NocWatchdog %s (%s/%s)\n", Version, runtime.GOOS, runtime.GOARCH)
		return
	}

	log := logging.New().With("watchdog")
	cfg, err := config.Load(*cfgPath)
	if err != nil {
		log.Errorf("config: %v", err)
		os.Exit(2)
	}
	if !cfg.Watchdog.Enabled {
		log.Info("watchdog disabled in config — exiting")
		return
	}

	// On Windows, when launched by SCM, hand off to the service runner so
	// we respond to control messages. Otherwise run in foreground.
	if runIfService() {
		if err := runAsWindowsService(cfg, *pidFile, log); err != nil {
			log.Errorf("service runner: %v", err)
			os.Exit(3)
		}
		return
	}

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()
	runWatchdog(ctx, cfg, *pidFile)
}

func runWatchdog(ctx context.Context, cfg config.Config, pidFile string) {
	log := logging.New().With("watchdog")

	stale := cfg.Watchdog.StaleAfter
	if stale <= 0 {
		stale = 90 * time.Second
	}
	hbFile := cfg.Watchdog.HeartbeatFile

	log.Info("watchdog started", "heartbeat_file", hbFile, "stale_after", stale.String())

	t := time.NewTicker(15 * time.Second)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			if isStale(hbFile, stale) {
				log.Warn("agent heartbeat stale — restarting", "file", hbFile)
				restart(log, cfg, pidFile)
			}
		}
	}
}

func isStale(path string, after time.Duration) bool {
	st, err := os.Stat(path)
	if err != nil {
		return true // missing => stale
	}
	return time.Since(st.ModTime()) > after
}

func restart(log *logging.Logger, cfg config.Config, pidFile string) {
	if pid, ok := readPid(pidFile); ok {
		_ = signalProcess(pid, sigTerm)
		deadline := time.Now().Add(10 * time.Second)
		for time.Now().Before(deadline) {
			if !pidAlive(pid) {
				break
			}
			time.Sleep(500 * time.Millisecond)
		}
		if pidAlive(pid) {
			_ = signalProcess(pid, sigKill)
		}
	}

	args := cfg.Watchdog.RestartCmd
	if len(args) == 0 {
		// best-effort: re-exec a sibling "nocagent" binary
		exe, _ := os.Executable()
		dir := filepath.Dir(exe)
		bin := filepath.Join(dir, "nocagent")
		if runtime.GOOS == "windows" {
			bin += ".exe"
		}
		args = []string{bin}
	}
	cmd := exec.Command(args[0], args[1:]...) //nolint:gosec
	cmd.Stdout, cmd.Stderr = os.Stdout, os.Stderr
	if err := cmd.Start(); err != nil {
		log.Errorf("restart failed: %v", err)
		return
	}
	log.Info("agent restarted", "pid", strconv.Itoa(cmd.Process.Pid))
}

func readPid(path string) (int, bool) {
	b, err := os.ReadFile(path)
	if err != nil {
		return 0, false
	}
	n, err := strconv.Atoi(strings.TrimSpace(string(b)))
	if err != nil || n <= 0 {
		return 0, false
	}
	return n, true
}

func pidAlive(pid int) bool {
	return signalProcess(pid, sigZero) == nil
}

func defaultPidFile() string {
	if runtime.GOOS == "windows" {
		return filepath.Join(os.Getenv("ProgramData"), "86NocAgent", "agent.pid")
	}
	return "/var/run/86nocagent.pid"
}
