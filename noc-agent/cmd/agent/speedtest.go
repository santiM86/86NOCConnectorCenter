// Package main — handler comando WS "speedtest".
// Esegue uno speedtest puro-Go (no dipendenze esterne) misurando:
//   - download speed via HTTP GET su file noti (Cloudflare speed test endpoint)
//   - upload speed via HTTP POST su httpbin/Cloudflare
//   - ping/jitter via ICMP verso il server piu' vicino
//
// Strategia ridotta: per chiudere il loop Fase 1 senza appesantire il binario
// con la lib Ookla, usiamo Cloudflare's /__down e /__up endpoint che ogni MSP
// usa come reference (Auvik fa lo stesso). Risultati buoni come baseline.
//
// Il risultato viene POSTato al Center via HTTP API (no callback WS) per
// semplicita': l'agent ha gia' un client HTTP autenticato (cfg.Server.BaseURL).
//
// Cross-platform: nessun import platform-specific.
package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// speedtestArgs sono gli argomenti del comando WS dal Center.
type speedtestArgs struct {
	CommandID string `json:"command_id"`
	ClientID  string `json:"client_id"`
}

// speedtestResult e' il payload POSTed al Center via /external-monitor/speedtest-result.
type speedtestResult struct {
	CommandID    string  `json:"command_id"`
	ClientID     string  `json:"client_id"`
	AgentID      string  `json:"agent_id"`
	DownloadMbps float64 `json:"download_mbps"`
	UploadMbps   float64 `json:"upload_mbps"`
	PingMs       float64 `json:"ping_ms"`
	JitterMs     float64 `json:"jitter_ms"`
	Server       string  `json:"server"`
	ISP          string  `json:"isp"`
	Error        string  `json:"error,omitempty"`
}

const (
	cfDownURL = "https://speed.cloudflare.com/__down?bytes=26214400"  // 25 MB
	cfUpURL   = "https://speed.cloudflare.com/__up"
	cfMetaURL = "https://speed.cloudflare.com/meta"
	dlSize    = 25 * 1024 * 1024
	ulSize    = 8 * 1024 * 1024
)

// runSpeedtest esegue download+upload+ping e ritorna il payload da inviare.
func runSpeedtest(ctx context.Context, cmdID, clientID, agentID string) speedtestResult {
	r := speedtestResult{
		CommandID: cmdID,
		ClientID:  clientID,
		AgentID:   agentID,
		Server:    "Cloudflare speed.cloudflare.com",
	}

	// 1. Metadata (ISP detection) — best-effort, no fail
	cli := &http.Client{Timeout: 10 * time.Second}
	if req, err := http.NewRequestWithContext(ctx, "GET", cfMetaURL, nil); err == nil {
		if resp, err := cli.Do(req); err == nil {
			defer resp.Body.Close()
			var meta struct {
				ASN         int    `json:"asn"`
				ASOrg       string `json:"asOrganization"`
				City        string `json:"city"`
				Country     string `json:"country"`
				ColoCity    string `json:"clientLocation"`
			}
			if json.NewDecoder(resp.Body).Decode(&meta) == nil && meta.ASOrg != "" {
				r.ISP = fmt.Sprintf("AS%d %s", meta.ASN, meta.ASOrg)
			}
		}
	}

	// 2. Download speed (25 MB)
	downCli := &http.Client{Timeout: 60 * time.Second}
	t0 := time.Now()
	req, _ := http.NewRequestWithContext(ctx, "GET", cfDownURL, nil)
	resp, err := downCli.Do(req)
	if err != nil {
		r.Error = "download: " + err.Error()
		return r
	}
	n, _ := io.Copy(io.Discard, resp.Body)
	resp.Body.Close()
	elapsed := time.Since(t0).Seconds()
	if elapsed > 0 && n > 0 {
		r.DownloadMbps = float64(n) * 8 / elapsed / 1_000_000
		r.DownloadMbps = round1(r.DownloadMbps)
	}

	// 3. Upload speed (8 MB random)
	uploadCli := &http.Client{Timeout: 60 * time.Second}
	payload := make([]byte, ulSize)
	rand.Read(payload)
	t0 = time.Now()
	upReq, _ := http.NewRequestWithContext(ctx, "POST", cfUpURL, bytes.NewReader(payload))
	upReq.Header.Set("Content-Type", "application/octet-stream")
	upResp, err := uploadCli.Do(upReq)
	if err != nil {
		r.Error = "upload: " + err.Error()
		// Continuiamo: down e' valido, segniamo upload come 0 + error
	} else {
		io.Copy(io.Discard, upResp.Body)
		upResp.Body.Close()
		elapsed = time.Since(t0).Seconds()
		if elapsed > 0 {
			r.UploadMbps = float64(ulSize) * 8 / elapsed / 1_000_000
			r.UploadMbps = round1(r.UploadMbps)
		}
	}

	// 4. Ping + jitter via 6 GET piccoli al meta endpoint
	var lats []float64
	for i := 0; i < 6; i++ {
		t0 := time.Now()
		req, _ := http.NewRequestWithContext(ctx, "GET", cfMetaURL, nil)
		resp, err := cli.Do(req)
		if err == nil {
			io.Copy(io.Discard, resp.Body)
			resp.Body.Close()
			lats = append(lats, float64(time.Since(t0).Milliseconds()))
		}
		time.Sleep(150 * time.Millisecond)
	}
	if len(lats) > 0 {
		var sum float64
		for _, v := range lats {
			sum += v
		}
		avg := sum / float64(len(lats))
		r.PingMs = round1(avg)
		var jitter float64
		for i := 1; i < len(lats); i++ {
			d := lats[i] - lats[i-1]
			if d < 0 {
				d = -d
			}
			jitter += d
		}
		if len(lats) > 1 {
			r.JitterMs = round1(jitter / float64(len(lats)-1))
		}
	}

	return r
}

func round1(v float64) float64 {
	return float64(int(v*10+0.5)) / 10
}

// sendSpeedtestResult fa POST al Center via HTTP base URL.
// baseURL puo' essere il WS URL (wss://host/api/agent/ws) o un HTTPS plain.
// La funzione lo converte automaticamente in https://host.
func sendSpeedtestResult(ctx context.Context, baseURL, agentID, token string, res speedtestResult) error {
	if baseURL == "" {
		return fmt.Errorf("baseURL empty")
	}
	// Normalizza: wss:// → https://, ws:// → http://, rimuove path /api/agent/ws
	httpBase := baseURL
	if strings.HasPrefix(httpBase, "wss://") {
		httpBase = "https://" + httpBase[len("wss://"):]
	} else if strings.HasPrefix(httpBase, "ws://") {
		httpBase = "http://" + httpBase[len("ws://"):]
	}
	if idx := strings.Index(httpBase, "/api/"); idx > 0 {
		httpBase = httpBase[:idx]
	}
	u, err := url.Parse(strings.TrimRight(httpBase, "/") + "/api/external-monitor/speedtest-result")
	if err != nil {
		return err
	}
	body, _ := json.Marshal(res)
	req, _ := http.NewRequestWithContext(ctx, "POST", u.String(), bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	if agentID != "" {
		req.Header.Set("X-Agent-ID", agentID)
	}
	cli := &http.Client{Timeout: 15 * time.Second}
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
