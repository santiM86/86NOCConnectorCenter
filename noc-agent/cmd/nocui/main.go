// 86BIT Argus Connector — native Windows GUI single-binary.
//
// Zero PowerShell, zero DOS console, single instance, sempre vivo
// (esce solo da menu "Esci"). Tray icon + finestra "Gestisci Dispositivi"
// in un solo processo. Compilare con -H=windowsgui per non mostrare
// console DOS.
//
// Build:
//
//   GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build \
//     -trimpath -ldflags '-s -w -H=windowsgui' \
//     -o build/bin/windows-amd64/nocagent-ui.exe ./cmd/nocui
//
// Modes (from CLI flag -show=true|false):
//   default: avvia il processo tray (idempotente: se gia' attivo esce)
//   -show:   chiede all'istanza tray di mostrare la finestra Gestisci
//            Dispositivi. Se nessuna tray attiva, la avvia e poi mostra.
//
//go:build windows

package main

import (
	"bytes"
	"encoding/csv"
	"encoding/json"
	_ "embed"
	"flag"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
	"unsafe"

	"github.com/lxn/walk"
	wd "github.com/lxn/walk/declarative"
	"github.com/lxn/win"
)

//go:embed argus.ico
var argusIcoBytes []byte

// --- IPC tra istanze dello stesso EXE ---------------------------------------

const (
	// Senza prefix "Global\" perche' utenti normali NON hanno il privilegio
	// SE_CREATE_GLOBAL_NAME e CreateMutexW fallirebbe silenziosamente.
	// Senza prefix il mutex e' session-local, esattamente quello che vogliamo:
	// tray + secondo lancio dello shortcut girano nella stessa sessione utente.
	mutexName = "86BITArgusConnectorTray"
)

// File marker che la tray polla per sapere se un'altra istanza ha chiesto
// di mostrare la finestra "Gestisci Dispositivi". Usiamo %LOCALAPPDATA%
// (sempre user-writable, identico tra Scheduled Task e shortcut nella stessa
// sessione) invece di %TEMP% che puo' divergere.
func ipcShowFlagPath() string {
	base := os.Getenv("LOCALAPPDATA")
	if base == "" {
		base = os.TempDir()
	}
	dir := filepath.Join(base, "86NocAgent")
	_ = os.MkdirAll(dir, 0o755)
	return filepath.Join(dir, "show.flag")
}

func acquireSingleInstance() (release func(), alreadyRunning bool) {
	name, _ := syscall.UTF16PtrFromString(mutexName)
	h, _ := windowsCreateMutexW(0, false, name)
	if h == 0 {
		return func() {}, false
	}
	if windowsGetLastError() == 183 /* ERROR_ALREADY_EXISTS */ {
		windowsCloseHandle(h)
		return func() {}, true
	}
	return func() { windowsReleaseMutex(h); windowsCloseHandle(h) }, false
}

// minimal Win32 wrappers (avoid pulling in extra packages)
var (
	modKernel32        = syscall.NewLazyDLL("kernel32.dll")
	procCreateMutexW   = modKernel32.NewProc("CreateMutexW")
	procReleaseMutex   = modKernel32.NewProc("ReleaseMutex")
	procCloseHandle    = modKernel32.NewProc("CloseHandle")
	procGetLastError   = modKernel32.NewProc("GetLastError")
)

func windowsCreateMutexW(sa uintptr, initialOwner bool, name *uint16) (uintptr, error) {
	io := uintptr(0)
	if initialOwner {
		io = 1
	}
	r, _, err := procCreateMutexW.Call(sa, io, uintptr(unsafe.Pointer(name)))
	if r == 0 {
		return 0, err
	}
	return r, nil
}
func windowsReleaseMutex(h uintptr) { procReleaseMutex.Call(h) }
func windowsCloseHandle(h uintptr)  { procCloseHandle.Call(h) }
func windowsGetLastError() uintptr {
	r, _, _ := procGetLastError.Call()
	return r
}

// --- Config persistente -----------------------------------------------------

type AgentInfo struct {
	BackendURL  string `json:"backend_url"`
	ClientID    string `json:"client_id"`
	Token       string `json:"token"`
	Role        string `json:"role"`
	InstallDir  string `json:"install_dir"`
	ConfigPath  string `json:"config_path"`
	Version     string `json:"version"`
}

