package poller

import (
	"testing"
	"time"

	"github.com/86bit/noc-agent/pkg/proto"
)

func TestApplyParsedLinuxSuccess(t *testing.T) {
	out := `PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.
64 bytes from 8.8.8.8: icmp_seq=1 ttl=117 time=8.42 ms

--- 8.8.8.8 ping statistics ---
1 packets transmitted, 1 received, 0% packet loss, time 0ms
rtt min/avg/max/mdev = 8.420/8.420/8.420/0.000 ms
`
	res := proto.PingPollResult{}
	applyParsed(&res, out, 1)
	if res.LossPct != 0 {
		t.Fatalf("want loss 0, got %v", res.LossPct)
	}
	if res.Latency < 8*time.Millisecond || res.Latency > 9*time.Millisecond {
		t.Fatalf("want ~8.42ms, got %v", res.Latency)
	}
}

func TestApplyParsedLinuxFullLoss(t *testing.T) {
	out := `PING 10.0.0.99 56(84) bytes of data.
--- 10.0.0.99 ping statistics ---
3 packets transmitted, 0 received, 100% packet loss, time 2031ms
`
	res := proto.PingPollResult{}
	applyParsed(&res, out, 3)
	if res.LossPct != 100 {
		t.Fatalf("want 100%% loss, got %v", res.LossPct)
	}
}

func TestApplyParsedWindowsSuccess(t *testing.T) {
	out := "Esecuzione di Ping 192.168.1.1 con 32 byte di dati:\r\n" +
		"Risposta da 192.168.1.1: byte=32 durata=2ms TTL=64\r\n" +
		"\r\nStatistiche Ping per 192.168.1.1:\r\n" +
		"    Pacchetti: Trasmessi = 1, Ricevuti = 1, Persi = 0 (0% persi),\r\n" +
		"Tempo approssimativo percorrenza p/r in millisecondi:\r\n" +
		"    Minimo = 2ms, Massimo = 2ms, Media = 2ms\r\n"
	res := proto.PingPollResult{}
	applyParsed(&res, out, 1)
	if res.LossPct != 0 {
		t.Fatalf("want loss 0, got %v", res.LossPct)
	}
	if res.Latency != 2*time.Millisecond {
		t.Fatalf("want 2ms, got %v", res.Latency)
	}
}
