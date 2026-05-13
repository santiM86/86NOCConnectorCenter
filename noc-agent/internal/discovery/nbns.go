// nbns.go - NetBIOS Name Service enrichment per il manager discovery.
//
// Dopo che ARP / mDNS / scan locale hanno trovato un insieme di IP (DiscoveredEndpoint),
// questa funzione li interroga via UDP/137 NBSTAT in parallelo per arricchire
// l'hostname quando i source precedenti non hanno trovato nome o quando il
// nome ottenuto non e' significativo (es. PTR generico tipo
// "10-10-1-55.dyn.example.com" mentre NBNS dice "PC-MARCO").
//
// Caratteristiche:
//   - Concorrenza limitata (workers=64) per non saturare la rete LAN.
//   - Timeout per query 200ms (vedi nbns.DefaultTimeout): la latenza tipica
//     in LAN e' 5-50ms.
//   - Non sovrascrive Hostname gia' impostato a meno che il NetBIOS nome sia
//     piu' significativo (heuristica simple: nessun punto = NetBIOS hostname
//     "puro" come "PC-MARCO", da preferire al PTR FQDN dinamico).
package discovery

import (
	"context"
	"strings"
	"sync"

	"github.com/86bit/noc-agent/internal/nbns"
	"github.com/86bit/noc-agent/pkg/proto"
)

const nbnsWorkers = 64

func enrichNBNS(ctx context.Context, eps []proto.DiscoveredEndpoint) []proto.DiscoveredEndpoint {
	if len(eps) == 0 {
		return eps
	}
	sem := make(chan struct{}, nbnsWorkers)
	var wg sync.WaitGroup
	var mu sync.Mutex

	for i := range eps {
		ep := &eps[i]
		if ep.IP == "" {
			continue
		}
		wg.Add(1)
		sem <- struct{}{}
		go func(ep *proto.DiscoveredEndpoint) {
			defer wg.Done()
			defer func() { <-sem }()
			select {
			case <-ctx.Done():
				return
			default:
			}
			info, err := nbns.Query(ep.IP, nbns.DefaultTimeout)
			if err != nil || info == nil {
				return
			}
			mu.Lock()
			defer mu.Unlock()
			if info.ComputerName != "" {
				// Sostituisci hostname se attualmente vuoto OPPURE se il nome
				// corrente e' un FQDN "dinamico" tipo "10-10-1-55.example.com"
				// (cerco trattini nella prima label come euristica).
				existing := ep.Hostname
				if existing == "" || shouldReplaceWithNetbios(existing, info.ComputerName) {
					ep.Hostname = info.ComputerName
				}
			}
			// MAC fallback (solo se ARP/mDNS non l'hanno popolato).
			if ep.MAC == "" && info.MAC != "" {
				ep.MAC = info.MAC
			}
		}(ep)
	}
	wg.Wait()
	return eps
}

// shouldReplaceWithNetbios decide se sovrascrivere un hostname esistente col
// nome NetBIOS. Heuristica: se l'hostname corrente sembra un FQDN dinamico
// (prima label con piu' trattini "10-10-1-55"), preferiamo il NetBIOS.
func shouldReplaceWithNetbios(existing, netbios string) bool {
	first := existing
	if i := strings.Index(existing, "."); i > 0 {
		first = existing[:i]
	}
	// "10-10-1-55" → contiene trattini in posizioni numeriche
	if strings.Count(first, "-") >= 2 && hasOnlyDigitsAndDashes(first) {
		return true
	}
	// Se esistente e' tutto numerico (es. "1234"), prendi NetBIOS.
	if isAllDigits(first) {
		return true
	}
	_ = netbios
	return false
}

func hasOnlyDigitsAndDashes(s string) bool {
	for _, c := range s {
		if !((c >= '0' && c <= '9') || c == '-') {
			return false
		}
	}
	return true
}

func isAllDigits(s string) bool {
	if s == "" {
		return false
	}
	for _, c := range s {
		if c < '0' || c > '9' {
			return false
		}
	}
	return true
}
