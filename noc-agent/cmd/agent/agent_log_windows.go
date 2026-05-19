//go:build windows

// agent_log_windows.go — comando WS "get_agent_logs" che restituisce
// al Center il contenuto del file nocagent.log del servizio agent.
//
// Motivazione: dal connector Go non vogliamo piu' esporre il path log
// (sta sotto C:\Windows\System32\config\systemprofile\AppData\... ed e'
// inaccessibile agli utenti standard). L'admin legge i log SOLO dal
// Center, cliccando 📋 sulla riga dell'agent nella pagina /agents.
//
// La logica e' simile a get_upgrade_log ma punta al log dell'agent
// stesso (nocagent.log), non al transcript di upgrade.

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
	agentLogMaxBytes  = 256 * 1024 // 256 KB cap per WS frame
	agentLogListLimit = 10
)

// registerAgentLogCommand registra il comando WS get_agent_logs.
func registerAgentLogCommand(client *transport.Client, log *logging.Logger) {
	client.Register("get_agent_logs", func(_ context.Context, args json.RawMessage) (any, error) {
		var req struct {
			TailKB int    `json:"tail_kb,omitempty"`
			File   string `json:"file,omitempty"` // future: scegli quale log
		}
		if len(args) > 0 {
			_ = json.Unmarshal(args, &req)
		}
		maxBytes := agentLogMaxBytes
		if req.TailKB > 0 && req.TailKB*1024 < maxBytes {
			maxBytes = req.TailKB * 1024
		}

		// Risoluzione path: l'agent service scrive in
		// %LOCALAPPDATA%\86NocAgent\logs\nocagent.log, ma quando gira
		// come SYSTEM (servizio Windows) LOCALAPPDATA punta a
		// C:\Windows\System32\config\systemprofile\AppData\Local\.
		// Il path effettivo viene scritto a runtime in:
		//   %ProgramData%\86NocAgent\log_path.txt
		// che il watchdog/UI usa per localizzare il file. Lo leggiamo
		// per essere sicuri al 100%.
		logPath := resolveAgentLogPath()
		baseDir := filepath.Dir(logPath)

		result := map[string]any{
			"base_dir":     baseDir,
			"log_path":     logPath,
			"exists":       false,
			"latest_log":   "",
			"latest_size":  0,
			"latest_mtime": "",
			"files":        []any{},
		}

		if logPath == "" {
			log.Info("get_agent_logs: log_path non risolto")
			return result, nil
		}

		// Lettura file principale (tail-ato)
		data, err := os.ReadFile(logPath)
		if err == nil {
			result["exists"] = true
			result["latest_size"] = len(data)
			if st, e := os.Stat(logPath); e == nil {
				result["latest_mtime"] = st.ModTime().UTC().Format(time.RFC3339)
			}
			if len(data) > maxBytes {
				result["latest_log"] = "...[truncated head]...\n" + string(data[len(data)-maxBytes:])
			} else {
				result["latest_log"] = string(data)
			}
		}

		// Lista file ruotati nella cartella (nocagent.log.1, .2, ...)
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
					!strings.Contains(name, ".log.") {
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
			sort.Slice(files, func(i, j int) bool { return files[i].MTime > files[j].MTime })
			if len(files) > agentLogListLimit {
				files = files[:agentLogListLimit]
			}
			result["files"] = files
		}

		return result, nil
	})
}

// resolveAgentLogPath legge log_path.txt persistito dal servizio agent
// (che lo scrive all'avvio dopo aver risolto %LOCALAPPDATA%). Fallback
// statico se il file manca.
func resolveAgentLogPath() string {
	if pd := os.Getenv("ProgramData"); pd != "" {
		if b, err := os.ReadFile(filepath.Join(pd, "86NocAgent", "log_path.txt")); err == nil {
			p := strings.TrimSpace(string(b))
			if p != "" {
				return p
			}
		}
	}
	if lad := os.Getenv("LOCALAPPDATA"); lad != "" {
		return filepath.Join(lad, "86NocAgent", "logs", "nocagent.log")
	}
	return ""
}

// _ helpers placeholder per evitare warning unused se la build di test cambia
var _ = fmt.Sprintf