func loadAgentInfo() AgentInfo {
	// agent-ui.json viene scritto dall'installer accanto al binario
	exe, _ := os.Executable()
	dir := filepath.Dir(exe)
	for _, p := range []string{
		filepath.Join(dir, "agent-ui.json"),
		filepath.Join(os.Getenv("ProgramData"), "86NocAgent", "agent-ui.json"),
	} {
		if b, err := os.ReadFile(p); err == nil {
			var a AgentInfo
			if json.Unmarshal(b, &a) == nil {
				if a.InstallDir == "" {
					a.InstallDir = dir
				}
				if a.ConfigPath == "" {
					a.ConfigPath = filepath.Join(os.Getenv("ProgramData"), "86NocAgent", "agent.yaml")
				}
				return a
			}
		}
	}
	// Fallback (dev/test)
	return AgentInfo{
		BackendURL: "https://snmp-hub-noc.preview.emergentagent.com",
		ClientID:   "unknown",
		Token:      "",
		Role:       "master",
		InstallDir: dir,
		ConfigPath: filepath.Join(os.Getenv("ProgramData"), "86NocAgent", "agent.yaml"),
		Version:    "4.0.0",
	}
}

// --- SNMP target model ------------------------------------------------------

type Target struct {
	IP          string
	Name        string
	Community   string
	DeviceType  string
	SNMPVersion string
	SNMPPort    int
	WebUI       string
}

const (
	beginMarker = "# === BEGIN MANAGED TARGETS ==="
	endMarker   = "# === END MANAGED TARGETS ==="
)

func parseTargets(yaml string) []*Target {
	var out []*Target
	in := false
	var cur *Target
	for _, line := range strings.Split(yaml, "\n") {
		ln := strings.TrimRight(line, "\r")
		ts := strings.TrimSpace(ln)
		if strings.HasPrefix(ts, beginMarker) {
			in = true
			continue
		}
		if strings.HasPrefix(ts, endMarker) {
			if cur != nil {
				out = append(out, cur)
				cur = nil
			}
			in = false
			continue
		}
		if !in {
			continue
		}
		if strings.HasPrefix(ts, "- ip:") {
			if cur != nil {
				out = append(out, cur)
			}
			cur = &Target{IP: stripQuotes(strings.TrimSpace(strings.TrimPrefix(ts, "- ip:"))), Community: "public", SNMPVersion: "v2c", SNMPPort: 161}
			continue
		}
		if cur == nil {
			continue
		}
		if v, ok := matchKV(ts, "name:"); ok {
			cur.Name = v
		} else if v, ok := matchKV(ts, "community:"); ok {
			cur.Community = v
		} else if v, ok := matchKV(ts, "profile:"); ok {
			cur.DeviceType = v
		} else if v, ok := matchKV(ts, "snmp_version:"); ok {
			cur.SNMPVersion = v
		} else if v, ok := matchKV(ts, "snmp_port:"); ok {
			if p, err := strconv.Atoi(v); err == nil {
				cur.SNMPPort = p
			}
		}
	}
	if cur != nil {
		out = append(out, cur)
	}
	return out
}

func matchKV(line, key string) (string, bool) {
	if !strings.HasPrefix(line, key) {
		return "", false
	}
	return stripQuotes(strings.TrimSpace(strings.TrimPrefix(line, key))), true
}
func stripQuotes(s string) string {
	s = strings.TrimSpace(s)
	if len(s) >= 2 && s[0] == '"' && s[len(s)-1] == '"' {
		return s[1 : len(s)-1]
	}
	return s
}

func writeTargets(configPath string, targets []*Target) error {
	raw, err := os.ReadFile(configPath)
	if err != nil {
		return err
	}
	src := string(raw)
	// rimuovi blocco esistente
	if i := strings.Index(src, beginMarker); i >= 0 {
		if j := strings.Index(src[i:], endMarker); j >= 0 {
			end := i + j + len(endMarker)
			// inghiotti newline finale
			if end < len(src) && (src[end] == '\r' || src[end] == '\n') {
				end++
				if end < len(src) && src[end] == '\n' {
					end++
				}
			}
			src = src[:i] + src[end:]
		}
	}
	src = strings.TrimRight(src, "\r\n")

	var b bytes.Buffer
	b.WriteString(src)
	b.WriteString("\r\n")
	b.WriteString(beginMarker)
	b.WriteString("\r\n# Gestito da Argus Connector - non modificare a mano\r\n")
	b.WriteString("snmp_targets:\r\n")
	for _, t := range targets {
		fmt.Fprintf(&b, "  - ip: %q\r\n", t.IP)
		if t.Name != "" {
			fmt.Fprintf(&b, "    name: %q\r\n", t.Name)
		}
		if t.Community != "" {
			fmt.Fprintf(&b, "    community: %q\r\n", t.Community)
		}
		if t.DeviceType != "" {
			fmt.Fprintf(&b, "    profile: %q\r\n", t.DeviceType)
		}
		if t.SNMPVersion != "" {
			fmt.Fprintf(&b, "    snmp_version: %q\r\n", t.SNMPVersion)
		}
		if t.SNMPPort != 0 && t.SNMPPort != 161 {
			fmt.Fprintf(&b, "    snmp_port: %d\r\n", t.SNMPPort)
		}
	}
	b.WriteString(endMarker)
	b.WriteString("\r\n")
	return os.WriteFile(configPath, b.Bytes(), 0o644)
}

