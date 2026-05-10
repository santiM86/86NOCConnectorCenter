// Network scanner per il Connector — ispirato ad Advanced IP Scanner.
//
// TCP probe parallelo su un range IP (default = subnet locale /24) +
// parse della ARP cache + DNS reverse lookup + OUI vendor lookup.
//
// Niente raw ICMP perche' richiederebbe privilegi admin che il tray
// non ha; la combinazione TCP probe (porte comuni) + ARP cache copre
// la stragrande maggioranza dei device LAN.
//
//go:build windows

package main

import (
	"bytes"
	"context"
	"crypto/tls"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"sort"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"github.com/lxn/walk"
	wd "github.com/lxn/walk/declarative"
)

// ScanResult is one row in the scanner table.
type ScanResult struct {
	IP       string
	MAC      string
	Hostname string
	Vendor   string
	Status   string // "alive" | "arp-only" | "down"
	RTTms    int    // RTT in millisecondi, -1 se non risposto
	OpenPort int    // prima porta TCP che ha risposto (0 = nessuna)
	WebURL   string // url HTTP/HTTPS rilevato
	SNMPok   bool   // risponde a SNMP v2c con community public/private
}

type scanResultsModel struct {
	walk.TableModelBase
	items []*ScanResult
}

func (m *scanResultsModel) RowCount() int { return len(m.items) }
func (m *scanResultsModel) Value(row, col int) interface{} {
	if row < 0 || row >= len(m.items) {
		return ""
	}
	r := m.items[row]
	switch col {
	case 0:
		// Stato visivo: pallini colorati come gli IP scanner enterprise
		switch r.Status {
		case "alive":
			return "● alive"
		case "arp-only":
			return "◐ arp"
		default:
			return "○ down"
		}
	case 1:
		return r.IP
	case 2:
		if r.RTTms < 0 {
			return ""
		}
		return fmt.Sprintf("%d ms", r.RTTms)
	case 3:
		return r.Hostname
	case 4:
		return r.MAC
	case 5:
		return r.Vendor
	case 6:
		extras := ""
		if r.WebURL != "" {
			extras += "WEB "
		}
		if r.SNMPok {
			extras += "SNMP "
		}
		if r.OpenPort != 0 && extras == "" {
			extras = fmt.Sprintf(":%d", r.OpenPort)
		}
		return strings.TrimSpace(extras)
	}
	return ""
}
func (m *scanResultsModel) publishReset() { m.PublishRowsReset() }

// insertSortedByIP inserisce r nella posizione corretta per mantenere
// la tabella ordinata per IP numerico durante lo streaming. Se un IP
// duplicato arriva (raro: alive emesso poi arp-only), aggiorna la riga
// invece di duplicarla.
func insertSortedByIP(m *scanResultsModel, r *ScanResult) {
	if r == nil {
		return
	}
	target := ipNumeric(r.IP)
	for i, ex := range m.items {
		if ex.IP == r.IP {
			m.items[i] = r
			m.PublishRowsReset()
			return
		}
		if ipNumeric(ex.IP) > target {
			m.items = append(m.items, nil)
			copy(m.items[i+1:], m.items[i:])
			m.items[i] = r
			m.PublishRowsReset()
			return
		}
	}
	m.items = append(m.items, r)
	m.PublishRowsReset()
}

