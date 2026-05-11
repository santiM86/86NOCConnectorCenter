// ARP-table discovery. We read the host's neighbour cache cross-platform
// without spawning external processes:
//
//   - Linux: /proc/net/arp
//   - Windows: GetIpNetTable via syscall (kept simple here: parse `arp -a`
//     output as a fallback; real builds will swap to iphlpapi)
//   - macOS/BSD: parse `arp -an`
//
// To keep this MVP focused, we use the /proc reader on Linux and a portable
// `arp -a` reader elsewhere. The result is canonicalised to DiscoveredEndpoint.
package discovery

import (
	"bufio"
	"context"
	"errors"
	"net"
	"os"
	"os/exec"
	"runtime"
	"strings"

	"github.com/86bit/noc-agent/pkg/proto"
)

// ARP is a Source backed by the OS ARP/neighbour cache.
type ARP struct{}

func NewARP() *ARP { return &ARP{} }

func (a *ARP) Name() string { return "arp" }

func (a *ARP) Scan(ctx context.Context) ([]proto.DiscoveredEndpoint, error) {
	if runtime.GOOS == "linux" {
		return a.scanProc()
	}
	return a.scanCmd(ctx)
}

func (a *ARP) scanProc() ([]proto.DiscoveredEndpoint, error) {
	f, err := os.Open("/proc/net/arp")
	if err != nil {
		return nil, err
	}
	defer f.Close()
	out := []proto.DiscoveredEndpoint{}
	sc := bufio.NewScanner(f)
	first := true
	for sc.Scan() {
		if first { // header
			first = false
			continue
		}
		fields := strings.Fields(sc.Text())
		if len(fields) < 6 {
			continue
		}
		ip, mac := fields[0], strings.ToLower(fields[3])
		if mac == "00:00:00:00:00:00" || net.ParseIP(ip) == nil {
			continue
		}
		out = append(out, proto.DiscoveredEndpoint{
			IP: ip, MAC: mac, Source: "arp",
		})
	}
	return out, sc.Err()
}

func (a *ARP) scanCmd(ctx context.Context) ([]proto.DiscoveredEndpoint, error) {
	bin, err := exec.LookPath("arp")
	if err != nil {
		return nil, errors.New("arp binary not found in PATH")
	}
	// Windows uses `arp -a`; BSD/macOS use `arp -an` (numeric, no DNS).
	flag := "-an"
	if runtime.GOOS == "windows" {
		flag = "-a"
	}
	cmd := exec.CommandContext(ctx, bin, flag)
	out, err := cmd.Output()
	if err != nil {
		return nil, err
	}
	res := []proto.DiscoveredEndpoint{}
	for _, line := range strings.Split(string(out), "\n") {
		ip, mac := parseARPLine(line)
		if ip == "" || mac == "" {
			continue
		}
		// Skip multicast (01:00:5e:..) and broadcast (ff:ff:..) entries.
		if strings.HasPrefix(mac, "01:00:5e") || mac == "ff:ff:ff:ff:ff:ff" {
			continue
		}
		// Skip multicast IPv4 ranges (224.0.0.0/4) and broadcast.
		if pip := net.ParseIP(ip); pip == nil || pip.IsMulticast() || pip.Equal(net.IPv4bcast) {
			continue
		}
		res = append(res, proto.DiscoveredEndpoint{IP: ip, MAC: mac, Source: "arp"})
	}
	return res, nil
}

// parseARPLine handles BSD/Windows formats:
//
//	? (192.168.1.1) at aa:bb:cc:dd:ee:ff on en0 ifscope [ethernet]
//	  192.168.1.1           aa-bb-cc-dd-ee-ff     dynamic
func parseARPLine(line string) (ip, mac string) {
	if i := strings.Index(line, "("); i >= 0 {
		if j := strings.Index(line[i:], ")"); j > 0 {
			ip = line[i+1 : i+j]
		}
	}
	for _, tok := range strings.Fields(line) {
		if isMACLike(tok) {
			mac = strings.ToLower(strings.ReplaceAll(tok, "-", ":"))
			break
		}
	}
	if ip == "" {
		// Windows-style: first column is IP
		parts := strings.Fields(line)
		if len(parts) > 0 && net.ParseIP(parts[0]) != nil {
			ip = parts[0]
		}
	}
	return
}

func isMACLike(s string) bool {
	if len(s) != 17 {
		return false
	}
	for i := 0; i < 17; i++ {
		c := s[i]
		switch {
		case (i+1)%3 == 0:
			if c != ':' && c != '-' {
				return false
			}
		default:
			if !((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F')) {
				return false
			}
		}
	}
	return true
}