// runHidden esegue un comando Windows senza mostrare la console parent.
// Usalo per qualsiasi exec.Command verso CLI tools (sc.exe, ping, rundll32,
// ecc.). La finestra "vera" del processo target (es. browser) viene
// comunque mostrata se il programma la apre.
func runHidden(name string, args ...string) error {
	cmd := exec.Command(name, args...)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	return cmd.Start()
}

// --- Service control --------------------------------------------------------

func runSC(args ...string) error {
	cmd := exec.Command("sc.exe", args...)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	return cmd.Run()
}
func startServices() {
	runSC("start", "86NocAgent")
	runSC("start", "86NocWatchdog")
}
func stopServices() {
	runSC("stop", "86NocWatchdog")
	runSC("stop", "86NocAgent")
}
func restartServices() {
	stopServices()
	time.Sleep(800 * time.Millisecond)
	startServices()
}

func serviceStatus(name string) string {
	cmd := exec.Command("sc.exe", "query", name)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	out, err := cmd.Output()
	if err != nil {
		return "unknown"
	}
	s := string(out)
	switch {
	case strings.Contains(s, "RUNNING"):
		return "Running"
	case strings.Contains(s, "STOPPED"):
		return "Stopped"
	case strings.Contains(s, "START_PENDING"):
		return "Starting"
	case strings.Contains(s, "STOP_PENDING"):
		return "Stopping"
	}
	return "Unknown"
}

// --- HTTP helpers -----------------------------------------------------------

func backendPost(path string, agent AgentInfo, body any, out any) error {
	u := strings.TrimRight(agent.BackendURL, "/") + path + "?token=" + url.QueryEscape(agent.Token)
	var rd *bytes.Reader
	if body != nil {
		j, _ := json.Marshal(body)
		rd = bytes.NewReader(j)
	} else {
		rd = bytes.NewReader(nil)
	}
	req, err := http.NewRequest("POST", u, rd)
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	cli := &http.Client{Timeout: 30 * time.Second}
	resp, err := cli.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		var b bytes.Buffer
		b.ReadFrom(resp.Body)
		return fmt.Errorf("http %d: %s", resp.StatusCode, b.String())
	}
	if out != nil {
		return json.NewDecoder(resp.Body).Decode(out)
	}
	return nil
}

func backendGet(path string, agent AgentInfo, out any) error {
	u := strings.TrimRight(agent.BackendURL, "/") + path + "?token=" + url.QueryEscape(agent.Token)
	cli := &http.Client{Timeout: 15 * time.Second}
	resp, err := cli.Get(u)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		var b bytes.Buffer
		b.ReadFrom(resp.Body)
		return fmt.Errorf("http %d: %s", resp.StatusCode, b.String())
	}
	if out != nil {
		return json.NewDecoder(resp.Body).Decode(out)
	}
	return nil
}

type snmpReply struct {
	AgentID string `json:"agent_id"`
	Reply   struct {
		OK     bool   `json:"ok"`
		Error  string `json:"error"`
		Result struct {
			Reachable    bool    `json:"reachable"`
			SysName      string  `json:"sys_name"`
			SysDescr     string  `json:"sys_descr"`
			SysObjectID  string  `json:"sys_object_id"`
			UptimeNs     int64   `json:"uptime_ns"`
			LatencyNs    int64   `json:"latency_ns"`
			ErrMsg       string  `json:"error"`
		} `json:"result"`
	} `json:"reply"`
}