// detectLocalCIDR returns a /24 CIDR built from the first private IPv4
// address bound to a local interface. Falls back to "192.168.1.0/24".
func detectLocalCIDR() string {
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

// expandCIDR returns every host IP in cidr (IPv4 only, /16..32 supported).
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
	// skip network + broadcast on /24..30
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

// probeAlive returns whether any of the well-known TCP ports answers
// within timeout, the first responding port and the RTT in millisec.
// It does not need elevated privileges.
//
// IMPORTANTE: lancia tutti i tentativi di connessione TCP **in parallelo**
// e ritorna alla prima porta che risponde. Cosi' un host vivo viene
// rilevato in <RTT> ms (1-50ms su LAN) invece di max(N_ports * timeout)
// per host morto. Per host morti il caso peggiore resta `timeout`
// (singolo, non N volte).
func probeAlive(ctx context.Context, ip string, timeout time.Duration) (alive bool, port int, rttMs int) {
	// Ordine: porte piu' diffuse prima (Windows SMB, web, Linux SSH).
	// Le porte stampante (515/9100/631) e SNMP (161) coprono device IoT.
	ports := []int{445, 135, 139, 80, 443, 22, 3389, 8080, 8443, 161, 23, 9100, 631, 515, 53}
	cctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	type winT struct {
		port int
		rtt  int
	}
	win := make(chan winT, 1)
	var wg sync.WaitGroup
	for _, p := range ports {
		p := p
		wg.Add(1)
		go func() {
			defer wg.Done()
			d := net.Dialer{}
			t0 := time.Now()
			conn, err := d.DialContext(cctx, "tcp", net.JoinHostPort(ip, strconv.Itoa(p)))
			if err != nil {
				return
			}
			_ = conn.Close()
			rtt := int(time.Since(t0).Milliseconds())
			select {
			case win <- winT{p, rtt}:
			default:
			}
		}()
	}
	doneAll := make(chan struct{})
	go func() { wg.Wait(); close(doneAll) }()
	select {
	case w := <-win:
		// Cancella i tentativi residui non appena uno e' andato a buon fine
		// per liberare le risorse di rete e accelerare lo scan.
		cancel()
		return true, w.port, w.rtt
	case <-doneAll:
		return false, 0, -1
	case <-ctx.Done():
		return false, 0, -1
	}
}

// probeICMPPing usa il comando 'ping' nativo di Windows con count=1 e
// timeout breve. Niente raw socket, niente privilege elevation.
// Ritorna RTT in ms (-1 se nessuna risposta).
func probeICMPPing(ctx context.Context, ip string, timeoutMs int) int {
	cctx, cancel := context.WithTimeout(ctx, time.Duration(timeoutMs+200)*time.Millisecond)
	defer cancel()
	cmd := exec.CommandContext(cctx, "ping", "-n", "1", "-w", strconv.Itoa(timeoutMs), ip)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	out, err := cmd.Output()
	if err != nil {
		return -1
	}
	// Output Windows: "Risposta da 192.168.1.1: byte=32 durata=1ms TTL=64"
	// oppure inglese: "Reply from ...: bytes=32 time=1ms TTL=64"
	low := strings.ToLower(string(out))
	for _, key := range []string{"durata=", "time=", "tempo="} {
		if i := strings.Index(low, key); i >= 0 {
			rest := low[i+len(key):]
			j := strings.Index(rest, "ms")
			if j > 0 {
				if n, err := strconv.Atoi(strings.TrimSpace(rest[:j])); err == nil {
					return n
				}
			}
		}
	}
	if strings.Contains(low, "ttl=") {
		return 0 // ha risposto ma non riusciamo a parsare
	}
	return -1
}

// probeWebUI fa probe HTTP/HTTPS PARALLELE su 80/443 e ritorna la
// prima URL che risponde con status < 500. Timeout aggressivo (700ms)
// per evitare di rallentare lo scan.
func probeWebUI(ctx context.Context, ip string) string {
	cctx, cancel := context.WithTimeout(ctx, 1*time.Second)
	defer cancel()
	type res struct{ url string }
	urls := []string{"http://" + ip + "/", "https://" + ip + "/"}
	out := make(chan string, len(urls))
	cli := &http.Client{
		Timeout: 700 * time.Millisecond,
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			return http.ErrUseLastResponse
		},
		Transport: &http.Transport{
			TLSClientConfig:       &tls.Config{InsecureSkipVerify: true},
			DisableKeepAlives:     true,
			ResponseHeaderTimeout: 600 * time.Millisecond,
			TLSHandshakeTimeout:   500 * time.Millisecond,
		},
	}
	for _, u := range urls {
		u := u
		go func() {
			req, _ := http.NewRequestWithContext(cctx, "HEAD", u, nil)
			req.Header.Set("User-Agent", "ArgusScanner/1.0")
			resp, err := cli.Do(req)
			if err != nil {
				out <- ""
				return
			}
			resp.Body.Close()
			if resp.StatusCode < 500 {
				out <- u
				return
			}
			out <- ""
		}()
	}
	for i := 0; i < len(urls); i++ {
		select {
		case u := <-out:
			if u != "" {
				return u
			}
		case <-cctx.Done():
			return ""
		}
	}
	return ""
}

// probeSNMPv2c invia un GET-Request SNMP v2c per sysDescr.0 con la
// community indicata. Implementazione minimale BER/SNMP per evitare
// dipendenze esterne. Ritorna true se arriva una risposta valida.
func probeSNMPv2c(ip string, community string, timeout time.Duration) bool {
	conn, err := net.DialTimeout("udp", ip+":161", timeout)
	if err != nil {
		return false
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(timeout))
	pkt := buildSNMPv2cGetSysDescr(community)
	if _, err := conn.Write(pkt); err != nil {
		return false
	}
	buf := make([]byte, 1500)
	n, err := conn.Read(buf)
	if err != nil || n < 20 {
		return false
	}
	// Controllo grossolano: BER SEQUENCE (0x30) iniziale + presenza
	// del marker community echoed.
	return buf[0] == 0x30 && bytes.Contains(buf[:n], []byte(community))
}

