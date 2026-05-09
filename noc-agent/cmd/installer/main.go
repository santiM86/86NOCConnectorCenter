// 86NocInstall — native Go installer for 86NocAgent v4.
//
//go:build windows

// Single-binary Windows installer that replaces the legacy .vbs/.ps1 chain.
// Why a separate Go binary instead of PowerShell scripts:
//   - Antivirus (CrowdStrike, SentinelOne, ESET, Sophos) flag .vbs / elevated
//     PowerShell scripts as default. A signed-or-unsigned plain .exe is
//     treated much more permissively.
//   - One file, no execution policy quirks, no hidden console windows.
//   - Same code path as the agent (Go) → easier to maintain.
//
// Behaviour:
//   1. Auto-elevate via ShellExecute(verb="runas") if not running as admin.
//   2. Show a Win32 MessageBox confirming what will be installed.
//   3. Read --token + --backend from CLI flags. If missing, look for a sidecar
//      file "nocinstall.cfg" next to the .exe (so the technician can just
//      double-click after dropping the cfg in the same folder).
//   4. Open a console window with progress; perform manifest fetch, binary
//      download, agent.yaml write, sc.exe service creation with Recovery,
//      service start.
//   5. Final MessageBox: success → "Open NOC Center?", fail → error details.
//
// This binary is built only for windows/amd64.
package main

import (
	"crypto/sha256"
	"crypto/tls"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
	"unsafe"

	"golang.org/x/sys/windows"
)

var Version = "4.0.0"

const (
	platform     = "windows-amd64"
	serviceName  = "86NocAgent"
	watchdogName = "86NocWatchdog"
)

type cliCfg struct {
	token   string
	backend string
	silent  bool
}

type manifest struct {
	ClientID       string            `json:"client_id"`
	Role           string            `json:"role"`
	BackendWS      string            `json:"backend_ws"`
	Binaries       map[string]string `json:"binaries"`
	SHA256         map[string]string `json:"sha256"`
	ConfigTemplate string            `json:"config_template"`
}

