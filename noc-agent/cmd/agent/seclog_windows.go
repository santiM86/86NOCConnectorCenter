//go:build windows

// Package main — Registro accessi Amministratori di Sistema (Windows Event Log).
// Ogni 60s legge i nuovi eventi Security/System/RDP tramite Get-WinEvent
// (cursore su RecordId per log, persistito su disco) e li invia al Center
// come evento WS kind=security_events. Il Center li concatena con hash SHA-256.
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/86bit/noc-agent/internal/config"
	"github.com/86bit/noc-agent/internal/logging"
	"github.com/86bit/noc-agent/internal/transport"
)

const secLogEventKind = "security_events"

var secLogSources = []struct {
	Log string
	IDs string
}{
	{"Security", "4624,4625,4634,4647,4672,4720,4722,4724,4725,4726,4728,4732,4733,4756,4740,4767,1102"},
	{"System", "6005,6006,1074,41,6008,104"},
	{"Microsoft-Windows-TerminalServices-RemoteConnectionManager/Operational", "1149"},
	{"Microsoft-Windows-TerminalServices-LocalSessionManager/Operational", "21,24,25"},
}

type secLogEvent struct {
	Log       string            `json:"log"`
	RecordID  int64             `json:"record_id"`
	EventID   int               `json:"event_id"`
	TS        string            `json:"ts"`
	Data      map[string]string `json:"data"`
	Message   string            `json:"message,omitempty"`
	LogonType string            `json:"logon_type,omitempty"`
}

type secLogBatch struct {
	Hostname string        `json:"hostname"`
	Events   []secLogEvent `json:"events"`
}

type secLogCursor map[string]int64

func secLogCursorPath() string {
	return filepath.Join(config.DefaultStateDir(), "seclog_cursor.json")
}

func loadSecLogCursor() secLogCursor {
	c := secLogCursor{}
	if b, err := os.ReadFile(secLogCursorPath()); err == nil {
		_ = json.Unmarshal(b, &c)
	}
	return c
}

func saveSecLogCursor(c secLogCursor) {
	p := secLogCursorPath()
	_ = os.MkdirAll(filepath.Dir(p), 0o755)
	if b, err := json.Marshal(c); err == nil {
		_ = os.WriteFile(p, b, 0o600)
	}
}

// secLogScript: PowerShell che estrae gli eventi > RecordId con EventData come mappa piatta.
const secLogScript = `
$ErrorActionPreference='SilentlyContinue'
$log=%q; $ids=@(%s); $after=%d; $max=%d
$filter=@{LogName=$log; Id=$ids}
if ($after -le 0) { $filter['StartTime']=(Get-Date).AddHours(-24) }
$evs=Get-WinEvent -FilterHashtable $filter -MaxEvents 5000 2>$null | Where-Object { $_.RecordId -gt $after } | Sort-Object RecordId | Select-Object -First $max
$out=@()
foreach ($e in $evs) {
  $d=@{}
  try { $x=[xml]$e.ToXml(); foreach ($n in $x.Event.EventData.Data) { if ($n.Name) { $d[$n.Name]=[string]$n.'#text' } }
        if ($x.Event.UserData) { foreach ($n in $x.Event.UserData.ChildNodes[0].ChildNodes) { $d[$n.LocalName]=[string]$n.InnerText } } } catch {}
  $out+=[pscustomobject]@{log=$log; record_id=$e.RecordId; event_id=$e.Id; ts=$e.TimeCreated.ToUniversalTime().ToString('o'); data=$d; message=([string]$e.Message).Split("` + "`n" + `")[0]}
}
$out | ConvertTo-Json -Depth 4 -Compress
`

func collectSecLog(ctx context.Context, log *logging.Logger, cur secLogCursor) ([]secLogEvent, bool) {
	var all []secLogEvent
	changed := false
	for _, src := range secLogSources {
		after := cur[src.Log]
		cctx, cancel := context.WithTimeout(ctx, 90*time.Second)
		out, err := runPowershell(cctx, fmt.Sprintf(secLogScript, src.Log, src.IDs, after, 400))
		cancel()
		out = strings.TrimSpace(out)
		if err != nil && out == "" {
			log.Debug("seclog query failed", "log", src.Log, "err", err.Error())
			continue
		}
		if out == "" || out == "null" {
			continue
		}
		var evs []secLogEvent
		if strings.HasPrefix(out, "{") {
			var one secLogEvent
			if json.Unmarshal([]byte(out), &one) == nil {
				evs = []secLogEvent{one}
			}
		} else if json.Unmarshal([]byte(out), &evs) != nil {
			log.Warn("seclog parse failed", "log", src.Log, "len", fmt.Sprint(len(out)))
			continue
		}
		for _, e := range evs {
			if e.RecordID > cur[src.Log] {
				cur[src.Log] = e.RecordID
				changed = true
			}
			if lt, ok := e.Data["LogonType"]; ok {
				e.LogonType = lt
			}
			all = append(all, e)
		}
	}
	return all, changed
}

// runSecLogCollector: loop ogni 60s; invia batch ≤200 eventi; cursore persistito solo dopo l'enqueue.
func runSecLogCollector(ctx context.Context, client *transport.Client, log *logging.Logger) {
	slog := log.With("seclog")
	cur := loadSecLogCursor()
	hostname, _ := os.Hostname()
	slog.Info("seclog collector started", "logs", fmt.Sprint(len(secLogSources)))
	t := time.NewTicker(60 * time.Second)
	defer t.Stop()
	for {
		evs, changed := collectSecLog(ctx, slog, cur)
		for i := 0; i < len(evs); i += 200 {
			j := i + 200
			if j > len(evs) {
				j = len(evs)
			}
			if !client.PushEvent(secLogEventKind, secLogBatch{Hostname: hostname, Events: evs[i:j]}) {
				slog.Warn("seclog push backpressure — batch dropped", "n", fmt.Sprint(j-i))
			}
		}
		if changed {
			saveSecLogCursor(cur)
		}
		select {
		case <-ctx.Done():
			return
		case <-t.C:
		}
	}
}
