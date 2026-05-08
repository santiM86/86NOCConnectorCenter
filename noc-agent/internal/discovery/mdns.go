// mDNS / DNS-SD discovery. We browse a small but high-signal set of
// service types that cover ~95% of consumer/enterprise LAN devices:
//
//   _services._dns-sd._udp        — meta service (lists everything else)
//   _http._tcp                    — generic web UIs
//   _printer._tcp / _ipp._tcp     — printers
//   _workstation._tcp             — Linux/macOS hosts
//   _smb._tcp                     — Windows shares / NAS
//   _airplay._tcp / _raop._tcp    — Apple TV / AirPlay speakers
//   _hap._tcp                     — HomeKit
//   _googlecast._tcp              — Chromecast / Google Home
//
// We block per query for at most 3 seconds and merge by hostname.
package discovery

import (
	"context"
	"strings"
	"sync"
	"time"

	"github.com/hashicorp/mdns"

	"github.com/86bit/noc-agent/pkg/proto"
)

// MDNS is a Source backed by multicast DNS / DNS-SD.
type MDNS struct{}

func NewMDNS() *MDNS { return &MDNS{} }

func (m *MDNS) Name() string { return "mdns" }

var mdnsServices = []string{
	"_services._dns-sd._udp",
	"_http._tcp",
	"_printer._tcp",
	"_ipp._tcp",
	"_workstation._tcp",
	"_smb._tcp",
	"_airplay._tcp",
	"_raop._tcp",
	"_hap._tcp",
	"_googlecast._tcp",
}

func (m *MDNS) Scan(ctx context.Context) ([]proto.DiscoveredEndpoint, error) {
	deadline := 3 * time.Second
	if dl, ok := ctx.Deadline(); ok {
		if d := time.Until(dl); d < deadline && d > 0 {
			deadline = d
		}
	}

	var (
		mu  sync.Mutex
		out = map[string]proto.DiscoveredEndpoint{}
		wg  sync.WaitGroup
	)

	for _, svc := range mdnsServices {
		svc := svc
		wg.Add(1)
		go func() {
			defer wg.Done()
			ch := make(chan *mdns.ServiceEntry, 64)
			done := make(chan struct{})
			go func() {
				for e := range ch {
					if e == nil || e.AddrV4 == nil {
						continue
					}
					ip := e.AddrV4.String()
					host := strings.TrimSuffix(e.Host, ".")
					attrs := map[string]string{"service": svc}
					if e.Info != "" {
						attrs["info"] = e.Info
					}
					mu.Lock()
					ep := out[ip]
					ep.IP = ip
					ep.Hostname = host
					ep.Source = "mdns"
					if ep.Attributes == nil {
						ep.Attributes = attrs
					} else {
						for k, v := range attrs {
							ep.Attributes[k] = v
						}
					}
					out[ip] = ep
					mu.Unlock()
				}
				close(done)
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

	res := make([]proto.DiscoveredEndpoint, 0, len(out))
	for _, ep := range out {
		res = append(res, ep)
	}
	return res, nil
}
