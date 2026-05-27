//go:build windows

// Package main — Hyper-V WMI collector
// Esegue WMI query verso namespace `root\virtualization\v2` e `root\cimv2`
// per raccogliere host info + lista VM + metriche per VM.
//
// Non blocca se Hyper-V non e' installato (verifica presenza del namespace).
// Output: POSTed al Center via /api/servers/hyperv/snapshot.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os/exec"
	"strings"
	"time"
)

type hyperVArgs struct {
	CommandID string `json:"command_id"`
	ClientID  string `json:"client_id"`
}

type hyperVVM struct {
	Name        string `json:"name"`
	State       string `json:"state"`        // Running/Off/Saved/Paused
	CPUUsage    int    `json:"cpu_usage"`    // %
	MemoryMB    int    `json:"memory_mb"`    // MB
	UptimeSec   int    `json:"uptime_sec"`
	Version     string `json:"version"`
	Generation  int    `json:"generation"`
}

type hyperVSnapshot struct {
	CommandID    string     `json:"command_id"`
	ClientID     string     `json:"client_id"`
	AgentID      string     `json:"agent_id"`
	Hostname     string     `json:"hostname"`
	HostInfo     map[string]interface{} `json:"host_info"`
	HyperVPresent bool       `json:"hyperv_present"`
	VMs          []hyperVVM `json:"vms"`
	Cluster      map[string]interface{} `json:"cluster,omitempty"`
	CSV          []map[string]interface{} `json:"csv,omitempty"`
	Replicas     []map[string]interface{} `json:"replicas,omitempty"`
	Error        string     `json:"error,omitempty"`
}

// runPowershell esegue uno script PS e ritorna stdout/stderr.
func runPowershell(ctx context.Context, script string) (string, error) {
	cmd := exec.CommandContext(ctx, "powershell.exe", "-NoProfile", "-NonInteractive",
		"-ExecutionPolicy", "Bypass", "-Command", script)
	out, err := cmd.CombinedOutput()
	return string(out), err
}

func collectHyperV(ctx context.Context, cmdID, clientID, agentID, hostname string) hyperVSnapshot {
	snap := hyperVSnapshot{
		CommandID: cmdID,
		ClientID:  clientID,
		AgentID:   agentID,
		Hostname:  hostname,
		HostInfo:  map[string]interface{}{},
		VMs:       []hyperVVM{},
	}

	// 1. Check Hyper-V presente
	psCheck := `if (Get-Module -ListAvailable -Name Hyper-V) { "OK" } else { "NO" }`
	out, _ := runPowershell(ctx, psCheck)
	if !strings.Contains(out, "OK") {
		snap.HyperVPresent = false
		snap.Error = "Hyper-V module not installed"
		return snap
	}
	snap.HyperVPresent = true

	// 2. Host info
	psHost := `
$h = Get-VMHost -ErrorAction SilentlyContinue
if ($h) {
  @{
    LogicalProcessors = $h.LogicalProcessorCount
    MemoryGB          = [math]::Round($h.MemoryCapacity / 1GB, 0)
    Version           = (Get-CimInstance Win32_OperatingSystem).Version
    VirtSwitches      = (Get-VMSwitch -ErrorAction SilentlyContinue | Measure).Count
    StoragePath       = $h.VirtualMachinePath
    EnableEnhancedSessionMode = $h.EnableEnhancedSessionMode
  } | ConvertTo-Json -Compress
}`
	out, _ = runPowershell(ctx, psHost)
	if out != "" {
		var hi map[string]interface{}
		if json.Unmarshal([]byte(strings.TrimSpace(out)), &hi) == nil {
			snap.HostInfo = hi
		}
	}

	// 3. Lista VM con metriche
	psVMs := `
Get-VM -ErrorAction SilentlyContinue | ForEach-Object {
  $vm = $_
  $u = $vm.Uptime.TotalSeconds
  @{
    name        = $vm.Name
    state       = $vm.State.ToString()
    cpu_usage   = [int]$vm.CPUUsage
    memory_mb   = [int]($vm.MemoryAssigned / 1MB)
    uptime_sec  = [int]$u
    version     = $vm.Version
    generation  = [int]$vm.Generation
  }
} | ConvertTo-Json -Compress`
	out, _ = runPowershell(ctx, psVMs)
	if out != "" {
		trimmed := strings.TrimSpace(out)
		// Single VM = object, multi = array
		if strings.HasPrefix(trimmed, "{") {
			var v hyperVVM
			if json.Unmarshal([]byte(trimmed), &v) == nil {
				snap.VMs = []hyperVVM{v}
			}
		} else if strings.HasPrefix(trimmed, "[") {
			_ = json.Unmarshal([]byte(trimmed), &snap.VMs)
		}
	}

	// 4. Cluster info (best-effort)
	psCluster := `
$c = Get-Cluster -ErrorAction SilentlyContinue
if ($c) {
  @{
    name     = $c.Name
    quorum   = (Get-ClusterQuorum -ErrorAction SilentlyContinue).QuorumResource.Name
    nodes    = @(Get-ClusterNode -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name)
  } | ConvertTo-Json -Compress
}`
	out, _ = runPowershell(ctx, psCluster)
	if out != "" {
		var cl map[string]interface{}
		if json.Unmarshal([]byte(strings.TrimSpace(out)), &cl) == nil {
			snap.Cluster = cl
		}
	}

	// 5. Hyper-V Replica (best-effort)
	psReplica := `
Get-VMReplication -ErrorAction SilentlyContinue | ForEach-Object {
  @{
    vm        = $_.VMName
    state     = $_.State.ToString()
    health    = $_.Health.ToString()
    primary   = $_.PrimaryServer
    replica   = $_.ReplicaServer
    last_replication = $_.LastReplicationTime.ToString("o")
  }
} | ConvertTo-Json -Compress`
	out, _ = runPowershell(ctx, psReplica)
	if out != "" {
		trimmed := strings.TrimSpace(out)
		if strings.HasPrefix(trimmed, "[") {
			_ = json.Unmarshal([]byte(trimmed), &snap.Replicas)
		} else if strings.HasPrefix(trimmed, "{") {
			var r map[string]interface{}
			if json.Unmarshal([]byte(trimmed), &r) == nil {
				snap.Replicas = []map[string]interface{}{r}
			}
		}
	}

	return snap
}

// sendHyperVSnapshot POSTa lo snapshot al Center.
func sendHyperVSnapshot(ctx context.Context, baseURL, agentID, token string, snap hyperVSnapshot) error {
	if baseURL == "" {
		return fmt.Errorf("baseURL empty")
	}
	httpBase := baseURL
	if strings.HasPrefix(httpBase, "wss://") {
		httpBase = "https://" + httpBase[len("wss://"):]
	} else if strings.HasPrefix(httpBase, "ws://") {
		httpBase = "http://" + httpBase[len("ws://"):]
	}
	if idx := strings.Index(httpBase, "/api/"); idx > 0 {
		httpBase = httpBase[:idx]
	}
	u, err := url.Parse(strings.TrimRight(httpBase, "/") + "/api/servers/hyperv/snapshot")
	if err != nil {
		return err
	}
	body, _ := json.Marshal(snap)
	req, _ := http.NewRequestWithContext(ctx, "POST", u.String(), bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	if agentID != "" {
		req.Header.Set("X-Agent-ID", agentID)
	}
	cli := &http.Client{Timeout: 20 * time.Second}
	resp, err := cli.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		b, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("status %d: %s", resp.StatusCode, string(b))
	}
	return nil
}