type healthReply struct {
	Connected     bool    `json:"connected"`
	ClientID      string  `json:"client_id"`
	AgentID       string  `json:"agent_id"`
	AgentsOnline  int     `json:"agents_online"`
	RTT           float64 `json:"rtt_ms"`
	Hostname      string  `json:"hostname"`
	AgentVersion  string  `json:"agent_version"`
	Detail        string  `json:"detail"`
}

// --- App globals ------------------------------------------------------------

type App struct {
	agent      AgentInfo
	mw         *walk.MainWindow
	hiddenMw   *walk.MainWindow
	tray       *walk.NotifyIcon
	icon       *walk.Icon
	tableModel *targetTableModel
	statusItem *walk.Action
	healthItem *walk.Action
	mu         sync.Mutex
}

var theApp *App

// --- Table model ------------------------------------------------------------

type targetTableModel struct {
	walk.TableModelBase
	items []*Target
}

func (m *targetTableModel) RowCount() int { return len(m.items) }
func (m *targetTableModel) Value(row, col int) interface{} {
	if row < 0 || row >= len(m.items) {
		return ""
	}
	t := m.items[row]
	switch col {
	case 0:
		return t.IP
	case 1:
		return t.Community
	case 2:
		return t.Name
	case 3:
		return t.WebUI
	}
	return ""
}
func (m *targetTableModel) PublishRowsReset() { m.PublishRowsChanged(0, len(m.items)) }

// --- Console window ---------------------------------------------------------

func showConsoleWindow() {
	defer func() {
		if r := recover(); r != nil {
			logf("PANIC in showConsoleWindow: %v", r)
		}
	}()
	if theApp == nil {
		return
	}
	if theApp.mw != nil {
		// gia' creata: mostrala
		mw := theApp.mw
		theApp.hiddenMw.Synchronize(func() {
			win.ShowWindow(mw.Handle(), win.SW_SHOW)
			win.SetForegroundWindow(mw.Handle())
		})
		return
	}
	logf("building console window...")
	go buildConsole(theApp)
}

