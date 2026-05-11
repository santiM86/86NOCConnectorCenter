// PTR enrichment for discovered endpoints.
//
// After the regular scan sources (ARP, mDNS) have produced a merged batch,
// this helper performs a reverse-DNS PTR lookup for every endpoint that
// still lacks a Hostname.  Lookups are bounded in time and concurrency so
// the enrichment cannot block the scan or exhaust DNS resolvers on busy
// LANs.
//
// Design notes:
//   - mDNS-provided hostnames (e.g. "IFIXITGESTDS.local") are preserved:
//     this enrichment only fills the gap, never overwrites.
//   - Only fully-qualified non-`.in-addr.arpa` answers are accepted; we
//     strip the trailing dot for storage consistency.
//   - All lookups share a single short timeout per IP (default 1 s) and
//     a global concurrency cap (default 16 workers) so resolving a /24
//     completes in <3 seconds even with several timeouts.
package discovery

import (
	"context"
	"net"
	"strings"
	"sync"
	"time"

	"github.com/86bit/noc-agent/pkg/proto"
)

const (
	ptrLookupTimeout = 1 * time.Second
	ptrWorkers       = 16
)

// enrichPTR fills Hostname for endpoints that don't already have one,
// using reverse DNS. Mutates a copy of the slice and returns it.
func enrichPTR(ctx context.Context, eps []proto.DiscoveredEndpoint) []proto.DiscoveredEndpoint {
	if len(eps) == 0 {
		return eps
	}
	// Collect indices that need a PTR lookup.
	pending := make([]int, 0, len(eps))
	for i, ep := range eps {
		if ep.Hostname == "" && ep.IP != "" {
			pending = append(pending, i)
		}
	}
	if len(pending) == 0 {
		return eps
	}

	jobs := make(chan int, len(pending))
	var wg sync.WaitGroup
	var mu sync.Mutex
	workers := ptrWorkers
	if workers > len(pending) {
		workers = len(pending)
	}

	for w := 0; w < workers; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			resolver := &net.Resolver{}
			for idx := range jobs {
				lookupCtx, cancel := context.WithTimeout(ctx, ptrLookupTimeout)
				names, err := resolver.LookupAddr(lookupCtx, eps[idx].IP)
				cancel()
				if err != nil || len(names) == 0 {
					continue
				}
				host := sanitizePTR(names[0])
				if host == "" {
					continue
				}
				mu.Lock()
				eps[idx].Hostname = host
				mu.Unlock()
			}
		}()
	}
	for _, idx := range pending {
		jobs <- idx
	}
	close(jobs)
	wg.Wait()
	return eps
}

// sanitizePTR strips a trailing dot and rejects clearly synthetic answers
// such as "*.in-addr.arpa" which the resolver may return on miss.
func sanitizePTR(name string) string {
	n := strings.TrimSuffix(strings.TrimSpace(name), ".")
	if n == "" {
		return ""
	}
	lower := strings.ToLower(n)
	if strings.HasSuffix(lower, ".in-addr.arpa") || strings.HasSuffix(lower, ".ip6.arpa") {
		return ""
	}
	return n
}
