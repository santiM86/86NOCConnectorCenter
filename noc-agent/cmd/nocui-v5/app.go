//go:build windows

package main

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	goruntime "runtime"
	"strings"
	"sync"
	"time"

	wruntime "github.com/wailsapp/wails/v2/pkg/runtime"
)

// App è il "controller" esposto al frontend tramite il binding Wails.
// Ogni metodo pubblico (capitalized) è automaticamente disponibile come
// promise asincrona JavaScript — nessuna chiamata blocca la UI mai.
type App struct {
	ctx context.Context

	mu            sync.RWMutex
	agentInfo     AgentInfo
	agentInfoTime time.Time
}

// AgentInfo è lo stato statico letto da agent.yaml + dinamico via HTTP/WS.
type AgentInfo struct {
	AgentID       string `json:"agent_id"`
	ClientID      string `json:"client_id"`
	Token         string `json:"token"`
	BackendURL    string `json:"backend_url"`
	Hostname      string `json:"hostname"`
	Role          string `json:"role"`
	AgentVersion  string `json:"agent_version"`
	ServiceState  string `json:"service_state"` // running / stopped / unknown
	WatchdogState string `json:"watchdog_state"`
	ConfigPath    string `json:"config_path"`
}

// HealthSnapshot è la risposta di /api/agent/self/health del Center.
type HealthSnapshot struct {
	Connected       bool    `json:"connected"`
	ClientID        string  `json:"client_id"`
	AgentID         string  `json:"agent_id"`
	AgentsOnline    int     `json:"agents_online"`
	RttMs           float64 `json:"rtt_ms"`
	Hostname        string  `json:"hostname"`
	AgentVersion    string  `json:"agent_version"`
	LastHeartbeatAt string  `json:"last_heartbeat_at"`
	ConnectedAt     string  `json:"connected_at"`
	Error           string  `json:"error,omitempty"`
}

// Device è una singola riga della pagina Dispositivi.
type Device struct {
	IP         string  `json:"ip"`
	Name       string  `json:"name,omitempty"`
	Status     string  `json:"status"` // online / offline / pending
	LastPollAt string  `json:"last_poll_at,omitempty"`
	LatencyMs  float64 `json:"latency_ms,omitempty"`
	DeviceType string  `json:"device_type,omitempty"`
}

// DiscoveredEndpoint è una scoperta passiva ARP/mDNS/SNMP.
type DiscoveredEndpoint struct {
	IP          string `json:"ip"`
	MAC         string `json:"mac,omitempty"`
	Hostname    string `json:"hostname,omitempty"`
	Vendor      string `json:"vendor,omitempty"`
	Source      string `json:"source"`
	LastSeenAt  string `json:"last_seen_at,omitempty"`
	FirstSeenAt string `json:"first_seen_at,omitempty"`
}

// LogLine — riga di log emessa dall'agent locale.
type LogLine struct {
	Timestamp string `json:"timestamp"`
	Level     string `json:"level"`
	Module    string `json:"module,omitempty"`
	Message   string `json:"message"`
}

// =======================================================================
// Lifecycle
// =======================================================================

func NewApp() *App { return &App{} }

func (a *App) startup(ctx context.Context) {
	a.ctx = ctx
	a.reloadAgentInfo()
	// Inizia a pollare lo stato del servizio + health in background
	// senza mai bloccare la UI.
	go a.statusLoop()
}

func (a *App) domReady(ctx context.Context)     {}
func (a *App) beforeClose(ctx context.Context) (prevent bool) {
	// Quando l'utente chiude la finestra → nascondi in tray, non killare.
	wruntime.WindowHide(a.ctx)
	return true
}
func (a *App) shutdown(ctx context.Context) {}

// =======================================================================
// Bindings esposti al frontend (chiamati via JS: window.go.main.App.<X>)
// =======================================================================

// AppVersion ritorna la stringa version dell'eseguibile.
func (a *App) AppVersion() string { return Version }

// AgentSnapshot ritorna l'ultimo snapshot in cache (non blocca).
func (a *App) AgentSnapshot() AgentInfo {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return a.agentInfo
}

// RefreshAgent forza la rilettura di agent.yaml + service state.
func (a *App) RefreshAgent() AgentInfo {
	a.reloadAgentInfo()
	return a.AgentSnapshot()
}

// HealthCheck contatta il Center via /api/agent/self/health e ritorna
// il risultato. Eseguito in goroutine — Wails wrappa in Promise lato JS.
func (a *App) HealthCheck() HealthSnapshot {
	info := a.AgentSnapshot()
	if info.BackendURL == "" || info.Token == "" {
		return HealthSnapshot{Error: "configurazione mancante"}
	}
	url := strings.TrimRight(info.BackendURL, "/") + "/api/agent/self/health?token=" + info.Token
	cli := &http.Client{Timeout: 8 * time.Second}
	resp, err := cli.Get(url)
	if err != nil {
		return HealthSnapshot{Error: err.Error()}
	}
	defer resp.Body.Close()
	var out HealthSnapshot
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return HealthSnapshot{Error: "decode: " + err.Error()}
	}
	return out
}

// ListDevices chiama il Center per la lista dispositivi del tenant.
func (a *App) ListDevices() ([]Device, error) {
	info := a.AgentSnapshot()
	if info.BackendURL == "" || info.Token == "" {
		return nil, fmt.Errorf("agent non configurato")
	}
	url := strings.TrimRight(info.BackendURL, "/") + "/api/devices?token=" + info.Token
	out, err := httpGetJSON[[]Device](url, 10*time.Second)
	if err != nil {
		return nil, err
	}
	return out, nil
}

