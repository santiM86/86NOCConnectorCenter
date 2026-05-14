// Stub non-Windows: la UI Wails è solo Windows. Tutta la build cross-platform
// (Linux CI, dev locale) deve compilare il package come no-op.
//
//go:build !windows

package lanscan

import (
	"context"
	"errors"
)

// Result rappresenta un dispositivo trovato sulla LAN.
type Result struct {
	IP       string `json:"ip"`
	MAC      string `json:"mac,omitempty"`
	Hostname string `json:"hostname,omitempty"`
	Vendor   string `json:"vendor,omitempty"`
	Status   string `json:"status"`
	RTTms    int    `json:"rtt_ms"`
}

// Progress traccia lo stato avanzamento per la UI.
type Progress struct {
	Done  int `json:"done"`
	Total int `json:"total"`
	Found int `json:"found"`
}

// DetectLocalCIDR è no-op fuori da Windows.
func DetectLocalCIDR() string { return "192.168.1.0/24" }

// Run è no-op fuori da Windows.
func Run(ctx context.Context, cidr string, onProgress func(Progress), onResult func(Result)) ([]Result, error) {
	return nil, errors.New("lanscan: supportato solo su Windows")
}

// CloseIcmpHandle è no-op fuori da Windows.
func CloseIcmpHandle() {}