func buildConsole(app *App) {
	defer func() {
		if r := recover(); r != nil {
			logf("PANIC in buildConsole: %v", r)
		}
	}()
	cfg, _ := os.ReadFile(app.agent.ConfigPath)
	app.tableModel = &targetTableModel{items: parseTargets(string(cfg))}
	logf("buildConsole: parsed %d targets from %s", len(app.tableModel.items), app.agent.ConfigPath)

	var (
		mw       *walk.MainWindow
		ipEd     *walk.LineEdit
		cmEd     *walk.LineEdit
		nameEd   *walk.LineEdit
		tv       *walk.TableView
		statusLb *walk.Label
		healthLb *walk.Label
	)

	addTarget := func() {
		ip := strings.TrimSpace(ipEd.Text())
		if ip == "" {
			return
		}
		c := strings.TrimSpace(cmEd.Text())
		if c == "" {
			c = "public"
		}
		app.tableModel.items = append(app.tableModel.items, &Target{
			IP: ip, Name: strings.TrimSpace(nameEd.Text()),
			Community: c, SNMPVersion: "v2c", SNMPPort: 161,
		})
		app.tableModel.PublishRowsReset()
		ipEd.SetText("")
		nameEd.SetText("")
		ipEd.SetFocus()
	}

	wd.MainWindow{
		AssignTo: &mw,
		Title:    "ARGUS Connector - Gestisci Dispositivi",
		Size:     wd.Size{Width: 920, Height: 700},
		MinSize:  wd.Size{Width: 800, Height: 600},
		Icon:     app.icon,
		Layout:   wd.VBox{MarginsZero: false},
		Children: []wd.Widget{
			wd.Label{Text: "Dispositivi Monitorati (SNMP Polling)", Font: wd.Font{Family: "Segoe UI", PointSize: 14, Bold: true}},
			wd.Label{Text: fmt.Sprintf("Cliente: %s · Ruolo: %s · Backend: %s", app.agent.ClientID, app.agent.Role, app.agent.BackendURL), TextColor: walk.RGB(110, 110, 125)},
			wd.Composite{
				Layout: wd.HBox{},
				Children: []wd.Widget{
					wd.GroupBox{
						Title:  "Aggiungi dispositivo",
						Layout: wd.HBox{},
						Children: []wd.Widget{
							wd.Label{Text: "IP:"},
							wd.LineEdit{AssignTo: &ipEd, MinSize: wd.Size{Width: 130}},
							wd.Label{Text: "Community:"},
							wd.LineEdit{AssignTo: &cmEd, Text: "public", MinSize: wd.Size{Width: 100}},
							wd.Label{Text: "Nome:"},
							wd.LineEdit{AssignTo: &nameEd, MinSize: wd.Size{Width: 200}},
							wd.PushButton{Text: "+ Aggiungi", OnClicked: addTarget},
						},
					},
				},
			},
			wd.TableView{
				AssignTo:         &tv,
				AlternatingRowBG: true,
				ColumnsOrderable: true,
				MultiSelection:   true,
				Columns: []wd.TableViewColumn{
					{Title: "IP Address", Width: 150},
					{Title: "Community", Width: 110},
					{Title: "Nome", Width: 280},
					{Title: "Web UI", Width: 280},
				},
				Model: app.tableModel,
			},
			wd.Composite{
				Layout: wd.HBox{},
				Children: []wd.Widget{
					wd.PushButton{Text: "Esporta CSV", OnClicked: func() {
						dlg := walk.FileDialog{Title: "Esporta CSV", Filter: "CSV (*.csv)|*.csv", FilePath: "argus-targets.csv"}
						if ok, _ := dlg.ShowSave(mw); !ok {
							return
						}
						f, err := os.Create(dlg.FilePath)
						if err != nil {
							walk.MsgBox(mw, "Errore", err.Error(), walk.MsgBoxIconError)
							return
						}
						defer f.Close()
						w := csv.NewWriter(f)
						w.Write([]string{"ip", "name", "community", "device_type", "snmp_version", "snmp_port"})
						for _, t := range app.tableModel.items {
							w.Write([]string{t.IP, t.Name, t.Community, t.DeviceType, t.SNMPVersion, strconv.Itoa(t.SNMPPort)})
						}
						w.Flush()
					}},
					wd.PushButton{Text: "Importa CSV", OnClicked: func() {
						dlg := walk.FileDialog{Title: "Importa CSV", Filter: "CSV (*.csv)|*.csv"}
						if ok, _ := dlg.ShowOpen(mw); !ok {
							return
						}
						f, err := os.Open(dlg.FilePath)
						if err != nil {
							walk.MsgBox(mw, "Errore", err.Error(), walk.MsgBoxIconError)
							return
						}
						defer f.Close()
						r := csv.NewReader(f)
						r.FieldsPerRecord = -1
						rows, err := r.ReadAll()
						if err != nil {
							walk.MsgBox(mw, "Errore CSV", err.Error(), walk.MsgBoxIconError)
							return
						}
						if len(rows) == 0 {
							return
						}
						hdr := map[string]int{}
						for i, h := range rows[0] {
							hdr[strings.ToLower(strings.TrimSpace(h))] = i
						}
						added := 0
						for _, row := range rows[1:] {
							get := func(k string) string {
								if i, ok := hdr[k]; ok && i < len(row) {
									return strings.TrimSpace(row[i])
								}
								return ""
							}
							ip := get("ip")
							if ip == "" {
								continue
							}
							p, _ := strconv.Atoi(get("snmp_port"))
							if p == 0 {
								p = 161
							}
							c := get("community")
							if c == "" {
								c = "public"
							}
							v := get("snmp_version")
							if v == "" {
								v = "v2c"
							}
							app.tableModel.items = append(app.tableModel.items, &Target{
								IP: ip, Name: get("name"), Community: c,
								DeviceType: get("device_type"), SNMPVersion: v, SNMPPort: p,
							})
							added++
						}
						app.tableModel.PublishRowsReset()
						walk.MsgBox(mw, "Import", fmt.Sprintf("Importati %d dispositivi.", added), walk.MsgBoxIconInformation)
					}},
					wd.HSpacer{},
					wd.PushButton{Text: "Stato canale (VPN/WS)", OnClicked: func() {
						healthLb.SetText("● Verifica canale in corso...")
						go func() {
							var hr healthReply
							err := backendGet("/api/agent/self/health", app.agent, &hr)
							mw.Synchronize(func() {
								if err != nil {
									healthLb.SetText("● Errore: " + err.Error())
									return
								}
								if hr.Connected {
									healthLb.SetText(fmt.Sprintf("● Canale OK · RTT %.0f ms · host %s · agents online: %d", hr.RTT, hr.Hostname, hr.AgentsOnline))
								} else {
									healthLb.SetText("● Agent NON connesso al NOC Center: " + hr.Detail)
								}
							})
						}()
					}},
				},
			},
			wd.Composite{
				Layout: wd.HBox{},
				Children: []wd.Widget{
					wd.PushButton{Text: "Rimuovi selezionato", OnClicked: func() {
						sel := tv.SelectedIndexes()
						if len(sel) == 0 {
							return
						}
						sm := map[int]bool{}
						for _, i := range sel {
							sm[i] = true
						}
						kept := app.tableModel.items[:0]
						for i, t := range app.tableModel.items {
							if !sm[i] {
								kept = append(kept, t)
							}
						}
						app.tableModel.items = kept
						app.tableModel.PublishRowsReset()
					}},
					wd.PushButton{Text: "Test SNMP", OnClicked: func() {
						sel := tv.SelectedIndexes()
						if len(sel) == 0 {
							walk.MsgBox(mw, "Test SNMP", "Seleziona prima un dispositivo.", walk.MsgBoxIconInformation)
							return
						}
						t := app.tableModel.items[sel[0]]
						statusLb.SetText("Interrogazione SNMP " + t.IP + " in corso...")
						go func() {
							var sr snmpReply
							err := backendPost("/api/agent/self/snmp/test", app.agent, map[string]any{
								"ip": t.IP, "community": t.Community, "port": t.SNMPPort, "version": t.SNMPVersion,
							}, &sr)
							mw.Synchronize(func() {
								if err != nil {
									statusLb.SetText("Errore HTTP: " + err.Error())
									walk.MsgBox(mw, "Test SNMP", err.Error(), walk.MsgBoxIconError)
									return
								}
								if !sr.Reply.OK {
									statusLb.SetText("Test fallito: " + sr.Reply.Error)
									return
								}
								r := sr.Reply.Result
								reach := "NON RAGGIUNGIBILE"
								if r.Reachable {
									reach = "OK"
								}
								msg := fmt.Sprintf("IP: %s\nReachable: %s\n", t.IP, reach)
								if r.SysName != "" {
									msg += "sysName:     " + r.SysName + "\n"
								}
								if r.SysDescr != "" {
									msg += "sysDescr:    " + r.SysDescr + "\n"
								}
								if r.SysObjectID != "" {
									msg += "sysObjectID: " + r.SysObjectID + "\n"
								}
								if r.LatencyNs > 0 {
									msg += fmt.Sprintf("Latency:     %d ms\n", r.LatencyNs/1e6)
								}
								walk.MsgBox(mw, "Test SNMP via WS reale", msg, walk.MsgBoxIconInformation)
								statusLb.SetText(fmt.Sprintf("Test SNMP %s: %s · %s", t.IP, reach, r.SysName))
							})
						}()
					}},
					wd.PushButton{Text: "Apri Web UI", OnClicked: func() {
						sel := tv.SelectedIndexes()
						if len(sel) == 0 {
							return
						}
						t := app.tableModel.items[sel[0]]
						statusLb.SetText("Verifica Web UI di " + t.IP + " ...")
						// HTTP probe in goroutine: la net.Get puo' bloccare
						// fino a 4s e congelerebbe la UI se eseguita qui.
						go func(target *Target) {
							for _, sch := range []string{"https", "http"} {
								u := sch + "://" + target.IP + "/"
								resp, err := (&http.Client{Timeout: 2 * time.Second}).Get(u)
								if err == nil {
									resp.Body.Close()
									if resp.StatusCode < 500 {
										runHidden("rundll32", "url.dll,FileProtocolHandler", u)
										mw.Synchronize(func() {
											target.WebUI = u
											app.tableModel.PublishRowsReset()
											statusLb.SetText("Web UI aperta: " + u)
										})
										return
									}
								}
							}
							mw.Synchronize(func() {
								statusLb.SetText("Nessuna risposta HTTP/HTTPS da " + target.IP)
								walk.MsgBox(mw, "Web UI", "Nessuna risposta HTTP/HTTPS dal device.", walk.MsgBoxIconWarning)
							})
						}(t)
					}},
					wd.PushButton{Text: "Scansiona Rete", OnClicked: func() {
						go showScannerDialog(app, mw)
					}},
					wd.HSpacer{},
					wd.PushButton{Text: "Apri NOC Center", OnClicked: func() {
						runHidden("rundll32", "url.dll,FileProtocolHandler", app.agent.BackendURL)
					}},
					wd.PushButton{Text: "Salva e Riavvia", OnClicked: func() {
						if err := writeTargets(app.agent.ConfigPath, app.tableModel.items); err != nil {
							walk.MsgBox(mw, "Errore", err.Error(), walk.MsgBoxIconError)
							return
						}
						go func() {
							restartServices()
							mw.Synchronize(func() {
								walk.MsgBox(mw, "Salvato", fmt.Sprintf("Configurazione salvata, servizi riavviati.\nTotale: %d target.", len(app.tableModel.items)), walk.MsgBoxIconInformation)
							})
						}()
					}},
				},
			},
			wd.Label{AssignTo: &statusLb, Text: ""},
			wd.Label{AssignTo: &healthLb, Text: ""},
		},
	}.Create()

	app.mw = mw
	mw.Closing().Attach(func(canceled *bool, reason walk.CloseReason) {
		// Non terminare il processo: torna in tray
		mw.Hide()
		*canceled = true
	})
	mw.Show()
	mw.Run()
	app.mw = nil
}

