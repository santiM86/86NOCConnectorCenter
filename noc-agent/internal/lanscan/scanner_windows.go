// Package lanscan implementa la scansione LAN streaming usata dalla UI
// Desktop v5 (Wails). E' un porting deliberatamente snellito del vecchio
// `cmd/nocui/scanner_windows.go` senza le dipendenze da lxn/walk.
//
// Caratteristiche:
//   - ICMP nativo via IcmpSendEcho2 (zero CreateProcess overhead).
//   - ARP cache snapshot in pre+post scan.
//   - NBNS + reverse DNS enrichment in background goroutine.
//   - Streaming callback `onResult` invocato per ogni device trovato.
//   - Niente chiamate UI: completamente disaccoppiato dal frontend.
//
//go:build windows

package lanscan

import (
	"context"
	"fmt"
	"net"
	"os/exec"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"github.com/86bit/noc-agent/internal/nbns"
)

// Result rappresenta un dispositivo trovato sulla LAN.
type Result struct {
	IP         string   `json:"ip"`
	MAC        string   `json:"mac,omitempty"`
	Hostname   string   `json:"hostname,omitempty"`
	Vendor     string   `json:"vendor,omitempty"`
	Status     string   `json:"status"` // "alive" | "arp-only"
	RTTms      int      `json:"rtt_ms"` // -1 = non risposto
	MDNSName   string   `json:"mdns_name,omitempty"`
	Services   []string `json:"services,omitempty"`
	HTTPServer string   `json:"http_server,omitempty"`
}

// Progress traccia lo stato avanzamento per la UI.
type Progress struct {
	Done  int `json:"done"`
	Total int `json:"total"`
	Found int `json:"found"`
}

// DetectLocalCIDR ritorna la prima /24 privata trovata sulle interfacce locali.
func DetectLocalCIDR() string {
	addrs, err := net.InterfaceAddrs()
	if err != nil {
		return "192.168.1.0/24"
	}
	for _, a := range addrs {
		ipNet, ok := a.(*net.IPNet)
		if !ok || ipNet.IP.IsLoopback() {
			continue
		}
		ip4 := ipNet.IP.To4()
		if ip4 == nil {
			continue
		}
		if !(ip4[0] == 10 ||
			(ip4[0] == 172 && ip4[1] >= 16 && ip4[1] <= 31) ||
			(ip4[0] == 192 && ip4[1] == 168)) {
			continue
		}
		return fmt.Sprintf("%d.%d.%d.0/24", ip4[0], ip4[1], ip4[2])
	}
	return "192.168.1.0/24"
}

// expandCIDR ritorna ogni IP host del CIDR (IPv4 solo).
func expandCIDR(cidr string) ([]string, error) {
	_, ipNet, err := net.ParseCIDR(cidr)
	if err != nil {
		return nil, err
	}
	if ipNet.IP.To4() == nil {
		return nil, fmt.Errorf("solo IPv4 supportato")
	}
	ones, bits := ipNet.Mask.Size()
	if bits-ones > 16 {
		return nil, fmt.Errorf("range troppo ampio (max /16)")
	}
	var out []string
	ip := ipNet.IP.Mask(ipNet.Mask).To4()
	start := uint32(ip[0])<<24 | uint32(ip[1])<<16 | uint32(ip[2])<<8 | uint32(ip[3])
	size := uint32(1) << uint(bits-ones)
	skipNet := bits-ones >= 2
	for i := uint32(0); i < size; i++ {
		if skipNet && (i == 0 || i == size-1) {
			continue
		}
		v := start + i
		out = append(out, fmt.Sprintf("%d.%d.%d.%d",
			byte(v>>24), byte(v>>16), byte(v>>8), byte(v)))
	}
	return out, nil
}

func cidrContains(cidr, ip string) bool {
	_, ipNet, err := net.ParseCIDR(cidr)
	if err != nil {
		return false
	}
	parsed := net.ParseIP(ip)
	if parsed == nil {
		return false
	}
	return ipNet.Contains(parsed)
}

func ipNumeric(s string) uint32 {
	ip := net.ParseIP(s).To4()
	if ip == nil {
		return 0
	}
	return uint32(ip[0])<<24 | uint32(ip[1])<<16 | uint32(ip[2])<<8 | uint32(ip[3])
}

// readARPTable esegue `arp -a` e ritorna mappa ip->mac.
func readARPTable(ctx context.Context) map[string]string {
	out := map[string]string{}
	cmd := exec.CommandContext(ctx, "arp", "-a")
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	data, err := cmd.Output()
	if err != nil {
		return out
	}
	for _, line := range strings.Split(string(data), "\n") {
		fields := strings.Fields(line)
		if len(fields) < 2 {
			continue
		}
		ip := fields[0]
		if net.ParseIP(ip) == nil {
			continue
		}
		for _, tok := range fields[1:] {
			t := strings.ToLower(strings.ReplaceAll(tok, "-", ":"))
			if isMAC17(t) && t != "ff:ff:ff:ff:ff:ff" && t != "00:00:00:00:00:00" {
				out[ip] = t
				break
			}
		}
	}
	return out
}

