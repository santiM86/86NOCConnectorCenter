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
	"context"
	"fmt"
	"net"
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
	Status   string // "alive" | "arp-only"
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
		return r.Status
	case 1:
		return r.IP
	case 2:
		return r.Hostname
	case 3:
		return r.MAC
	case 4:
		return r.Vendor
	}
	return ""
}
func (m *scanResultsModel) PublishRowsReset() { m.PublishRowsChanged(0, len(m.items)) }

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

// probeAlive returns true if any of the well-known TCP ports answers
// within timeout. It does not need elevated privileges.
func probeAlive(ip string, timeout time.Duration) bool {
	ports := []int{135, 445, 139, 80, 22, 443, 8080, 23, 3389, 161, 515, 9100, 631}
	for _, p := range ports {
		conn, err := net.DialTimeout("tcp", net.JoinHostPort(ip, strconv.Itoa(p)), timeout)
		if err == nil {
			_ = conn.Close()
			return true
		}
	}
	return false
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
// onProgress is called from the worker goroutine — callers must marshal
// to the UI thread via MainWindow.Synchronize.
func runScan(ctx context.Context, cidr string, timeout time.Duration,
	onProgress func(done, total int)) ([]*ScanResult, error) {

	ips, err := expandCIDR(cidr)
	if err != nil {
		return nil, err
	}
	total := len(ips)
	var done int32

	// Phase 1: TCP probe in parallel.
	alive := struct {
		mu sync.Mutex
		m  map[string]bool
	}{m: map[string]bool{}}
	sem := make(chan struct{}, 64)
	var wg sync.WaitGroup
	for _, ip := range ips {
		ip := ip
		select {
		case <-ctx.Done():
			break
		default:
		}
		wg.Add(1)
		sem <- struct{}{}
		go func() {
			defer wg.Done()
			defer func() { <-sem }()
			if probeAlive(ip, timeout) {
				alive.mu.Lock()
				alive.m[ip] = true
				alive.mu.Unlock()
			}
			n := atomic.AddInt32(&done, 1)
			if onProgress != nil && (n%4 == 0 || int(n) == total) {
				onProgress(int(n), total)
			}
		}()
	}
	wg.Wait()

	// Phase 2: ARP cache (catches devices that block TCP but answered to
	// our probe attempts so the kernel populated the neighbour cache).
	arp := readARPTable(ctx)

	// Merge: union of alive set + ARP table.
	merged := map[string]string{} // ip -> mac
	for ip := range alive.m {
		merged[ip] = arp[ip]
	}
	for ip, mac := range arp {
		if _, ok := merged[ip]; !ok {
			merged[ip] = mac
		}
	}

	// Phase 3: PTR lookups (parallel, short timeout).
	type out struct {
		ip   string
		host string
	}
	hosts := map[string]string{}
	hostsMu := sync.Mutex{}
	wg = sync.WaitGroup{}
	hostSem := make(chan struct{}, 32)
	for ip := range merged {
		ip := ip
		wg.Add(1)
		hostSem <- struct{}{}
		go func() {
			defer wg.Done()
			defer func() { <-hostSem }()
			h := reverseDNS(ctx, ip)
			if h != "" {
				hostsMu.Lock()
				hosts[ip] = h
				hostsMu.Unlock()
			}
		}()
	}
	wg.Wait()

	results := make([]*ScanResult, 0, len(merged))
	for ip, mac := range merged {
		status := "arp-only"
		if alive.m[ip] {
			status = "alive"
		}
		results = append(results, &ScanResult{
			IP:       ip,
			MAC:      mac,
			Hostname: hosts[ip],
			Vendor:   ouiVendor(mac),
			Status:   status,
		})
	}
	sort.Slice(results, func(i, j int) bool { return ipNumeric(results[i].IP) < ipNumeric(results[j].IP) })
	return results, nil
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
			res, err := runScan(ctxScan, cidr, 250*time.Millisecond, func(done, total int) {
				dlg.Synchronize(func() {
					if total > 0 {
						progressBar.SetValue(int(float64(done) / float64(total) * 100))
					}
					statusLb.SetText(fmt.Sprintf("Probe %d/%d ...", done, total))
				})
			})
			dlg.Synchronize(func() {
				btnScan.SetText("Scansiona Rete")
				if err != nil {
					statusLb.SetText("Errore: " + err.Error())
					return
				}
				model.items = res
				model.PublishRowsReset()
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
			statusLb.SetText("Scansione annullata.")
			return
		}
		startScan()
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
		Size:     wd.Size{Width: 920, Height: 620},
		MinSize:  wd.Size{Width: 800, Height: 500},
		Layout:   wd.VBox{},
		Children: []wd.Widget{
			wd.Label{Text: "Scansione rete locale (TCP probe + ARP cache + DNS reverse)",
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
					{Title: "Hostname", Width: 220},
					{Title: "MAC", Width: 150},
					{Title: "Vendor", Width: 140},
				},
				Model: model,
			},
			wd.Composite{
				Layout: wd.HBox{},
				Children: []wd.Widget{
					wd.PushButton{AssignTo: &btnAdd, Text: "+ Aggiungi (community: public)",
						Enabled: false, OnClicked: func() { addSelectedAsTargets("public") }},
					wd.PushButton{AssignTo: &btnAddSNMP, Text: "+ Aggiungi (community personalizzata...)",
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
						sb.WriteString("status,ip,hostname,mac,vendor\n")
						for _, r := range model.items {
							sb.WriteString(fmt.Sprintf("%s,%s,%q,%s,%q\n",
								r.Status, r.IP, r.Hostname, r.MAC, r.Vendor))
						}
						_ = writeFileText(fd.FilePath, sb.String())
					}},
					wd.PushButton{Text: "Chiudi", OnClicked: func() { dlg.Accept() }},
				},
			},
		},
	}.Run(parent)
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