// ListDiscovered chiama il Center per gli endpoint scoperti.
func (a *App) ListDiscovered() ([]DiscoveredEndpoint, error) {
	info := a.AgentSnapshot()
	if info.BackendURL == "" || info.Token == "" {
		return nil, fmt.Errorf("agent non configurato")
	}
	url := strings.TrimRight(info.BackendURL, "/") + "/api/discovery/endpoints?token=" + info.Token
	out, err := httpGetJSON[[]DiscoveredEndpoint](url, 10*time.Second)
	if err != nil {
		return nil, err
	}
	return out, nil
}

// TestPing invoca il comando `force_ping_poll` sull'agent via Center.
// Non blocca: il Center proxa la chiamata via WebSocket all'agent locale.
func (a *App) TestPing(ip string) (map[string]any, error) {
	info := a.AgentSnapshot()
	if info.BackendURL == "" || info.Token == "" {
		return nil, fmt.Errorf("agent non configurato")
	}
	url := strings.TrimRight(info.BackendURL, "/") + "/api/agent/self/ping/test?token=" + info.Token
	return httpPostJSON[map[string]any](url, map[string]any{"ip": ip}, 15*time.Second)
}

// StartService avvia il servizio 86NocAgent (richiede admin).
func (a *App) StartService() error { return runSC("start", "86NocAgent") }

// StopService ferma il servizio 86NocAgent (richiede admin).
func (a *App) StopService() error { return runSC("stop", "86NocAgent") }

// RestartService = stop + start (sequenziale, non blocca grazie a goroutine
// nel chiamante JS).
func (a *App) RestartService() error {
	_ = runSC("stop", "86NocAgent")
	time.Sleep(800 * time.Millisecond)
	return runSC("start", "86NocAgent")
}

// ReadLogs ritorna le ultime `n` righe del log dell'agent locale.
func (a *App) ReadLogs(n int) ([]LogLine, error) {
	if n <= 0 || n > 5000 {
		n = 500
	}
	logPath := defaultLogPath()
	f, err := os.Open(logPath)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil {
		return nil, err
	}
	// Leggi gli ultimi ~64 KB (sufficiente per ~500 righe) per evitare di
	// caricare file da 100 MB in memoria.
	const window = 256 * 1024
	start := int64(0)
	if st.Size() > window {
		start = st.Size() - window
	}
	if _, err := f.Seek(start, 0); err != nil {
		return nil, err
	}
	buf := make([]byte, st.Size()-start)
	_, _ = f.Read(buf)
	lines := strings.Split(string(buf), "\n")
	if len(lines) > n {
		lines = lines[len(lines)-n:]
	}
	out := make([]LogLine, 0, len(lines))
	for _, l := range lines {
		if l == "" {
			continue
		}
		var ll LogLine
		if err := json.Unmarshal([]byte(l), &ll); err != nil {
			// Riga non-JSON → mostra grezza.
			ll = LogLine{Message: l, Level: "info"}
		}
		out = append(out, ll)
	}
	return out, nil
}

// OpenDashboard apre la dashboard web del Center nel browser di default.
func (a *App) OpenDashboard() error {
	info := a.AgentSnapshot()
	url := info.BackendURL
	if url == "" {
		url = "https://argus.86bit.it"
	}
	return openURL(url)
}

// OpenExternal apre un URL arbitrario nel browser (esposto al frontend).
func (a *App) OpenExternal(url string) error { return openURL(url) }

// OpenConfig apre la cartella ProgramData con agent.yaml in Explorer.
func (a *App) OpenConfig() error {
	dir := filepath.Join(os.Getenv("ProgramData"), "86NocAgent")
	cmd := exec.Command("explorer.exe", dir)
	return cmd.Start()
}

// =======================================================================
// Helpers
// =======================================================================

func (a *App) reloadAgentInfo() {
	info := loadAgentInfoFromYAML()
	info.ServiceState = serviceStatus("86NocAgent")
	info.WatchdogState = serviceStatus("86NocWatchdog")
	if h, err := os.Hostname(); err == nil {
		info.Hostname = h
	}
	a.mu.Lock()
	a.agentInfo = info
	a.agentInfoTime = time.Now()
	a.mu.Unlock()
	// Notifica il frontend (event-based, mai polling lato JS).
	if a.ctx != nil {
		wruntime.EventsEmit(a.ctx, "agent:updated", info)
	}
}

func (a *App) statusLoop() {
	t := time.NewTicker(5 * time.Second)
	defer t.Stop()
	for {
		select {
		case <-a.ctx.Done():
			return
		case <-t.C:
			a.reloadAgentInfo()
		}
	}
}

func runSC(args ...string) error {
	args = append([]string{}, args...)
	cmd := exec.Command("sc.exe", args...)
	return cmd.Run()
}

func openURL(u string) error {
	switch goruntime.GOOS {
	case "windows":
		return exec.Command("rundll32.exe", "url.dll,FileProtocolHandler", u).Start()
	case "darwin":
		return exec.Command("open", u).Start()
	default:
		return exec.Command("xdg-open", u).Start()
	}
}

func defaultLogPath() string {
	return filepath.Join(os.Getenv("ProgramData"), "86NocAgent", "nocagent.log")
}
