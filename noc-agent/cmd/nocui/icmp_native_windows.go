// ICMP echo nativo via Win32 IP Helper API.
//
// MOTIVAZIONE: `exec.Command("ping.exe", ...)` ha ~50-150ms di overhead
// per CreateProcess su Windows (worsened by Defender ASR che ispeziona
// ogni nuovo processo figlio prima di lasciarlo eseguire). Su un /24
// con 254 IP questo trasforma una scansione che dovrebbe durare ~500ms
// in 5-10 secondi.
//
// IcmpSendEcho2 da iphlpapi.dll permette di inviare echo request ICMP
// SENZA spawn di processi figli e SENZA privilegi admin (la chiamata
// e' wrapped dal driver tcpip.sys che gestisce il raw socket per noi).
//
// Questa e' la stessa API usata da Advanced IP Scanner, SoftPerfect
// Network Scanner e nmap su Windows -- e' la via canonica enterprise.
//
//go:build windows

package main

import (
	"context"
	"encoding/binary"
	"net"
	"sync"
	"syscall"
	"time"
	"unsafe"
)

var (
	iphlpapi             = syscall.NewLazyDLL("iphlpapi.dll")
	procIcmpCreateFile   = iphlpapi.NewProc("IcmpCreateFile")
	procIcmpCloseHandle  = iphlpapi.NewProc("IcmpCloseHandle")
	procIcmpSendEcho2    = iphlpapi.NewProc("IcmpSendEcho2")
	icmpHandleSingleton  syscall.Handle
	icmpHandleOnce       sync.Once
	icmpHandleAvailable  bool
)

// initIcmpHandle apre un handle ICMP riusabile per tutto il processo.
// Il driver Windows gestisce internamente il fan-out concorrente,
// quindi un solo handle e' sufficiente per N goroutine in parallelo.
func initIcmpHandle() {
	icmpHandleOnce.Do(func() {
		h, _, _ := procIcmpCreateFile.Call()
		// IcmpCreateFile ritorna INVALID_HANDLE_VALUE (-1 / 0xFFFFFFFF...)
		// in caso di errore. Su system con tcpip.sys regolarmente
		// caricato non dovrebbe MAI fallire.
		if h == 0 || h == ^uintptr(0) {
			icmpHandleAvailable = false
			return
		}
		icmpHandleSingleton = syscall.Handle(h)
		icmpHandleAvailable = true
	})
}

// CloseIcmpHandle e' chiamabile a fine programma (best-effort).
// In pratica il SO ripulisce comunque alla terminazione del processo.
func CloseIcmpHandle() {
	if icmpHandleAvailable {
		_, _, _ = procIcmpCloseHandle.Call(uintptr(icmpHandleSingleton))
		icmpHandleAvailable = false
	}
}

// ICMP_ECHO_REPLY layout su Windows x64 (sizeof ~28 bytes + Options).
// Allocheremo 96 bytes per safety (request 32 bytes + reply struct +
// padding + IP_OPTION_INFORMATION).
//
// Field offsets (x86 / x64 entrambi packed):
//   0  IPAddr  Address           (4)
//   4  ULONG   Status            (4)
//   8  ULONG   RoundTripTime     (4)
//  12  USHORT  DataSize          (2)
//  14  USHORT  Reserved          (2)
//  16  PVOID   Data              (4/8)  ← dipende dall'arch
//  24  IP_OPTION_INFORMATION     (8 su x64)
//
// Per estrarre RoundTripTime ci basta leggere offset 8-12.

const (
	icmpStatusSuccess     uint32 = 0
	icmpReplyBufferSize          = 96
	icmpRequestPayloadLen        = 32 // payload "ARGUS\0\0..." 32 bytes
)

// probeICMPNative esegue un echo ICMP via Win32 IcmpSendEcho2 e ritorna
// il RTT in millisecondi (>=0) oppure -1 se l'host non risponde entro
// timeoutMs millisecondi.
//
// Sicuro per chiamate concorrenti grazie all'handle singleton + driver
// kernel-side multiplexing.
func probeICMPNative(ctx context.Context, ip string, timeoutMs int) int {
	initIcmpHandle()
	if !icmpHandleAvailable {
		// Fallback al ping.exe legacy se IcmpCreateFile e' fallito
		// (caso patologico: iphlpapi.dll non caricabile).
		return probeICMPPing(ctx, ip, timeoutMs)
	}
	parsed := net.ParseIP(ip).To4()
	if parsed == nil {
		return -1
	}
	// IPAddr e' un DWORD little-endian con i 4 byte dell'IP.
	// IcmpSendEcho2 si aspetta network-byte-order MA su Windows la
	// API espone l'IPAddr in host-byte-order: a.b.c.d -> d<<24|c<<16|b<<8|a.
	addr := uint32(parsed[0]) | uint32(parsed[1])<<8 | uint32(parsed[2])<<16 | uint32(parsed[3])<<24

	// Payload deterministico per evitare data race con altre goroutine.
	// Buffer locale alla chiamata, non condiviso.
	payload := [icmpRequestPayloadLen]byte{
		'A', 'R', 'G', 'U', 'S', '-', 'S', 'C', 'A', 'N',
		0, 0, 0, 0, 0, 0,
		0, 0, 0, 0, 0, 0, 0, 0,
		0, 0, 0, 0, 0, 0, 0, 0,
	}
	reply := make([]byte, icmpReplyBufferSize)

	// Honor del ctx cancel: se il contesto e' gia' scaduto, exit immediato.
	select {
	case <-ctx.Done():
		return -1
	default:
	}

	// IcmpSendEcho2 e' bloccante fino a Reply o Timeout (ms). Per
	// rispettare context cancel asincrono, lanciamo la syscall in
	// goroutine e race contro il context.Done().
	type icmpResult struct {
		n   uintptr
		rtt int
	}
	resCh := make(chan icmpResult, 1)

	go func() {
		defer func() { _ = recover() }()
		n, _, _ := procIcmpSendEcho2.Call(
			uintptr(icmpHandleSingleton),
			0, // Event (NULL = synchronous)
			0, // ApcRoutine (NULL)
			0, // ApcContext (NULL)
			uintptr(addr),
			uintptr(unsafe.Pointer(&payload[0])),
			uintptr(icmpRequestPayloadLen),
			0, // RequestOptions (NULL = defaults)
			uintptr(unsafe.Pointer(&reply[0])),
			uintptr(icmpReplyBufferSize),
			uintptr(timeoutMs),
		)
		rtt := -1
		if n > 0 {
			// Parse ICMP_ECHO_REPLY.
			status := binary.LittleEndian.Uint32(reply[4:8])
			roundTrip := binary.LittleEndian.Uint32(reply[8:12])
			if status == icmpStatusSuccess {
				rtt = int(roundTrip)
				if rtt == 0 {
					rtt = 1 // LAN locale: <1ms diventa 1ms per leggibilita'
				}
			}
		}
		select {
		case resCh <- icmpResult{n: n, rtt: rtt}:
		default:
		}
	}()

	// Wait max timeoutMs + 100ms (slack) o ctx cancel.
	wait := time.Duration(timeoutMs+100) * time.Millisecond
	select {
	case r := <-resCh:
		return r.rtt
	case <-ctx.Done():
		return -1
	case <-time.After(wait):
		// Timeout safety net: non dovrebbe MAI scattare perche'
		// IcmpSendEcho2 rispetta gia' il timeout interno.
		return -1
	}
}
