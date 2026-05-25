// stub non-windows — fallback per build cross-platform. Su Linux/macOS
// il fork di `ping` non e' bloccato da Defender ASR, quindi continuiamo
// a usare il path classico in icmp.go.
//
//go:build !windows

package poller

import "context"

// nativeProbeICMP non disponibile fuori da Windows. probe() rilevera'
// nativeICMPSupported=false e fallback al path `os/exec ping`.
func nativeProbeICMP(_ context.Context, _ string, _ int) (bool, int, string) {
	return false, 0, "native not available"
}

const nativeICMPSupported = false