// --- Tray icon --------------------------------------------------------------

func setupTray(app *App) error {
	mw, err := walk.NewMainWindow()
	if err != nil {
		return err
	}
	app.hiddenMw = mw

	ni, err := walk.NewNotifyIcon(mw)
	if err != nil {
		return err
	}
	if app.icon != nil {
		ni.SetIcon(app.icon)
	}
	ni.SetToolTip("86BIT Argus Connector")
	ni.SetVisible(true)
	app.tray = ni

	// Doppio-click sull'icona → apre Gestisci Dispositivi
	ni.MouseDown().Attach(func(x, y int, b walk.MouseButton) {
		if b == walk.LeftButton {
			showConsoleWindow()
		}
	})

	add := func(text string, fn func()) *walk.Action {
		a := walk.NewAction()
		a.SetText(text)
		if fn != nil {
			a.Triggered().Attach(fn)
		}
		ni.ContextMenu().Actions().Add(a)
		return a
	}
	add("Apri NOC Center", func() {
		exec.Command("rundll32", "url.dll,FileProtocolHandler", app.agent.BackendURL).Start()
	})
	add("Gestisci Dispositivi...", func() { showConsoleWindow() })
	ni.ContextMenu().Actions().Add(walk.NewSeparatorAction())

	app.statusItem = add("Stato: ...", nil)
	app.statusItem.SetEnabled(false)
	app.healthItem = add("Canale: ...", nil)
	app.healthItem.SetEnabled(false)
	ni.ContextMenu().Actions().Add(walk.NewSeparatorAction())
	add("Avvia servizi", func() { go func() { startServices(); refreshStatus(app) }() })
	add("Ferma servizi", func() { go func() { stopServices(); refreshStatus(app) }() })
	add("Riavvia servizi", func() { go func() { restartServices(); refreshStatus(app) }() })
	ni.ContextMenu().Actions().Add(walk.NewSeparatorAction())
	add("Apri cartella log", func() {
		dir := filepath.Join(os.Getenv("ProgramData"), "86NocAgent", "logs")
		os.MkdirAll(dir, 0o755)
		runHidden("explorer.exe", dir)
	})
	ni.ContextMenu().Actions().Add(walk.NewSeparatorAction())
	add("Esci", func() {
		ni.SetVisible(false)
		walk.App().Exit(0)
	})

	// Refresh stato periodico (background)
	go func() {
		for {
			refreshStatus(app)
			time.Sleep(8 * time.Second)
		}
	}()

	// Polling IPC: se un'altra istanza ha richiesto di mostrare la console
	go func() {
		flag := ipcShowFlagPath()
		logf("ipc poller started, watching %s", flag)
		for {
			if _, err := os.Stat(flag); err == nil {
				os.Remove(flag)
				logf("ipc flag detected -> showing console")
				app.hiddenMw.Synchronize(func() { showConsoleWindow() })
			}
			time.Sleep(300 * time.Millisecond)
		}
	}()

	return nil
}

