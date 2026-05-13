//go:build windows

package main

// push_scan_results_windows.go
//
// pushScanResultsToCenter posts the in-memory results of the network scanner
// to the NOC Center via POST /api/agent/scan-report, using the bearer token
// from agent.yaml (already loaded into app.agent).
//
// Aggiunto su richiesta dell'utente: "voglio un pulsante che quando finisce
// scan passi subito i dati al center". L'utente non vuole attendere il
// prossimo ciclo di discovery dell'agent (5 min): da console clicca
// "Scansiona Rete" -> "Invia al NOC Center" e i risultati appaiono
// immediatamente nella lista dispositivi del cliente.

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// scanReportEndpoint mirrors backend/routes/agent_ws.py:ScanReportEndpoint.
// Tag JSON identici per evitare drift di serializzazione.
type scanReportEndpoint struct {
	IP            string  `json:"ip"`
	MAC           string  `json:"mac,omitempty"`
	Hostname      string  `json:"hostname,omitempty"`
	Vendor        string  `json:"vendor,omitempty"`
	RTTms         float64 `json:"rtt_ms,omitempty"`
	DiscoveredVia string  `json:"discovered_via"`
	SysDescr      string  `json:"sys_descr,omitempty"`
}

type scanReportRequest struct {
	ClientID  string                `json:"client_id"`
	Subnet    string                `json:"subnet"`
	Endpoints []scanReportEndpoint  `json:"endpoints"`
}

type scanReportResponse struct {
	Status            string `json:"status"`
	EndpointsStored   int    `json:"endpoints_stored"`
	DevicesAutoAdded  int    `json:"devices_auto_added"`
	Detail            string `json:"detail,omitempty"`
}

// pushScanResultsToCenter sends the scan results and returns (stored, auto_added, err).
//
// Resolves the backend HTTPS base URL from app.agent.BackendURL (which is
// already in https:// form thanks to wsToHttp() during loadAgentInfo).
// If the URL ends with /api/agent/ws it is stripped so the result is a
// clean base like https://argus.86bit.it.
func pushScanResultsToCenter(app *App, items []*ScanResult, subnet string) (int, int, error) {
	if app == nil || app.agent.Token == "" {
		return 0, 0, errors.New("token agent assente in agent.yaml (campo top-level 'token')")
	}
	if app.agent.ClientID == "" || app.agent.ClientID == "unknown" {
		return 0, 0, errors.New("client_id agent assente o 'unknown' in agent.yaml")
	}

	base := strings.TrimRight(app.agent.BackendURL, "/")
	// Tollera sia wss:// (in caso non sia stato convertito) sia paths leftover.
	base = strings.TrimSuffix(base, "/api/agent/ws")
	base = strings.Replace(base, "wss://", "https://", 1)
	base = strings.Replace(base, "ws://", "http://", 1)
	if !strings.HasPrefix(base, "http://") && !strings.HasPrefix(base, "https://") {
		base = "https://" + base
	}

	endpoint := base + "/api/agent/scan-report"

	// Costruisci payload — convertiamo solo gli host raggiungibili o con MAC,
	// per ridurre il rumore (lo scanner produce molti "down" durante lo sweep).
	eps := make([]scanReportEndpoint, 0, len(items))
	for _, r := range items {
		if r == nil {
			continue
		}
		if r.Status != "alive" && r.Status != "arp-only" {
			continue
		}
		ep := scanReportEndpoint{
			IP:            r.IP,
			MAC:           r.MAC,
			Hostname:      r.Hostname,
			Vendor:        r.Vendor,
			DiscoveredVia: "ui_scan",
		}
		if r.RTTms >= 0 {
			ep.RTTms = float64(r.RTTms)
		}
		eps = append(eps, ep)
	}
	if len(eps) == 0 {
		return 0, 0, errors.New("nessun host raggiungibile da inviare (filtra solo alive/arp-only)")
	}

	body, err := json.Marshal(scanReportRequest{
		ClientID:  app.agent.ClientID,
		Subnet:    subnet,
		Endpoints: eps,
	})
	if err != nil {
		return 0, 0, fmt.Errorf("marshal payload: %w", err)
	}

	req, err := http.NewRequest(http.MethodPost, endpoint, bytes.NewReader(body))
	if err != nil {
		return 0, 0, fmt.Errorf("new request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+app.agent.Token)
	req.Header.Set("User-Agent", "86NocAgent-UI/1.0")

	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return 0, 0, fmt.Errorf("POST %s: %w", endpoint, err)
	}
	defer resp.Body.Close()

	rawBody, _ := io.ReadAll(io.LimitReader(resp.Body, 64*1024))

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		// Surface backend detail message if it is JSON {detail: "..."}.
		msg := strings.TrimSpace(string(rawBody))
		if msg == "" {
			msg = resp.Status
		}
		return 0, 0, fmt.Errorf("HTTP %d: %s", resp.StatusCode, msg)
	}

	var parsed scanReportResponse
	if err := json.Unmarshal(rawBody, &parsed); err != nil {
		// Backend ha risposto 2xx ma con body non-JSON: consideriamo successo
		// con 0/0 cosi' l'utente sa che e' stato accettato.
		return len(eps), 0, nil
	}
	return parsed.EndpointsStored, parsed.DevicesAutoAdded, nil
}