func main() {
	cfg := parseFlags()

	if !isElevated() {
		if err := relaunchAsAdmin(); err != nil {
			messageBoxError("Auto-elevazione fallita", err.Error())
			os.Exit(1)
		}
		os.Exit(0)
	}

	// Defer fatal exits so the console window stays open with the error.
	defer func() {
		if r := recover(); r != nil {
			messageBoxError("86NocAgent Installer - Errore fatale", fmt.Sprintf("%v", r))
			os.Exit(2)
		}
	}()

	if cfg.token == "" || cfg.backend == "" {
		if t, b, ok := readSidecar(); ok {
			cfg.token, cfg.backend = t, b
		}
	}
	if cfg.token == "" || cfg.backend == "" {
		messageBoxError("Configurazione mancante",
			"Esegui con:  nocinstall.exe --token <TOKEN> --backend <URL>\n\n"+
				"Oppure crea un file 'nocinstall.cfg' nella stessa cartella, contenente:\n"+
				"  TOKEN=...\n  BACKEND=https://argus.86bit.it")
		os.Exit(1)
	}

	if !cfg.silent {
		ok := messageBoxYesNo("86NocAgent Installer v"+Version,
			fmt.Sprintf(
				"Verra' installato 86NocAgent v%s su questo computer.\n\n"+
					"Backend: %s\n"+
					"Cartella: %s\n\n"+
					"Verranno creati 2 servizi Windows (auto-start + Service Recovery):\n"+
					"  - 86NocAgent\n  - 86NocWatchdog\n\n"+
					"Procedere con l'installazione?",
				Version, cfg.backend, installDir(),
			))
		if !ok {
			os.Exit(0)
		}
	}

	enableConsoleColors()
	step("[1/8] Lettura manifest installazione")
	man, err := fetchManifest(cfg)
	if err != nil {
		fail("manifest:", err)
	}
	okf("       cliente: %s", man.ClientID)

	step("[2/8] Stop servizi precedenti (se presenti)")
	for _, s := range []string{watchdogName, serviceName} {
		_ = run("sc.exe", "stop", s)
		time.Sleep(500 * time.Millisecond)
		_ = run("sc.exe", "delete", s)
	}

	step("[3/8] Creazione directory")
	if err := os.MkdirAll(installDir(), 0o755); err != nil {
		fail("mkdir install:", err)
	}
	if err := os.MkdirAll(dataDir(), 0o755); err != nil {
		fail("mkdir data:", err)
	}

	step("[4/8] Download nocagent.exe")
	if err := downloadFile(cfg, "nocagent.exe", filepath.Join(installDir(), "nocagent.exe"), man.SHA256["nocagent.exe"]); err != nil {
		fail("download nocagent:", err)
	}

	step("[5/8] Download nocwatchdog.exe")
	if err := downloadFile(cfg, "nocwatchdog.exe", filepath.Join(installDir(), "nocwatchdog.exe"), man.SHA256["nocwatchdog.exe"]); err != nil {
		fail("download nocwatchdog:", err)
	}

	step("[6/8] Scrittura agent.yaml")
	if err := os.WriteFile(configPath(), []byte(man.ConfigTemplate), 0o644); err != nil {
		fail("write yaml:", err)
	}

	// Scrivi anche agent-ui.json: la GUI nativa nocagent-ui.exe lo legge
	// per sapere client_id/role/backend_url da mostrare e per fare le
	// chiamate alle API self/health, self/snmp/test.
	uiCfg := map[string]any{
		"backend_url": cfg.backend,
		"client_id":   man.ClientID,
		"token":       cfg.token,
		"role":        man.Role,
		"install_dir": installDir(),
		"config_path": configPath(),
		"version":     "4.0.0",
	}
	if buf, err := json.MarshalIndent(uiCfg, "", "  "); err == nil {
		_ = os.WriteFile(filepath.Join(installDir(), "agent-ui.json"), buf, 0o644)
		_ = os.WriteFile(filepath.Join(dataDir(), "agent-ui.json"), buf, 0o644)
	}
	// Scarica anche argus.ico per avere icone consistenti negli shortcut
	// e nelle finestre della UI.
	icoURL := strings.TrimRight(cfg.backend, "/") + "/api/agent/install/argus.ico"
	if resp, err := httpClient.Get(icoURL); err == nil {
		defer resp.Body.Close()
		if resp.StatusCode == http.StatusOK {
			if out, err := os.Create(filepath.Join(installDir(), "argus.ico")); err == nil {
				_, _ = io.Copy(out, resp.Body)
				out.Close()
			}
		}
	}

	step("[7/8] Registrazione servizi Windows")
	if err := registerService(serviceName, "86bit NOC Agent",
		filepath.Join(installDir(), "nocagent.exe"), ""); err != nil {
		fail("create service agent:", err)
	}
	if err := registerService(watchdogName, "86bit NOC Watchdog",
		filepath.Join(installDir(), "nocwatchdog.exe"), serviceName); err != nil {
		fail("create service watchdog:", err)
	}

	step("[8/8] Avvio servizi")
	if err := run("sc.exe", "start", serviceName); err != nil {
		warnf("avvio %s: %v", serviceName, err)
	}
	time.Sleep(2 * time.Second)
	if err := run("sc.exe", "start", watchdogName); err != nil {
		warnf("avvio %s: %v", watchdogName, err)
	}
	time.Sleep(2 * time.Second)

	agStatus := serviceStatus(serviceName)
	wdStatus := serviceStatus(watchdogName)
	fmt.Println()
	fmt.Printf("       %s    : %s\n", serviceName, agStatus)
	fmt.Printf("       %s : %s\n", watchdogName, wdStatus)

	if agStatus == "RUNNING" && wdStatus == "RUNNING" {
		okf("\nInstallazione completata con successo.")
		if !cfg.silent {
			messageBoxInfo("86NocAgent Installer",
				fmt.Sprintf(
					"Installazione completata.\n\n"+
						"Cliente: %s\n"+
						"Backend: %s\n\n"+
						"Verifica nel NOC Center che l'agent risulti 'live'.",
					man.ClientID, cfg.backend,
				))
		}
		os.Exit(0)
	}
	failf("uno o piu' servizi non sono in stato Running")
}

// ---- CLI -------------------------------------------------------------------