func refreshStatus(app *App) {
	a := serviceStatus("86NocAgent")
	w := serviceStatus("86NocWatchdog")
	// Tutte le operazioni walk DEVONO girare sul thread del message
	// loop principale, altrimenti la UI puo' corrompersi e i bottoni
	// smettono di rispondere ai click.
	if app.hiddenMw != nil {
		app.hiddenMw.Synchronize(func() {
			if app.statusItem != nil {
				app.statusItem.SetText(fmt.Sprintf("Stato: agent=%s · watchdog=%s", a, w))
			}
			if app.tray != nil {
				if a == "Running" && w == "Running" {
					app.tray.SetToolTip("86BIT Argus Connector - Online")
				} else {
					app.tray.SetToolTip(fmt.Sprintf("86BIT Argus Connector - agent=%s", a))
				}
			}
		})
	}
	go func() {
		var hr healthReply
		err := backendGet("/api/agent/self/health", app.agent, &hr)
		txt := "Canale: errore"
		if err == nil {
			if hr.Connected {
				txt = fmt.Sprintf("Canale OK · RTT %.0fms", hr.RTT)
			} else {
				txt = "Canale: NON connesso"
			}
		}
		if app.hiddenMw != nil && app.healthItem != nil {
			app.hiddenMw.Synchronize(func() {
				app.healthItem.SetText(txt)
			})
		}
	}()
}