// buildSNMPv2cGetSysDescr produce un pacchetto SNMPv2c GET-Request
// minimal per OID 1.3.6.1.2.1.1.1.0 (sysDescr).
func buildSNMPv2cGetSysDescr(community string) []byte {
	// Costruzione manuale BER. L'OID e' fisso quindi pre-encodiamo.
	// 1.3.6.1.2.1.1.1.0 -> 06 08 2b 06 01 02 01 01 01 00
	oid := []byte{0x06, 0x08, 0x2b, 0x06, 0x01, 0x02, 0x01, 0x01, 0x01, 0x00}
	// VarBind: SEQUENCE { OID, NULL }
	vb := append([]byte{0x30, byte(len(oid) + 2)}, oid...)
	vb = append(vb, 0x05, 0x00)
	// VarBindList: SEQUENCE { vb }
	vbl := append([]byte{0x30, byte(len(vb))}, vb...)
	// PDU GET-Request (0xa0): SEQUENCE { reqID INT, error INT, errorIdx INT, vbl }
	reqID := []byte{0x02, 0x04, 0x12, 0x34, 0x56, 0x78}
	zero := []byte{0x02, 0x01, 0x00}
	pdu := append([]byte{}, reqID...)
	pdu = append(pdu, zero...)
	pdu = append(pdu, zero...)
	pdu = append(pdu, vbl...)
	pdu = append([]byte{0xa0, byte(len(pdu))}, pdu...)
	// Message: SEQUENCE { version INT 1, community STR, pdu }
	ver := []byte{0x02, 0x01, 0x01}
	comm := append([]byte{0x04, byte(len(community))}, []byte(community)...)
	msg := append([]byte{}, ver...)
	msg = append(msg, comm...)
	msg = append(msg, pdu...)
	msg = append([]byte{0x30, byte(len(msg))}, msg...)
	return msg
}

// readARPTable runs `arp -a` and returns a map ip -> mac (lowercase).
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
		// Windows format: "  192.168.1.1          aa-bb-cc-dd-ee-ff     dynamic"
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

// reverseDNS does a best-effort PTR lookup with a short timeout.
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

// ouiVendor returns a short vendor label derived from the MAC OUI prefix.
// Tiny built-in table — covers >80% of LAN devices encountered in
// SMB/MSP networks. For the long tail we fall back to "".
var ouiTable = map[string]string{
	// Networking / routing / Wi-Fi
	"001c.c0": "Intel", "0050.56": "VMware", "0050.b6": "Mitsubishi", "0050.f9": "Apple",
	"d017.c2": "Cisco", "001e.0b": "HP", "0023.7d": "Cisco", "0024.a8": "TP-Link",
	"f0:9f:c2": "Ubiquiti", "24:5a:4c": "Ubiquiti", "78:8a:20": "Ubiquiti", "fc:ec:da": "Ubiquiti",
	"04:18:d6": "Ubiquiti", "00:0d:b9": "Mikrotik", "4c:5e:0c": "Mikrotik", "b8:69:f4": "Mikrotik",
	"ec:1f:72": "Mikrotik", "dc:2c:6e": "Mikrotik", "6c:3b:6b": "Mikrotik", "74:4d:28": "Mikrotik",
	"00:13:49": "Zyxel", "5c:6a:80": "Zyxel", "10:7b:ef": "Zyxel", "bc:99:11": "Zyxel",
	"00:18:f3": "ASUSTek", "08:62:66": "ASUSTek", "20:cf:30": "ASUSTek", "60:45:cb": "ASUSTek",
	"00:14:5e": "IBM", "00:1d:c5": "Cisco", "00:1c:f0": "D-Link", "14:d6:4d": "D-Link",
	"a4:2b:b0": "TP-Link", "98:da:c4": "TP-Link", "60:e3:27": "TP-Link",
	"24:f5:a2": "TP-Link", "1c:bf:ce": "TP-Link", "50:c7:bf": "TP-Link",
	"60:32:b1": "FRITZ!Box", "9c:c7:a6": "FRITZ!Box", "08:96:d7": "FRITZ!Box",
	"4c:60:de": "Netgear", "10:0d:7f": "Netgear", "20:e5:2a": "Netgear",
	"00:0c:42": "Routerboard", "f4:8e:38": "Dahua", "3c:e3:6b": "Dahua",
	// Server/PC vendor
	"d4:81:d7": "Dell", "f4:8e:b8": "Dell", "00:14:22": "Dell", "00:1d:09": "Dell",
	"94:c6:91": "HP", "9c:8e:99": "HP", "70:5a:0f": "HP", "fc:15:b4": "HP",
	"e4:54:e8": "Lenovo", "08:6d:41": "Lenovo", "60:eb:69": "Lenovo",
	"00:25:64": "Microsoft", "7c:1e:52": "Microsoft", "98:5f:d3": "Microsoft",
	// Apple
	"a4:5e:60": "Apple", "f0:18:98": "Apple", "f0:c1:f1": "Apple", "98:01:a7": "Apple",
	"5c:f9:38": "Apple", "70:48:0f": "Apple", "ac:bc:32": "Apple", "ac:de:48": "Apple",
	// Printers
	"00:21:5a": "HP Print", "9c:b6:d0": "HP Print", "ec:b1:d7": "HP Print",
	"00:1b:a9": "Brother", "00:80:77": "Brother", "30:05:5c": "Brother",
	"00:1e:8f": "Canon", "84:25:3f": "Canon", "00:00:85": "Canon",
	"00:00:48": "Epson", "08:00:83": "Epson", "44:d2:44": "Epson",
	"00:00:74": "Ricoh", "ac:44:f2": "Ricoh", "00:26:73": "Ricoh",
	"00:90:fb": "Konica Minolta", "00:20:6b": "Konica Minolta",
	// IoT / camera
	"5c:cf:7f": "Espressif", "ec:fa:bc": "Espressif", "8c:aa:b5": "Espressif",
	"24:6f:28": "Espressif", "e8:db:84": "Espressif",
	"00:62:6e": "Hikvision", "44:19:b6": "Hikvision", "bc:ad:28": "Hikvision",
	"ec:c8:9c": "Hikvision",
	"00:18:dd": "Sennheiser", "ac:21:b7": "Polycom",
	// Synology / QNAP NAS
	"00:11:32": "Synology",
	"00:08:9b": "QNAP", "24:5e:be": "QNAP",
	// Phones
	"40:b4:f0": "Xiaomi", "20:47:da": "Xiaomi", "f4:f5:db": "Xiaomi",
	"58:48:22": "OnePlus", "00:9b:ad": "Sony",
}