func parseFlags() cliCfg {
	t := flag.String("token", "", "agent token (registered via /api/agents/register)")
	b := flag.String("backend", "", "backend HTTPS URL, es: https://argus.86bit.it")
	s := flag.Bool("silent", false, "no MessageBox dialogs")
	v := flag.Bool("version", false, "print version and exit")
	flag.Parse()
	if *v {
		fmt.Printf("86NocInstall %s (windows/amd64)\n", Version)
		os.Exit(0)
	}
	return cliCfg{token: strings.TrimSpace(*t), backend: strings.TrimRight(strings.TrimSpace(*b), "/"), silent: *s}
}

func readSidecar() (string, string, bool) {
	exe, err := os.Executable()
	if err != nil {
		return "", "", false
	}
	cfg := filepath.Join(filepath.Dir(exe), "nocinstall.cfg")
	data, err := os.ReadFile(cfg)
	if err != nil {
		return "", "", false
	}
	var token, backend string
	for _, line := range strings.Split(string(data), "\n") {
		line = strings.TrimSpace(line)
		k, v, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		switch strings.ToUpper(strings.TrimSpace(k)) {
		case "TOKEN":
			token = strings.TrimSpace(v)
		case "BACKEND":
			backend = strings.TrimRight(strings.TrimSpace(v), "/")
		}
	}
	return token, backend, token != "" && backend != ""
}

// ---- Network ----------------------------------------------------------------

var httpClient = &http.Client{
	Timeout: 120 * time.Second,
	Transport: &http.Transport{
		TLSClientConfig: &tls.Config{MinVersion: tls.VersionTLS12},
	},
}

func fetchManifest(c cliCfg) (*manifest, error) {
	url := fmt.Sprintf("%s/api/agent/install/manifest?platform=%s&token=%s", c.backend, platform, c.token)
	resp, err := httpClient.Get(url)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(body))
	}
	var m manifest
	if err := json.NewDecoder(resp.Body).Decode(&m); err != nil {
		return nil, err
	}
	return &m, nil
}

func downloadFile(c cliCfg, name, dst, expectedSHA string) error {
	url := fmt.Sprintf("%s/api/agent/binary/%s/%s?token=%s", c.backend, platform, name, c.token)
	resp, err := httpClient.Get(url)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("HTTP %d", resp.StatusCode)
	}
	tmp := dst + ".tmp"
	f, err := os.Create(tmp)
	if err != nil {
		return err
	}
	hasher := sha256.New()
	if _, err := io.Copy(io.MultiWriter(f, hasher), resp.Body); err != nil {
		f.Close()
		os.Remove(tmp)
		return err
	}
	f.Close()
	if expectedSHA != "" {
		got := hex.EncodeToString(hasher.Sum(nil))
		if !strings.EqualFold(got, expectedSHA) {
			os.Remove(tmp)
			return fmt.Errorf("sha256 mismatch (expected %s, got %s)", expectedSHA, got)
		}
	}
	if err := os.Rename(tmp, dst); err != nil {
		os.Remove(tmp)
		return err
	}
	return nil
}

// ---- Service registration ---------------------------------------------------

func registerService(name, displayName, binPath, depend string) error {
	bin := fmt.Sprintf(`"%s" --config "%s"`, binPath, configPath())
	args := []string{"create", name, "binPath=", bin, "start=", "auto", "DisplayName=", displayName}
	if depend != "" {
		args = append(args, "depend=", depend)
	}
	if err := run("sc.exe", args...); err != nil {
		return err
	}
	_ = run("sc.exe", "description", name, "Native NOC monitoring agent for the 86bit platform.")
	// Recovery: restart 5s, restart 5s, restart 15s, reset counter daily.
	_ = run("sc.exe", "failure", name, "reset=", "86400",
		"actions=", "restart/5000/restart/5000/restart/15000")
	return nil
}

func serviceStatus(name string) string {
	out, err := exec.Command("sc.exe", "query", name).CombinedOutput()
	if err != nil {
		return "ERROR"
	}
	for _, line := range strings.Split(string(out), "\n") {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "STATE") {
			parts := strings.Fields(line)
			if len(parts) >= 4 {
				return strings.ToUpper(parts[3])
			}
		}
	}
	return "UNKNOWN"
}

// ---- Win32 dialogs (no external deps, syscall only) ------------------------

