// ICMP echo nativo via Win32 IcmpSendEcho2 — sostituisce il fork di
// `ping.exe` che su Windows con ASR (Attack Surface Reduction)
// attivo viene bloccato/ritardato dal sistema operativo causando
// timeout costanti e device che vanno tutti OFFLINE.
//
// Stessa implementazione di internal/lanscan/icmp_windows.go, ma
// duplicata qui per non creare dipendenze cross-package (poller e
// lanscan sono moduli indipendenti).
//
//go:build windows

package poller

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
	iphlpapi            = syscall.NewLazyDLL("iphlpapi.dll")
	procIcmpCreateFile  = iphlpapi.NewProc("IcmpCreateFile")
	procIcmpCloseHandle = iphlpapi.NewProc("IcmpCloseHandle")
	procIcmpSendEcho2   = iphlpapi.NewProc("IcmpSendEcho2")
	icmpHandleSingleton syscall.Handle
	icmpHandleOnce      sync.Once
	icmpHandleAvailable bool
)

const nativeICMPSupported = true

func initIcmpHandle() {
	icmpHandleOnce.Do(func() {
		h, _, _ := procIcmpCreateFile.Call()
		if h == 0 || h == ^uintptr(0) {
			icmpHandleAvailable = false
			return
		}
		icmpHandleSingleton = syscall.Handle(h)
		icmpHandleAvailable = true
	})
}

const (
	icmpStatusSuccess     uint32 = 0
	icmpReplyBufferSize          = 96
	icmpRequestPayloadLen        = 32
)

// nativeProbeICMP invia un echo ICMP via IcmpSendEcho2 (no fork di ping.exe).
// Ritorna (reachable, rttMs, errorMessage).
//
//	reachable: true se il device ha risposto entro timeoutMs.
//	rttMs:     RTT in millisecondi (>=1 se reachable, 0 se non).
//	err:       stringa di errore breve per UI ("timeout", "no route", ecc.).
func nativeProbeICMP(ctx context.Context, ip string, timeoutMs int) (bool, int, string) {
	initIcmpHandle()
	if !icmpHandleAvailable {
		return false, 0, "icmp handle unavailable"
	}
	parsed := net.ParseIP(ip).To4()
	if parsed == nil {
		return false, 0, "ipv4 only"
	}
	addr := uint32(parsed[0]) | uint32(parsed[1])<<8 | uint32(parsed[2])<<16 | uint32(parsed[3])<<24

	payload := [icmpRequestPayloadLen]byte{
		'A', 'R', 'G', 'U', 'S', '-', 'P', 'O', 'L', 'L',
	}
	reply := make([]byte, icmpReplyBufferSize)

	select {
	case <-ctx.Done():
		return false, 0, "ctx cancelled"
	default:
	}

	type icmpResult struct {
		ok  bool
		rtt int
		err string
	}
	resCh := make(chan icmpResult, 1)

	go func() {
		defer func() { _ = recover() }()
		n, _, _ := procIcmpSendEcho2.Call(
			uintptr(icmpHandleSingleton),
			0, // event
			0, // apc routine
			0, // apc context
			uintptr(addr),
			uintptr(unsafe.Pointer(&payload[0])),
			uintptr(icmpRequestPayloadLen),
			0, // request options
			uintptr(unsafe.Pointer(&reply[0])),
			uintptr(icmpReplyBufferSize),
			uintptr(timeoutMs),
		)
		out := icmpResult{}
		if n > 0 {
			status := binary.LittleEndian.Uint32(reply[4:8])
			roundTrip := binary.LittleEndian.Uint32(reply[8:12])
			if status == icmpStatusSuccess {
				out.ok = true
				out.rtt = int(roundTrip)
				if out.rtt == 0 {
					out.rtt = 1
				}
			} else {
				out.err = "icmp status " + itoa(int(status))
			}
		} else {
			out.err = "icmp send failed"
		}
		select {
		case resCh <- out:
		default:
		}
	}()

	wait := time.Duration(timeoutMs+200) * time.Millisecond
	select {
	case r := <-resCh:
		return r.ok, r.rtt, r.err
	case <-ctx.Done():
		return false, 0, "ctx cancelled"
	case <-time.After(wait):
		return false, 0, "timeout"
	}
}

// piccolo helper itoa per evitare import "strconv" (gia' usato in icmp.go ma
// vogliamo questo file totalmente self-contained).
func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	neg := false
	if n < 0 {
		neg = true
		n = -n
	}
	var buf [20]byte
	i := len(buf)
	for n > 0 {
		i--
		buf[i] = byte('0' + n%10)
		n /= 10
	}
	if neg {
		i--
		buf[i] = '-'
	}
	return string(buf[i:])
}
