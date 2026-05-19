//go:build windows

// upgrade_log_windows.go — comando WS "get_upgrade_log" che recupera
// dal PC client i log degli ultimi tentativi di upgrade dell'agent.
//
// Il Center invoca questo comando per ispezionare un crash di update
// remoto SENZA dover RDP-are sul PC del cliente. I log vivono in
// %TEMP%\86noc-upgrade-logs\ (vedi install-noc-agent.ps1 step 0.PRE
// e update_remote_windows.go wrapper). Su SYSTEM = C:\Windows\Temp\86noc-upgrade-logs\.
//
// Il payload riportato include:
//   - marker JSON (status + start/end times + PID)
//   - contenuto di noc_upgrade_latest.log (cap 256 KB)
//   - lista cronologica degli ultimi 10 file con dimensioni e timestamp
//
// In questo modo il pulsante "Vedi log upgrade" della pagina /agents
// del Center mostra immediatamente il crash di upgrade piu' recente.

package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/86bit/noc-agent/internal/logging"
	"github.com/86bit/noc-agent/internal/transport"
)

const (
	upgradeLogDirName    = "86noc-upgrade-logs"
	upgradeLogMaxBytes   = 256 * 1024 // 256 KB cap per fitting in WS frame
	upgradeLogListLimit  = 10
)

// registerUpgradeLogCommand registra il comando WS sul client.
func registerUpgradeLogCommand(client *transport.Client, log *logging.Logger) {
	client.Register("get_upgrade_log", func(_ context.Context, args json.RawMessage) (any, error) {
		var req struct {
			TailKB int `json:"tail_kb,omitempty"`
		}
		if len(args) > 0 {
			_ = json.Unmarshal(args, &req)
		}

		// Default: leggiamo TUTTO il file fino al cap. Se tail_kb >0
		// torniamo solo le ultime N KB (utile per UI rapida).
		maxBytes := upgradeLogMaxBytes
		if req.TailKB > 0 && req.TailKB*1024 < maxBytes {
			maxBytes = req.TailKB * 1024
		}

		baseDir := filepath.Join(os.Getenv("TEMP"), upgradeLogDirName)
		// Fallback per SYSTEM senza %TEMP%: usa C:\Windows\Temp diretto.
		if os.Getenv("TEMP") == "" {
			baseDir = filepath.Join("C:\\Windows\\Temp", upgradeLogDirName)
		}

		result := map[string]any{
			"base_dir":      baseDir,
			"exists":        false,
			"marker":        nil,
			"latest_log":    "",
			"latest_path":   "",
			"latest_size":   0,
			"latest_mtime":  "",
			"files":         []any{},
		}

		fi, err := os.Stat(baseDir)
		if err != nil || !fi.IsDir() {
			log.Info("get_upgrade_log: base_dir assente",
				"base_dir", baseDir,
				"err", fmt.Sprintf("%v", err))
			return result, nil
		}
		result["exists"] = true

		// Leggi marker JSON (status, started, log_file)
		markerPath := filepath.Join(baseDir, "noc_upgrade_marker.txt")
		if data, err := os.ReadFile(markerPath); err == nil {
			var markerObj map[string]any
			if json.Unmarshal(data, &markerObj) == nil {
				result["marker"] = markerObj
			} else {
				result["marker"] = map[string]string{"raw": string(data)}
			}
		}

		// Leggi noc_upgrade_latest.log (tail-ato)
		latestPath := filepath.Join(baseDir, "noc_upgrade_latest.log")
		if data, err := os.ReadFile(latestPath); err == nil {
			result["latest_path"] = latestPath
			result["latest_size"] = len(data)
			if st, e := os.Stat(latestPath); e == nil {
				result["latest_mtime"] = st.ModTime().UTC().Format(time.RFC3339)
			}
			if len(data) > maxBytes {
				// Tail: tieni gli ultimi maxBytes
				result["latest_log"] = "...[truncated head]...\n" + string(data[len(data)-maxBytes:])
			} else {
				result["latest_log"] = string(data)
			}
		}

		// Lista cronologica file .log e .txt nella cartella, max 10
		entries, err := os.ReadDir(baseDir)
		if err == nil {
			type fileInfo struct {
				Name  string `json:"name"`
				Size  int64  `json:"size"`
				MTime string `json:"mtime"`
			}
			var files []fileInfo
			for _, e := range entries {
				if e.IsDir() {
					continue
				}
				name := e.Name()
				if !strings.HasSuffix(name, ".log") &&
					!strings.HasSuffix(name, ".txt") {
					continue
				}
				info, ie := e.Info()
				if ie != nil {
					continue
				}
				files = append(files, fileInfo{
					Name:  name,
					Size:  info.Size(),
					MTime: info.ModTime().UTC().Format(time.RFC3339),
				})
			}
			// Sort by mtime descending
			sort.Slice(files, func(i, j int) bool { return files[i].MTime > files[j].MTime })
			if len(files) > upgradeLogListLimit {
				files = files[:upgradeLogListLimit]
			}
			result["files"] = files
		}

		return result, nil
	})
}
