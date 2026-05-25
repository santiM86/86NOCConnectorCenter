// TCP probe fallback per device che bloccano ICMP.
//
// Molti firewall enterprise (Zyxel, FortiGate, Cisco ASA) hanno ICMP
// disabilitato per default → il ping ICMP fallisce anche se il device e'
// perfettamente acceso e raggiungibile sulle porte applicative.
// Analogamente, gli host Windows con Windows Firewall in modo "Public"
// bloccano ICMP in entrata di default.
//
// Strategia (stesso pattern di Zabbix, Nagios, Datto RMM):
//
//	1. Tenta ICMP (IcmpSendEcho2 native su Windows, exec ping altrove).
//	2. Se ICMP fallisce, tenta TCP connect su un set di porte comuni.
//	3. Se almeno una porta risponde con un SYN-ACK entro timeout → device
//	   considerato "reachable" (Method: "tcp_probe").
//
// Porte testate in ordine di velocita' di risposta probabile:
//
//	443 (HTTPS / TLS-VPN / web mgmt firewall)
//	80  (HTTP web mgmt)
//	22  (SSH server / router / switch)
//	3389 (RDP server Windows)
//	445  (SMB - server Windows e NAS)
//	161  (SNMP agent — TCP rara ma a volte aperta)
//	23   (Telnet vecchio router)
//
// La prima porta che risponde fa terminare la probe (no overhead inutile).
//
// Timeout per porta: max(500ms, icmp_timeout/2). Cosi' 7 porte * 500ms = 3.5s
// worst-case, ma il 95% dei device risponde alla prima porta in <100ms.

package poller

import (
	"context"
	"net"
	"strconv"
	"time"
)

// tcpFallbackPorts ordinate per probabilita' decrescente di hit su un
// device enterprise tipico (firewall, switch, NAS, server Windows).
var tcpFallbackPorts = []int{443, 80, 22, 3389, 445, 161, 23}

// probeTCPFallback ritorna (reachable, latency_ms, portUsed).
// portUsed = 0 se nessuna porta risponde.
func probeTCPFallback(ctx context.Context, ip string, perPortTimeout time.Duration) (bool, int, int) {
	if perPortTimeout < 300*time.Millisecond {
		perPortTimeout = 300 * time.Millisecond
	}
	if perPortTimeout > 2*time.Second {
		perPortTimeout = 2 * time.Second
	}
	for _, port := range tcpFallbackPorts {
		select {
		case <-ctx.Done():
			return false, 0, 0
		default:
		}
		start := time.Now()
		dialCtx, cancel := context.WithTimeout(ctx, perPortTimeout)
		conn, err := (&net.Dialer{}).DialContext(dialCtx, "tcp",
			net.JoinHostPort(ip, strconv.Itoa(port)))
		cancel()
		elapsed := time.Since(start)
		if err == nil {
			_ = conn.Close()
			ms := int(elapsed / time.Millisecond)
			if ms < 1 {
				ms = 1
			}
			return true, ms, port
		}
		// Network errors that say "filtered/blocked" vs "no host" can be
		// distinguished, but we don't care here — just try the next port.
	}
	return false, 0, 0
}