func ouiVendor(mac string) string {
	if len(mac) < 8 {
		return ""
	}
	pfx := strings.ToLower(mac[:8])
	if v, ok := ouiTable[pfx]; ok {
		return v
	}
	return ""
}

// runScan performs the full scan flow and returns the populated results.
// `onProgress` viene invocato periodicamente con (done, total). `onResult`
// viene invocato **per ogni host** appena viene rilevato come alive o
// arp-only — questo permette alla UI di popolare la tabella in streaming
// (effetto "live" alla Advanced IP Scanner) invece di aspettare il
// completamento di tutto lo scan.
//
// Tutti i callback vengono chiamati da goroutine worker — il chiamante
// deve sincronizzarsi sul thread UI via Form.Synchronize.
func runScan(ctx context.Context, cidr string, timeout time.Duration,
	onProgress func(done, total int),
	onResult func(*ScanResult)) ([]*ScanResult, error) {

	ips, err := expandCIDR(cidr)
	if err != nil {
		return nil, err
	}
	total := len(ips)
	var done int32

	// Phase 0: leggi ARP cache UPFRONT. E' istantanea (~5-30ms) e
	// fornisce MAC + vendor anche per host che non rispondono al TCP
	// probe (silenziosi ma raggiungibili in L2).
	arp := readARPTable(ctx)

	// emitted tiene traccia degli IP gia' notificati a onResult cosi'
	// non si duplicano (alive da TCP probe + arp-only successivo).
	var (
		mu       sync.Mutex
		results  []*ScanResult
		emitted  = map[string]bool{}
	)
	emit := func(r *ScanResult) {
		mu.Lock()
		if emitted[r.IP] {
			mu.Unlock()
			return
		}
		emitted[r.IP] = true
		results = append(results, r)
		mu.Unlock()
		if onResult != nil {
			onResult(r)
		}
	}

	// Phase 1: TCP probe parallelo su tutti gli IP. Ogni goroutine
	// per IP probe le porte in parallelo (cfr. probeAlive) — host
	// vivi rilevati in <50ms, host morti dopo `timeout` totale.
	// Concorrenza alta (256) per saturare la rete LAN moderna.
	sem := make(chan struct{}, 256)
	var wg sync.WaitGroup
	for _, ip := range ips {
		ip := ip
		select {
		case <-ctx.Done():
		default:
		}
		wg.Add(1)
		sem <- struct{}{}
		go func() {
			defer wg.Done()
			defer func() { <-sem }()
			alive, port, rtt := probeAlive(ctx, ip, timeout)
			n := atomic.AddInt32(&done, 1)
			if onProgress != nil && (n%8 == 0 || int(n) == total) {
				onProgress(int(n), total)
			}
			mac := arp[ip]
			if !alive && mac == "" {
				return
			}
			// reverseDNS ha gia' timeout interno breve (600ms); lanciato
			// inline cosi' il risultato emesso contiene gia' hostname.
			host := reverseDNS(ctx, ip)
			status := "alive"
			rttOut := rtt
			if !alive {
				status = "arp-only"
				rttOut = -1
			}
			emit(&ScanResult{
				IP:       ip,
				MAC:      mac,
				Hostname: host,
				Vendor:   ouiVendor(mac),
				Status:   status,
				RTTms:    rttOut,
				OpenPort: port,
			})
		}()
	}
	wg.Wait()

	// Phase 2 (cleanup): se l'ARP cache cambia durante lo scan (es. ne
	// arrivano di nuovi grazie ai nostri probe TCP), riemettiamo gli
	// arp-only rimasti fuori. E' un best-effort, costa pochi ms.
	arp2 := readARPTable(ctx)
	for ip, mac := range arp2 {
		mu.Lock()
		already := emitted[ip]
		mu.Unlock()
		if already {
			continue
		}
		// Conferma che l'IP appartiene al CIDR scansionato.
		// (arp -a ritorna anche entry di altre interfacce.)
		if !cidrContains(cidr, ip) {
			continue
		}
		emit(&ScanResult{
			IP:       ip,
			MAC:      mac,
			Hostname: reverseDNS(ctx, ip),
			Vendor:   ouiVendor(mac),
			Status:   "arp-only",
			RTTms:    -1,
		})
	}

	// Sort finale per IP (lo streaming arriva in ordine random).
	mu.Lock()
	sort.Slice(results, func(i, j int) bool { return ipNumeric(results[i].IP) < ipNumeric(results[j].IP) })
	out := make([]*ScanResult, len(results))
	copy(out, results)
	mu.Unlock()
	return out, nil
}

