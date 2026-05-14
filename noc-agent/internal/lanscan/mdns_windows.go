// mDNS / DNS-SD discovery per LAN scan. Identifica device che
// annunciano servizi Bonjour (Apple, Google Cast, stampanti AirPrint,
// Sonos, NAS Synology/QNAP, ecc.) ben oltre quello che vedono ARP +
// NBNS + reverse DNS.
//
// Riusa `github.com/hashicorp/mdns` (gia' dependency del progetto via
// `internal/discovery/mdns.go`). Lo stile e' deliberatamente identico
// per riusabilita' della pipeline.
//
//go:build windows

package lanscan

import (
	"context"
	"strings"
	"sync"
	"time"

	"github.com/hashicorp/mdns"
)

// mdnsInfo rappresenta un device scoperto via mDNS.
type mdnsInfo struct {
	Hostname string
	Services []string
}

var mdnsServiceTypes = []string{
	"_http._tcp",
	"_printer._tcp",
	"_ipp._tcp",
	"_workstation._tcp",
	"_smb._tcp",
	"_airplay._tcp",
	"_raop._tcp",
	"_googlecast._tcp",
	"_companion-link._tcp",
}

// discoverMDNS effettua una query multicast su tutti i service types
// rilevanti e ritorna mappa IP -> info. Timeout breve (3s default)
// perche' gira in parallelo al sweep ICMP.
func discoverMDNS(ctx context.Context) map[string]mdnsInfo {
	deadline := 3 * time.Second
	if dl, ok := ctx.Deadline(); ok {
		if d := time.Until(dl); d < deadline && d > 0 {
			deadline = d
		}
	}

	out := map[string]mdnsInfo{}
	var mu sync.Mutex
	var wg sync.WaitGroup

	for _, svc := range mdnsServiceTypes {
		svc := svc
		wg.Add(1)
		go func() {
			defer wg.Done()
			defer func() { _ = recover() }() // safety
			ch := make(chan *mdns.ServiceEntry, 64)
			done := make(chan struct{})
			go func() {
				defer close(done)
				for e := range ch {
					if e == nil || e.AddrV4 == nil {
						continue
					}
					ip := e.AddrV4.String()
					host := strings.TrimSuffix(e.Host, ".")
					host = strings.TrimSuffix(host, ".local")
					mu.Lock()
					info := out[ip]
					if info.Hostname == "" && host != "" {
						info.Hostname = host
					}
					info.Services = append(info.Services, svc)
					out[ip] = info
					mu.Unlock()
				}
			}()
			params := mdns.DefaultParams(svc)
			params.Entries = ch
			params.Timeout = deadline
			params.DisableIPv6 = true
			_ = mdns.Query(params)
			close(ch)
			<-done
		}()
	}
	wg.Wait()
	return out
}
