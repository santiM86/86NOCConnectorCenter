// ICMP echo nativo via Win32 IcmpSendEcho2 — copia leggera del wrapper
// usato in cmd/nocui per condividerlo con la UI v5 (Wails).
//
//go:build windows

package lanscan

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

// CloseIcmpHandle libera l'handle ICMP a fine programma (best-effort).
func CloseIcmpHandle() {
	if icmpHandleAvailable {
		_, _, _ = procIcmpCloseHandle.Call(uintptr(icmpHandleSingleton))
		icmpHandleAvailable = false
	}
}

const (
	icmpStatusSuccess     uint32 = 0
	icmpReplyBufferSize          = 96
	icmpRequestPayloadLen        = 32
)

// probeICMPNative invia un echo ICMP via IcmpSendEcho2 e ritorna l'RTT
// in millisecondi (>=0) o -1 se l'host non risponde entro timeoutMs.
// Safe per chiamate concorrenti grazie all'handle singleton.
func probeICMPNative(ctx context.Context, ip string, timeoutMs int) int {
	initIcmpHandle()
	if !icmpHandleAvailable {
		return -1
	}
	parsed := net.ParseIP(ip).To4()
	if parsed == nil {
		return -1
	}
	addr := uint32(parsed[0]) | uint32(parsed[1])<<8 | uint32(parsed[2])<<16 | uint32(parsed[3])<<24

	payload := [icmpRequestPayloadLen]byte{
		'A', 'R', 'G', 'U', 'S', '-', 'S', 'C', 'A', 'N',
		0, 0, 0, 0, 0, 0,
		0, 0, 0, 0, 0, 0, 0, 0,
		0, 0, 0, 0, 0, 0, 0, 0,
	}
	reply := make([]byte, icmpReplyBufferSize)

	select {
	case <-ctx.Done():
		return -1
	default:
	}

	type icmpResult struct {
		n   uintptr
		rtt int
	}
	resCh := make(chan icmpResult, 1)

	go func() {
		defer func() { _ = recover() }()
		n, _, _ := procIcmpSendEcho2.Call(
			uintptr(icmpHandleSingleton),
			0,
			0,
			0,
			uintptr(addr),
			uintptr(unsafe.Pointer(&payload[0])),
			uintptr(icmpRequestPayloadLen),
			0,
			uintptr(unsafe.Pointer(&reply[0])),
			uintptr(icmpReplyBufferSize),
			uintptr(timeoutMs),
		)
		rtt := -1
		if n > 0 {
			status := binary.LittleEndian.Uint32(reply[4:8])
			roundTrip := binary.LittleEndian.Uint32(reply[8:12])
			if status == icmpStatusSuccess {
				rtt = int(roundTrip)
				if rtt == 0 {
					rtt = 1
				}
			}
		}
		select {
		case resCh <- icmpResult{n: n, rtt: rtt}:
		default:
		}
	}()

	wait := time.Duration(timeoutMs+100) * time.Millisecond
	select {
	case r := <-resCh:
		return r.rtt
	case <-ctx.Done():
		return -1
	case <-time.After(wait):
		return -1
	}
}
