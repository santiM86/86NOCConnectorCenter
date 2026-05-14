// HTTP banner grabbing minimale. Tenta una connect TCP veloce sulle
// porte HTTP comuni (80, 8080, 443) e legge solo l'header `Server:`.
// Identifica device che espongono pannelli web di management:
// stampanti, NAS, switch managed, IP camera, ILO/iDRAC, router, ecc.
//
// Tempi target: <500ms total per IP, fail-fast su porte chiuse.
//
//go:build windows

package lanscan

import (
	"bufio"
	"context"
	"crypto/tls"
	"fmt"
	"net"
	"strings"
	"time"
)

var httpProbePorts = []int{80, 8080, 443}

// httpBanner tenta di catturare l'header `Server:` (o `WWW-Authenticate`
// realm come fallback) da un device esponente HTTP/S. Ritorna stringa
// vuota se nessuna porta risponde entro `timeout` totale.
func httpBanner(ctx context.Context, ip string, timeout time.Duration) string {
	deadline, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	for _, port := range httpProbePorts {
		select {
		case <-deadline.Done():
			return ""
		default:
		}
		b := probeOne(deadline, ip, port)
		if b != "" {
			return b
		}
	}
	return ""
}

func probeOne(ctx context.Context, ip string, port int) string {
	addr := fmt.Sprintf("%s:%d", ip, port)
	d := net.Dialer{Timeout: 200 * time.Millisecond}
	var conn net.Conn
	var err error
	if port == 443 {
		dl, ok := ctx.Deadline()
		td := 250 * time.Millisecond
		if ok {
			td = time.Until(dl)
		}
		conn, err = tls.DialWithDialer(
			&net.Dialer{Timeout: td},
			"tcp", addr,
			&tls.Config{InsecureSkipVerify: true, ServerName: ip},
		)
	} else {
		conn, err = d.DialContext(ctx, "tcp", addr)
	}
	if err != nil {
		return ""
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(300 * time.Millisecond))
	if _, err := fmt.Fprintf(conn, "HEAD / HTTP/1.0\r\nUser-Agent: ARGUS-Scan/1.0\r\nConnection: close\r\n\r\n"); err != nil {
		return ""
	}
	br := bufio.NewReader(conn)
	server := ""
	wwwAuth := ""
	for i := 0; i < 32; i++ { // read at most 32 header lines
		line, err := br.ReadString('\n')
		if err != nil {
			break
		}
		line = strings.TrimRight(line, "\r\n")
		if line == "" {
			break
		}
		l := strings.ToLower(line)
		if strings.HasPrefix(l, "server:") {
			server = strings.TrimSpace(line[7:])
		} else if strings.HasPrefix(l, "www-authenticate:") && wwwAuth == "" {
			wwwAuth = strings.TrimSpace(line[17:])
		}
	}
	if server != "" {
		return truncate(server, 96)
	}
	if wwwAuth != "" {
		// realm="HP Color LaserJet" -> spesso meglio del Server vuoto
		if idx := strings.Index(strings.ToLower(wwwAuth), "realm="); idx >= 0 {
			realm := strings.Trim(wwwAuth[idx+6:], `" `)
			if realm != "" {
				return truncate("realm: "+realm, 96)
			}
		}
	}
	return ""
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "…"
}