func isMAC17(s string) bool {
	if len(s) != 17 {
		return false
	}
	for i := 0; i < 17; i++ {
		c := s[i]
		if (i+1)%3 == 0 {
			if c != ':' {
				return false
			}
			continue
		}
		if !((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')) {
			return false
		}
	}
	return true
}

func reverseDNS(ctx context.Context, ip string) string {
	r := net.Resolver{}
	cctx, cancel := context.WithTimeout(ctx, 600*time.Millisecond)
	defer cancel()
	names, err := r.LookupAddr(cctx, ip)
	if err != nil || len(names) == 0 {
		return ""
	}
	return strings.TrimSuffix(names[0], ".")
}

// Run avvia la scansione del CIDR. Streamma i risultati via onResult
// e l'avanzamento via onProgress. Ritorna l'elenco completo a fine scan.
// Cancellabile via ctx.
func Run(
	ctx context.Context,
	cidr string,
	onProgress func(Progress),
	onResult func(Result),
) (results []Result, err error) {
	defer func() {
		if rv := recover(); rv != nil {
			err = fmt.Errorf("scan panic recovered: %v", rv)
		}
	}()

	ips, err := expandCIDR(cidr)
	if err != nil {
		return nil, err
	}
	total := len(ips)
	if total > 4096 {
		return nil, fmt.Errorf("range troppo ampio (%d IP). Usa /20 o piu' piccolo", total)
	}

	ctxScan, cancelScan := context.WithTimeout(ctx, 30*time.Second)
	defer cancelScan()

	var (
		mu      sync.Mutex
		found   = map[string]*Result{}
		doneCnt int32
	)

	// Phase 0-mDNS: lancio multicast discovery in goroutine separata.
	// I risultati arrivano in 1-3s e popolano la mappa shared. Quando
	// l'enrich di un IP gira, usa eventuali hint mDNS (hostname .local,
	// servizi annunciati) per arricchire l'output.
	var mdnsMu sync.RWMutex
	mdnsMap := map[string]mdnsInfo{}
	var mdnsWg sync.WaitGroup
	mdnsWg.Add(1)
	go func() {
		defer mdnsWg.Done()
		defer func() { _ = recover() }()
		m := discoverMDNS(ctxScan)
		mdnsMu.Lock()
		for ip, info := range m {
			mdnsMap[ip] = info
		}
		mdnsMu.Unlock()
	}()

	emit := func(r Result) {
		if r.IP == "" {
			return
		}
		if p := net.ParseIP(strings.TrimSpace(r.IP)); p != nil {
			if v4 := p.To4(); v4 != nil {
				r.IP = v4.String()
			}
		}
		mu.Lock()
		if prev, ok := found[r.IP]; ok {
			if r.Hostname == "" {
				r.Hostname = prev.Hostname
			}
			if r.MAC == "" {
				r.MAC = prev.MAC
			}
			if r.Vendor == "" {
				r.Vendor = prev.Vendor
			}
			if r.MDNSName == "" {
				r.MDNSName = prev.MDNSName
			}
			if len(r.Services) == 0 {
				r.Services = prev.Services
			}
			if r.HTTPServer == "" {
				r.HTTPServer = prev.HTTPServer
			}
			if r.Status == "arp-only" && prev.Status == "alive" {
				r.Status = prev.Status
				r.RTTms = prev.RTTms
			}
		} else {
			results = append(results, r)
		}
		copied := r
		found[r.IP] = &copied
		mu.Unlock()
		if onResult != nil {
			func() {
				defer func() { _ = recover() }()
				onResult(copied)
			}()
		}
	}

	bumpProgress := func() {
		n := atomic.AddInt32(&doneCnt, 1)
		if onProgress != nil && (n%2 == 0 || int(n) == total) {
			mu.Lock()
			fnd := len(found)
			mu.Unlock()
			func() {
				defer func() { _ = recover() }()
				onProgress(Progress{Done: int(n), Total: total, Found: fnd})
			}()
		}
	}

	// Phase 0: ARP cache snapshot.
	arp := readARPTable(ctxScan)
	for ip, mac := range arp {
		if !cidrContains(cidr, ip) {
			continue
		}
		emit(Result{
			IP:     ip,
			MAC:    mac,
			Vendor: ouiVendor(mac),
			Status: "alive",
			RTTms:  1,
		})
	}

	// Enrichment goroutine: NBNS + reverse DNS + HTTP banner + mDNS in
	// background per ogni IP scoperto.
	var enrichWg sync.WaitGroup
	enrich := func(ip string) {
		enrichWg.Add(1)
		go func() {
			defer enrichWg.Done()
			defer func() { _ = recover() }()
			host := ""
			macFromNbns := ""
			if info, e := nbns.Query(ip, 400*time.Millisecond); e == nil && info != nil {
				host = info.ComputerName
				macFromNbns = info.MAC
			}
			if host == "" {
				host = reverseDNS(ctxScan, ip)
			}

			// mDNS lookup (no-op se discovery non ancora ritornato)
			var mdnsName string
			var services []string
			mdnsMu.RLock()
			if mi, ok := mdnsMap[ip]; ok {
				mdnsName = mi.Hostname
				services = mi.Services
			}
			mdnsMu.RUnlock()
			if host == "" && mdnsName != "" {
				host = mdnsName
			}

			// HTTP banner probe (best-effort, <500ms total)
			httpSrv := httpBanner(ctxScan, ip, 500*time.Millisecond)

			if host == "" && macFromNbns == "" && mdnsName == "" && httpSrv == "" {
				return
			}
			mu.Lock()
			prev := found[ip]
			mu.Unlock()
			status := "alive"
			rtt := -1
			if prev != nil {
				status = prev.Status
				rtt = prev.RTTms
			}
			emit(Result{
				IP:         ip,
				Hostname:   host,
				MAC:        macFromNbns,
				Vendor:     ouiVendor(macFromNbns),
				Status:     status,
				RTTms:      rtt,
				MDNSName:   mdnsName,
				Services:   services,
				HTTPServer: httpSrv,
			})
		}()
	}

	mu.Lock()
	enrichedIPs := make([]string, 0, len(found))
	for ip := range found {
		enrichedIPs = append(enrichedIPs, ip)
	}
	mu.Unlock()
	for _, ip := range enrichedIPs {
		enrich(ip)
	}

	// Phase 1: burst ICMP nativo, sem 64.
	sem := make(chan struct{}, 64)
	var pingWg sync.WaitGroup
	for _, ip := range ips {
		ip := ip
		select {
		case <-ctxScan.Done():
			goto donePhase1
		default:
		}
		pingWg.Add(1)
		sem <- struct{}{}
		go func() {
			defer pingWg.Done()
			defer func() { <-sem }()
			defer func() { _ = recover() }()

			rtt := probeICMPNative(ctxScan, ip, 150)
			bumpProgress()
			if rtt < 0 {
				return
			}
			mac := ""
			mu.Lock()
			if prev, ok := found[ip]; ok {
				mac = prev.MAC
			} else {
				mac = arp[ip]
			}
			mu.Unlock()
			emit(Result{
				IP:     ip,
				MAC:    mac,
				Vendor: ouiVendor(mac),
				Status: "alive",
				RTTms:  rtt,
			})
			enrich(ip)
		}()
	}
donePhase1:
	pingDone := make(chan struct{})
	go func() {
		defer func() { _ = recover() }()
		pingWg.Wait()
		close(pingDone)
	}()
	select {
	case <-pingDone:
	case <-ctxScan.Done():
	}

	// Phase 2: re-read ARP cache dopo il burst.
	arp2 := readARPTable(ctxScan)
	for ip, mac := range arp2 {
		if !cidrContains(cidr, ip) {
			continue
		}
		mu.Lock()
		_, already := found[ip]
		mu.Unlock()
		if already {
			continue
		}
		emit(Result{
			IP:     ip,
			MAC:    mac,
			Vendor: ouiVendor(mac),
			Status: "arp-only",
			RTTms:  -1,
		})
		enrich(ip)
	}

	// Phase 3: attendi enrichment (best-effort, max 2s).
	enrichDone := make(chan struct{})
	go func() {
		defer func() { _ = recover() }()
		enrichWg.Wait()
		close(enrichDone)
	}()
	select {
	case <-enrichDone:
	case <-time.After(2 * time.Second):
	case <-ctxScan.Done():
	}
	// mDNS goroutine completion (no-block: ha gia' timeout 3s interno)
	mdnsWg.Wait()

	mu.Lock()
	out := make([]Result, len(results))
	for i, r := range results {
		if fr, ok := found[r.IP]; ok && fr != nil {
			out[i] = *fr
		} else {
			out[i] = r
		}
	}
	mu.Unlock()
	sort.Slice(out, func(i, j int) bool { return ipNumeric(out[i].IP) < ipNumeric(out[j].IP) })

	if ctxScan.Err() == context.DeadlineExceeded {
		return out, fmt.Errorf("scan timeout dopo 30s (risultati parziali: %d)", len(out))
	}
	return out, nil
}