// --- Icon embedded ----------------------------------------------------------

func loadAppIcon() *walk.Icon {
	// Estraggo argus.ico embedded (go:embed) su file temporaneo e
	// la carico con walk. Cosi' separo l'icona dal manifest .syso
	// che resta semplice (solo Common-Controls v6 dichiarato).
	if len(argusIcoBytes) > 0 {
		tmp := filepath.Join(os.TempDir(), "argus-tray.ico")
		if err := os.WriteFile(tmp, argusIcoBytes, 0o644); err == nil {
			if icon, err := walk.NewIconFromFile(tmp); err == nil {
				return icon
			}
		}
	}
	return nil
}

// ----------------------------------------------------------------------------

// init runs before main(): set up logging immediately so any panic in
// imported packages or in main() init can still be captured.
func init() {
	setupLogging()
	logf("=== init() done; runtime=%s/%s ===", runtime.GOOS, runtime.GOARCH)
}

// --- File logging -----------------------------------------------------------

var logFile *os.File

func setupLogging() {
	// Try LOCALAPPDATA, fallback to ProgramData, fallback to USERPROFILE\AppData\Local
	candidates := []string{
		os.Getenv("LOCALAPPDATA"),
		filepath.Join(os.Getenv("USERPROFILE"), "AppData", "Local"),
		os.Getenv("ProgramData"),
		os.TempDir(),
	}
	for _, base := range candidates {
		if base == "" {
			continue
		}
		dir := filepath.Join(base, "86NocAgent", "logs")
		if err := os.MkdirAll(dir, 0o755); err != nil {
			continue
		}
		path := filepath.Join(dir, "nocui.log")
		f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
		if err != nil {
			continue
		}
		logFile = f
		exe, _ := os.Executable()
		logf("=== nocagent-ui start pid=%d args=%v exe=%s log=%s ===",
			os.Getpid(), os.Args[1:], exe, path)
		return
	}
}

func logf(format string, args ...any) {
	if logFile == nil {
		return
	}
	line := fmt.Sprintf("[%s] ", time.Now().Format("2006-01-02 15:04:05.000")) + fmt.Sprintf(format, args...) + "\n"
	logFile.WriteString(line)
	logFile.Sync()
}

func recoverAndLog() {
	if r := recover(); r != nil {
		logf("PANIC: %v", r)
		panic(r)
	}
}

func main() {
	runtime.LockOSThread()

	show := flag.Bool("show", false, "show the 'Gestisci Dispositivi' window via IPC")
	flag.Parse()

	release, alreadyRunning := acquireSingleInstance()
	defer release()

	if alreadyRunning {
		// Tray gia' attiva: chiedi alla tray di mostrare la console via file flag
		if *show {
			os.WriteFile(ipcShowFlagPath(), []byte(time.Now().Format(time.RFC3339)), 0o644)
		}
		return
	}

	app := &App{agent: loadAgentInfo(), icon: loadAppIcon()}
	theApp = app

	if err := setupTray(app); err != nil {
		walk.MsgBox(nil, "Errore", err.Error(), walk.MsgBoxIconError)
		return
	}

	if *show {
		go func() {
			time.Sleep(200 * time.Millisecond)
			app.hiddenMw.Synchronize(func() { showConsoleWindow() })
		}()
	}

	// Loop walk principale: la hidden MainWindow tiene vivo il processo.
	// L'unico modo per uscire e' walk.App().Exit() chiamato dal menu Esci.
	app.hiddenMw.Run()
}
