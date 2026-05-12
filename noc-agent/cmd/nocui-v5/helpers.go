//go:build windows

package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

// loadAgentInfoFromYAML legge l'agent.yaml sotto ProgramData e ne estrae
// i campi che la UI mostra. Volutamente parser minimale: niente
// dipendenze YAML (lo schema è piatto, key: value).
func loadAgentInfoFromYAML() AgentInfo {
	info := AgentInfo{Role: "master"}
	cfgPath := filepath.Join(os.Getenv("ProgramData"), "86NocAgent", "agent.yaml")
	info.ConfigPath = cfgPath
	b, err := os.ReadFile(cfgPath)
	if err != nil {
		return info
	}
	for _, raw := range strings.Split(string(b), "\n") {
		l := strings.TrimSpace(raw)
		if l == "" || strings.HasPrefix(l, "#") {
			continue
		}
		key, val, ok := strings.Cut(l, ":")
		if !ok {
			continue
		}
		key = strings.TrimSpace(key)
		val = strings.TrimSpace(val)
		val = strings.Trim(val, `"'`)
		switch key {
		case "agent_id":
			info.AgentID = val
		case "client_id":
			info.ClientID = val
		case "token":
			info.Token = val
		case "role":
			info.Role = val
		case "url":
			// dentro `backend:` block, salta se vuoto
			if val != "" && (strings.HasPrefix(val, "http") || strings.HasPrefix(val, "ws")) {
				// converti ws/wss a http/https per la UI
				if strings.HasPrefix(val, "wss://") {
					val = "https://" + strings.TrimPrefix(val, "wss://")
				} else if strings.HasPrefix(val, "ws://") {
					val = "http://" + strings.TrimPrefix(val, "ws://")
				}
				val = strings.TrimSuffix(val, "/api/agent/ws")
				info.BackendURL = val
			}
		}
	}
	// Versione binario: chiama nocagent.exe --version
	if info.AgentVersion == "" {
		info.AgentVersion = readAgentVersion()
	}
	return info
}

func readAgentVersion() string {
	exe := filepath.Join(os.Getenv("ProgramFiles"), "86NocAgent", "nocagent.exe")
	if _, err := os.Stat(exe); err != nil {
		return ""
	}
	cmd := exec.Command(exe, "--version")
	out, err := cmd.CombinedOutput()
	if err != nil {
		return ""
	}
	// "86NocAgent 4.2.0+abcdef (windows/amd64, go 1.23)"
	parts := strings.Fields(string(out))
	if len(parts) >= 2 {
		return parts[1]
	}
	return strings.TrimSpace(string(out))
}

// serviceStatus interroga il servizio Windows via sc.exe e ritorna
// "running" / "stopped" / "unknown" come stringa pronta per la UI.
func serviceStatus(name string) string {
	cmd := exec.Command("sc.exe", "query", name)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return "unknown"
	}
	s := strings.ToUpper(string(out))
	switch {
	case strings.Contains(s, "RUNNING"):
		return "running"
	case strings.Contains(s, "STOPPED"):
		return "stopped"
	case strings.Contains(s, "START_PENDING"):
		return "starting"
	case strings.Contains(s, "STOP_PENDING"):
		return "stopping"
	default:
		return "unknown"
	}
}

// httpGetJSON è un helper generico per le chiamate JSON al Center.
// Tipizzato (Go 1.18+ generics) per evitare unmarshal-cast a runtime.
func httpGetJSON[T any](url string, timeout time.Duration) (T, error) {
	var zero T
	cli := &http.Client{Timeout: timeout}
	resp, err := cli.Get(url)
	if err != nil {
		return zero, err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		body, _ := io.ReadAll(resp.Body)
		return zero, fmt.Errorf("HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(body)))
	}
	var out T
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return zero, err
	}
	return out, nil
}

func httpPostJSON[T any](url string, body any, timeout time.Duration) (T, error) {
	var zero T
	js, err := json.Marshal(body)
	if err != nil {
		return zero, err
	}
	cli := &http.Client{Timeout: timeout}
	resp, err := cli.Post(url, "application/json", bytes.NewReader(js))
	if err != nil {
		return zero, err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		b, _ := io.ReadAll(resp.Body)
		return zero, fmt.Errorf("HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(b)))
	}
	var out T
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return zero, err
	}
	return out, nil
}