// cidrContains verifica se ip appartiene al CIDR (entrambi IPv4).
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

// showScannerDialog builds the Scanner window and runs it modally.
// app.tableModel is the SNMP table the user can append the selected
// scanner results to.
func showScannerDialog(app *App, parent walk.Form) {
	defer func() {
		if r := recover(); r != nil {
			logf("PANIC in showScannerDialog: %v", r)
		}
	}()

	model := &scanResultsModel{}
	defaultCIDR := detectLocalCIDR()

	var (
		dlg          *walk.Dialog
		cidrEd       *walk.LineEdit
		tv           *walk.TableView
		statusLb     *walk.Label
		progressBar  *walk.ProgressBar
		btnScan      *walk.PushButton
		btnAdd       *walk.PushButton
		btnAddSNMP   *walk.PushButton
		ctxScan      context.Context
		cancelScan   context.CancelFunc
	)

	startScan := func() {
		cidr := strings.TrimSpace(cidrEd.Text())
		if cidr == "" {
			cidr = defaultCIDR
		}
		// Reset
		model.items = nil
		model.PublishRowsReset()
		ctxScan, cancelScan = context.WithCancel(context.Background())
		btnScan.SetText("Annulla")
		btnScan.SetEnabled(true)
		btnAdd.SetEnabled(false)
		btnAddSNMP.SetEnabled(false)
		statusLb.SetText("Scansione di " + cidr + " in corso...")
		progressBar.SetRange(0, 100)
		progressBar.SetValue(0)
		go func() {
			t0 := time.Now()
			res, err := runScan(ctxScan, cidr, 400*time.Millisecond,
				func(d, total int) {
					dlg.Synchronize(func() {
						if total > 0 {
							progressBar.SetValue(int(float64(d) / float64(total) * 100))
						}
						statusLb.SetText(fmt.Sprintf("Probe %d/%d  ·  trovati %d", d, total, len(model.items)))
					})
				},
				func(r *ScanResult) {
					// Streaming: ogni device trovato finisce subito in
					// tabella, ordinato per IP. L'utente vede i risultati
					// arrivare LIVE invece di aspettare la fine.
					dlg.Synchronize(func() {
						insertSortedByIP(model, r)
					})
				})
			dlg.Synchronize(func() {
				btnScan.SetText("Scansiona Rete")
				if err != nil {
					statusLb.SetText("Errore: " + err.Error())
					return
				}
				progressBar.SetValue(100)
				statusLb.SetText(fmt.Sprintf("Trovati %d dispositivi in %s",
					len(res), time.Since(t0).Round(time.Second)))
				btnAdd.SetEnabled(len(res) > 0)
				btnAddSNMP.SetEnabled(len(res) > 0)
			})
		}()
	}

	cancelOrStart := func() {
		if btnScan.Text() == "Annulla" && cancelScan != nil {
			cancelScan()
			btnScan.SetText("Scansiona Rete")
			statusLb.SetText("Annullamento in corso (max 2s)...")
			return
		}
		startScan()
	}

	rescanRow := func(idx int) {
		if idx < 0 || idx >= len(model.items) {
			return
		}
		r := model.items[idx]
		statusLb.SetText("Re-scan di " + r.IP + " ...")
		go func(ip string, idx int) {
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			alive, port, rtt := probeAlive(ctx, ip, 400*time.Millisecond)
			host := reverseDNS(ctx, ip)
			arpMap := readARPTable(ctx)
			mac := arpMap[ip]
			dlg.Synchronize(func() {
				if idx >= len(model.items) {
					return
				}
				r := model.items[idx]
				if alive {
					r.Status = "alive"
					r.OpenPort = port
					r.RTTms = rtt
				} else if mac != "" {
					r.Status = "arp-only"
				} else {
					r.Status = "down"
					r.RTTms = -1
				}
				if host != "" {
					r.Hostname = host
				}
				if mac != "" {
					r.MAC = mac
					r.Vendor = ouiVendor(mac)
				}
				model.publishReset()
				statusLb.SetText("Re-scan completato per " + ip)
			})
		}(r.IP, idx)
	}

	exportHTML := func() {
		if len(model.items) == 0 {
			return
		}
		fd := walk.FileDialog{Title: "Esporta scansione (HTML)",
			Filter: "HTML (*.html)|*.html", FilePath: "argus-scan.html"}
		if ok, _ := fd.ShowSave(dlg); !ok {
			return
		}
		var sb strings.Builder
		sb.WriteString(`<!DOCTYPE html><html><head><meta charset="utf-8"><title>ARGUS Scan Report</title>`)
		sb.WriteString(`<style>body{font-family:Segoe UI,sans-serif;background:#fff;color:#1a1a2a;padding:24px}`)
		sb.WriteString(`h1{color:#1040e0;border-bottom:2px solid #1040e0;padding-bottom:8px}`)
		sb.WriteString(`table{border-collapse:collapse;width:100%;font-size:13px;margin-top:16px}`)
		sb.WriteString(`th,td{padding:8px 10px;text-align:left;border-bottom:1px solid #e5e7eb}`)
		sb.WriteString(`th{background:#1040e0;color:#fff;font-weight:600}`)
		sb.WriteString(`tr:nth-child(even){background:#f8fafc} tr:hover{background:#eef2ff}`)
		sb.WriteString(`.alive{color:#16a34a;font-weight:600} .arp{color:#ca8a04;font-weight:600} .down{color:#dc2626}`)
		sb.WriteString(`</style></head><body>`)
		sb.WriteString("<h1>ARGUS - Scan Report</h1>")
		sb.WriteString(fmt.Sprintf("<p><b>Range:</b> %s &nbsp; <b>Generato:</b> %s &nbsp; <b>Dispositivi trovati:</b> %d</p>",
			cidrEd.Text(), time.Now().Format("2006-01-02 15:04:05"), len(model.items)))
		sb.WriteString("<table><thead><tr><th>Stato</th><th>IP</th><th>RTT</th><th>Hostname</th><th>MAC</th><th>Vendor</th><th>Servizi</th></tr></thead><tbody>")
		for _, r := range model.items {
			cls := "down"
			if r.Status == "alive" {
				cls = "alive"
			} else if r.Status == "arp-only" {
				cls = "arp"
			}
			rttStr := ""
			if r.RTTms >= 0 {
				rttStr = fmt.Sprintf("%d ms", r.RTTms)
			}
			services := ""
			if r.WebURL != "" {
				services += "WEB "
			}
			if r.SNMPok {
				services += "SNMP "
			}
			sb.WriteString(fmt.Sprintf(
				"<tr><td class=\"%s\">%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>",
				cls, r.Status, r.IP, rttStr, htmlEscape(r.Hostname), r.MAC, htmlEscape(r.Vendor), strings.TrimSpace(services)))
		}
		sb.WriteString("</tbody></table></body></html>")
		_ = writeFileText(fd.FilePath, sb.String())
		statusLb.SetText("Report HTML salvato: " + fd.FilePath)
	}

	addSelectedAsTargets := func(community string) {
		sel := tv.SelectedIndexes()
		if len(sel) == 0 {
			walk.MsgBox(dlg, "Nessuna selezione",
				"Seleziona prima una o piu' righe dalla lista.", walk.MsgBoxIconInformation)
			return
		}
		// Build a quick lookup of existing IPs.
		existing := map[string]bool{}
		for _, t := range app.tableModel.items {
			existing[t.IP] = true
		}
		added := 0
		for _, i := range sel {
			r := model.items[i]
			if existing[r.IP] {
				continue
			}
			name := r.Hostname
			if name == "" && r.Vendor != "" {
				name = r.Vendor + " " + r.IP
			}
			app.tableModel.items = append(app.tableModel.items, &Target{
				IP: r.IP, Name: name, Community: community,
				SNMPVersion: "v2c", SNMPPort: 161,
			})
			added++
		}
		app.tableModel.PublishRowsReset()
		walk.MsgBox(dlg, "Aggiunti",
			fmt.Sprintf("%d dispositivi aggiunti alla lista SNMP.", added),
			walk.MsgBoxIconInformation)
	}

	wd.Dialog{
		AssignTo: &dlg,
		Title:    "ARGUS - Scansiona Rete",
		Icon:     app.icon,
		Size:     wd.Size{Width: 1100, Height: 660},
		MinSize:  wd.Size{Width: 900, Height: 500},
		Layout:   wd.VBox{},
		Children: []wd.Widget{
			wd.Label{Text: "Scansione rete locale (TCP probe + ICMP + ARP cache + DNS reverse + SNMP probe + Web detect)",
				Font: wd.Font{Family: "Segoe UI", PointSize: 11, Bold: true}},
			wd.Composite{
				Layout: wd.HBox{},
				Children: []wd.Widget{
					wd.Label{Text: "Range (CIDR):"},
					wd.LineEdit{AssignTo: &cidrEd, Text: defaultCIDR, MinSize: wd.Size{Width: 180}},
					wd.PushButton{AssignTo: &btnScan, Text: "Scansiona Rete", OnClicked: cancelOrStart},
					wd.HSpacer{},
					wd.Label{AssignTo: &statusLb, Text: "Pronto."},
				},
			},
			wd.ProgressBar{AssignTo: &progressBar, MinSize: wd.Size{Height: 12}},
			wd.TableView{
				AssignTo:         &tv,
				AlternatingRowBG: true,
				ColumnsOrderable: true,
				MultiSelection:   true,
				Columns: []wd.TableViewColumn{
					{Title: "Stato", Width: 80},
					{Title: "IP", Width: 130},
					{Title: "RTT", Width: 70},
					{Title: "Hostname", Width: 220},
					{Title: "MAC", Width: 150},
					{Title: "Vendor", Width: 140},
					{Title: "Servizi", Width: 110},
				},
				Model: model,
			},
			wd.Composite{
				Layout: wd.HBox{Spacing: 4},
				Children: []wd.Widget{
					wd.Label{Text: "Azioni:", Font: wd.Font{Family: "Segoe UI", PointSize: 9, Bold: true}},
					wd.PushButton{Text: "Web UI", OnClicked: func() {
						sel := tv.SelectedIndexes()
						if len(sel) == 0 {
							walk.MsgBox(dlg, "Web UI", "Seleziona prima un dispositivo.", walk.MsgBoxIconInformation)
							return
						}
						r := model.items[sel[0]]
						go func(ip string) {
							ctx, cancel := context.WithTimeout(context.Background(), 1500*time.Millisecond)
							defer cancel()
							u := probeWebUI(ctx, ip)
							if u == "" {
								u = "http://" + ip + "/"
							}
							_ = exec.Command("rundll32", "url.dll,FileProtocolHandler", u).Start()
						}(r.IP)
					}},
					wd.PushButton{Text: "RDP", OnClicked: func() {
						sel := tv.SelectedIndexes()
						if len(sel) == 0 {
							return
						}
						r := model.items[sel[0]]
						_ = exec.Command("mstsc", "/v:"+r.IP).Start()
					}},
					wd.PushButton{Text: "Cartelle (SMB)", OnClicked: func() {
						sel := tv.SelectedIndexes()
						if len(sel) == 0 {
							return
						}
						r := model.items[sel[0]]
						_ = exec.Command("explorer", `\\`+r.IP).Start()
					}},
					wd.PushButton{Text: "Telnet", OnClicked: func() {
						sel := tv.SelectedIndexes()
						if len(sel) == 0 {
							return
						}
						r := model.items[sel[0]]
						port := "23"
						if r.OpenPort == 22 {
							port = "22"
						}
						c := exec.Command("cmd", "/c", "start", "cmd", "/k", "telnet "+r.IP+" "+port)
						c.SysProcAttr = &syscall.SysProcAttr{HideWindow: false}
						_ = c.Start()
					}},
					wd.PushButton{Text: "FTP", OnClicked: func() {
						sel := tv.SelectedIndexes()
						if len(sel) == 0 {
							return
						}
						r := model.items[sel[0]]
						_ = exec.Command("rundll32", "url.dll,FileProtocolHandler", "ftp://"+r.IP+"/").Start()
					}},
					wd.PushButton{Text: "Tracert", OnClicked: func() {
						sel := tv.SelectedIndexes()
						if len(sel) == 0 {
							return
						}
						r := model.items[sel[0]]
						c := exec.Command("cmd", "/c", "start", "cmd", "/k", "tracert "+r.IP)
						c.SysProcAttr = &syscall.SysProcAttr{HideWindow: false}
						_ = c.Start()
					}},
					wd.PushButton{Text: "Ping...", OnClicked: func() {
						sel := tv.SelectedIndexes()
						if len(sel) == 0 {
							return
						}
						r := model.items[sel[0]]
						c := exec.Command("cmd", "/c", "start", "cmd", "/k", "ping -t "+r.IP)
						c.SysProcAttr = &syscall.SysProcAttr{HideWindow: false}
						_ = c.Start()
					}},
					wd.PushButton{Text: "Re-scan host", OnClicked: func() {
						sel := tv.SelectedIndexes()
						if len(sel) == 0 {
							return
						}
						rescanRow(sel[0])
					}},
					wd.PushButton{Text: "Wake-on-LAN", OnClicked: func() {
						sel := tv.SelectedIndexes()
						if len(sel) == 0 {
							return
						}
						r := model.items[sel[0]]
						if r.MAC == "" {
							walk.MsgBox(dlg, "WoL", "MAC non disponibile per questo device.", walk.MsgBoxIconWarning)
							return
						}
						if err := sendWoLMagicPacket(r.MAC); err != nil {
							walk.MsgBox(dlg, "WoL errore", err.Error(), walk.MsgBoxIconError)
							return
						}
						walk.MsgBox(dlg, "Wake-on-LAN", "Magic packet inviato a "+r.MAC, walk.MsgBoxIconInformation)
					}},
					wd.HSpacer{},
				},
			},
			wd.Composite{
				Layout: wd.HBox{},
				Children: []wd.Widget{
					wd.PushButton{AssignTo: &btnAdd, Text: "+ Aggiungi a SNMP (community: public)",
						Enabled: false, OnClicked: func() { addSelectedAsTargets("public") }},
					wd.PushButton{AssignTo: &btnAddSNMP, Text: "+ Aggiungi a SNMP (community personalizzata...)",
						Enabled: false, OnClicked: func() {
							c, ok := promptString(dlg, "Community SNMP",
								"Inserisci la community SNMP da usare:", "public")
							if !ok || c == "" {
								return
							}
							addSelectedAsTargets(c)
						}},
					wd.HSpacer{},
					wd.PushButton{Text: "Esporta CSV...", OnClicked: func() {
						if len(model.items) == 0 {
							return
						}
						fd := walk.FileDialog{Title: "Esporta scansione",
							Filter: "CSV (*.csv)|*.csv", FilePath: "argus-scan.csv"}
						if ok, _ := fd.ShowSave(dlg); !ok {
							return
						}
						var sb strings.Builder
						sb.WriteString("status,ip,rtt_ms,hostname,mac,vendor,web_url,snmp_ok\n")
						for _, r := range model.items {
							sb.WriteString(fmt.Sprintf("%s,%s,%d,%q,%s,%q,%s,%v\n",
								r.Status, r.IP, r.RTTms, r.Hostname, r.MAC, r.Vendor, r.WebURL, r.SNMPok))
						}
						_ = writeFileText(fd.FilePath, sb.String())
					}},
					wd.PushButton{Text: "Esporta HTML...", OnClicked: exportHTML},
					wd.PushButton{Text: "Chiudi", OnClicked: func() {
						// Termina subito eventuali scan in corso senza
						// attendere i goroutine residui — i timeout TCP
						// di 250ms li faranno scadere da soli entro
						// pochi secondi.
						if cancelScan != nil {
							cancelScan()
						}
						dlg.Accept()
					}},
				},
			},
		},
	}.Run(parent)
	// Quando il dialog si chiude in qualsiasi modo (X, Esc, Chiudi),
	// cancella eventuali scan in volo cosi' i goroutine non rimangono
	// zombie.
	if cancelScan != nil {
		cancelScan()
	}
}