const (
	mbOK             = 0x00000000
	mbYesNo          = 0x00000004
	mbIconError      = 0x00000010
	mbIconQuestion   = 0x00000020
	mbIconInfo       = 0x00000040
	idYes            = 6
	swShowNormal     = 1
)

func messageBox(title, text string, flags uint32) int {
	user32 := windows.NewLazySystemDLL("user32.dll")
	mb := user32.NewProc("MessageBoxW")
	titlePtr, _ := windows.UTF16PtrFromString(title)
	textPtr, _ := windows.UTF16PtrFromString(text)
	rc, _, _ := mb.Call(
		0,
		uintptr(unsafe.Pointer(textPtr)),
		uintptr(unsafe.Pointer(titlePtr)),
		uintptr(flags))
	return int(rc)
}

func messageBoxInfo(title, text string)   { messageBox(title, text, mbOK|mbIconInfo) }
func messageBoxError(title, text string)  { messageBox(title, text, mbOK|mbIconError) }
func messageBoxYesNo(title, text string) bool {
	return messageBox(title, text, mbYesNo|mbIconQuestion) == idYes
}

// ---- Auto-elevation ---------------------------------------------------------

func isElevated() bool {
	var sid *windows.SID
	err := windows.AllocateAndInitializeSid(
		&windows.SECURITY_NT_AUTHORITY,
		2,
		windows.SECURITY_BUILTIN_DOMAIN_RID,
		windows.DOMAIN_ALIAS_RID_ADMINS,
		0, 0, 0, 0, 0, 0, &sid)
	if err != nil {
		return false
	}
	defer windows.FreeSid(sid)
	token := windows.GetCurrentProcessToken()
	member, err := token.IsMember(sid)
	if err != nil {
		return false
	}
	return member
}

func relaunchAsAdmin() error {
	exe, err := os.Executable()
	if err != nil {
		return err
	}
	verb, _ := windows.UTF16PtrFromString("runas")
	exePtr, _ := windows.UTF16PtrFromString(exe)
	args := strings.Join(os.Args[1:], " ")
	argsPtr, _ := windows.UTF16PtrFromString(args)
	cwd, _ := os.Getwd()
	cwdPtr, _ := windows.UTF16PtrFromString(cwd)
	return windows.ShellExecute(0, verb, exePtr, argsPtr, cwdPtr, swShowNormal)
}

// ---- Console output --------------------------------------------------------

const (
	clrReset  = "\x1b[0m"
	clrCyan   = "\x1b[36m"
	clrGreen  = "\x1b[32m"
	clrRed    = "\x1b[31m"
	clrYellow = "\x1b[33m"
)

func enableConsoleColors() {
	// Windows 10 1607+ supports ANSI escape codes when this flag is set.
	const enableVT = 0x0004
	stdout := windows.Handle(os.Stdout.Fd())
	var mode uint32
	if windows.GetConsoleMode(stdout, &mode) == nil {
		_ = windows.SetConsoleMode(stdout, mode|enableVT)
	}
}

func step(msg string)                  { fmt.Println(clrCyan + msg + clrReset) }
func okf(format string, a ...any)      { fmt.Printf(clrGreen+format+clrReset+"\n", a...) }
func warnf(format string, a ...any)    { fmt.Printf(clrYellow+format+clrReset+"\n", a...) }
func failf(format string, a ...any)    {
	fmt.Printf(clrRed+"FATAL: "+format+clrReset+"\n", a...)
	messageBoxError("86NocAgent Installer - Errore", fmt.Sprintf(format, a...))
	os.Exit(2)
}
func fail(prefix string, err error)    { failf("%s %v", prefix, err) }

// ---- helpers ----------------------------------------------------------------

func installDir() string { return filepath.Join(os.Getenv("ProgramFiles"), "86NocAgent") }
func dataDir() string    { return filepath.Join(os.Getenv("ProgramData"), "86NocAgent") }
func configPath() string { return filepath.Join(dataDir(), "agent.yaml") }

func run(name string, args ...string) error {
	cmd := exec.Command(name, args...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("%s %s: %v: %s", name, strings.Join(args, " "), err, strings.TrimSpace(string(out)))
	}
	return nil
}