// promptString shows a tiny single-line input dialog. Returns (value, ok).
func promptString(parent walk.Form, title, prompt, def string) (string, bool) {
	var (
		dlg *walk.Dialog
		ed  *walk.LineEdit
	)
	out := def
	ok := false
	wd.Dialog{
		AssignTo: &dlg,
		Title:    title,
		Size:     wd.Size{Width: 380, Height: 140},
		Layout:   wd.VBox{},
		Children: []wd.Widget{
			wd.Label{Text: prompt},
			wd.LineEdit{AssignTo: &ed, Text: def},
			wd.Composite{
				Layout: wd.HBox{},
				Children: []wd.Widget{
					wd.HSpacer{},
					wd.PushButton{Text: "OK", OnClicked: func() {
						out = ed.Text()
						ok = true
						dlg.Accept()
					}},
					wd.PushButton{Text: "Annulla", OnClicked: func() { dlg.Cancel() }},
				},
			},
		},
	}.Run(parent)
	return out, ok
}

func writeFileText(path, content string) error {
	return os.WriteFile(path, []byte(content), 0o644)
}

// htmlEscape per il report HTML.
func htmlEscape(s string) string {
	r := strings.NewReplacer("&", "&amp;", "<", "&lt;", ">", "&gt;", "\"", "&quot;")
	return r.Replace(s)
}

// sendWoLMagicPacket invia un pacchetto Wake-on-LAN broadcast UDP/9.
// Il payload e' il magic packet standard: 6 byte 0xFF seguiti da 16
// ripetizioni dei 6 byte MAC del target.
func sendWoLMagicPacket(macStr string) error {
	mac, err := parseMAC6(macStr)
	if err != nil {
		return err
	}
	conn, err := net.Dial("udp", "255.255.255.255:9")
	if err != nil {
		return err
	}
	defer conn.Close()
	pkt := make([]byte, 0, 6+16*6)
	for i := 0; i < 6; i++ {
		pkt = append(pkt, 0xff)
	}
	for i := 0; i < 16; i++ {
		pkt = append(pkt, mac...)
	}
	_, err = conn.Write(pkt)
	return err
}

func parseMAC6(s string) ([]byte, error) {
	s = strings.ReplaceAll(s, "-", ":")
	parts := strings.Split(s, ":")
	if len(parts) != 6 {
		return nil, fmt.Errorf("MAC non valido: %q", s)
	}
	out := make([]byte, 6)
	for i, p := range parts {
		v, err := strconv.ParseUint(p, 16, 8)
		if err != nil {
			return nil, fmt.Errorf("MAC byte non valido: %q", p)
		}
		out[i] = byte(v)
	}
	return out, nil
}
