package nettrace

import "testing"

func TestParseMTR(t *testing.T) {
	out := `Start: 2026-06-01T10:00:00+0000
HOST: probe                     Loss%   Snt   Last   Avg  Best  Wrst StDev
  1.|-- 192.168.1.1              0.0%    10    1.2   1.3   1.1   1.6   0.1
  2.|-- 10.0.0.1                20.0%    10    5.0   6.0   4.0   9.0   1.0
  3.|-- ???                    100.0%    10    0.0   0.0   0.0   0.0   0.0
  4.|-- 8.8.8.8                  0.0%    10   12.0  13.0  11.0  15.0   1.2`
	hops := ParseMTR(out)
	if len(hops) != 4 {
		t.Fatalf("attesi 4 hop, trovati %d", len(hops))
	}
	if hops[0].IP != "192.168.1.1" || hops[0].LossPct != 0 || hops[0].AvgMs != 1.3 {
		t.Errorf("hop1 errato: %+v", hops[0])
	}
	if hops[1].LossPct != 20 {
		t.Errorf("hop2 loss atteso 20, %v", hops[1].LossPct)
	}
	if !hops[2].Timeout || hops[2].LossPct != 100 {
		t.Errorf("hop3 dovrebbe essere timeout 100%%: %+v", hops[2])
	}
	if hops[3].IP != "8.8.8.8" {
		t.Errorf("hop4 ip errato: %+v", hops[3])
	}
}

func TestParseTraceroute(t *testing.T) {
	out := `traceroute to 8.8.8.8 (8.8.8.8), 30 hops max, 60 byte packets
 1  192.168.1.1  1.234 ms  1.111 ms  1.222 ms
 2  * * *
 3  8.8.8.8  12.5 ms  11.9 ms  13.1 ms`
	hops := ParseTraceroute(out)
	if len(hops) != 3 {
		t.Fatalf("attesi 3 hop, trovati %d", len(hops))
	}
	if hops[0].IP != "192.168.1.1" || hops[0].AvgMs < 1.0 || hops[0].AvgMs > 1.5 {
		t.Errorf("hop1 errato: %+v", hops[0])
	}
	if !hops[1].Timeout || hops[1].LossPct != 100 {
		t.Errorf("hop2 dovrebbe essere timeout: %+v", hops[1])
	}
	if hops[2].IP != "8.8.8.8" {
		t.Errorf("hop3 ip errato: %+v", hops[2])
	}
}

func TestParseTracert(t *testing.T) {
	out := `
Traccia instradamento verso 8.8.8.8 su un massimo di 30 punti di passaggio

  1     1 ms     1 ms     1 ms  192.168.1.1
  2     *        *        *     Richiesta scaduta.
  3    12 ms    11 ms    13 ms  8.8.8.8

Traccia completata.`
	hops := ParseTracert(out)
	if len(hops) != 3 {
		t.Fatalf("attesi 3 hop, trovati %d", len(hops))
	}
	if hops[0].IP != "192.168.1.1" {
		t.Errorf("hop1 ip errato: %+v", hops[0])
	}
	if !hops[1].Timeout {
		t.Errorf("hop2 dovrebbe essere timeout: %+v", hops[1])
	}
	if hops[2].IP != "8.8.8.8" || hops[2].AvgMs != 12 {
		t.Errorf("hop3 errato: %+v", hops[2])
	}
}

func TestNormalizeDefaults(t *testing.T) {
	a := Args{Target: " 1.2.3.4 "}
	a.normalize()
	if a.Target != "1.2.3.4" || a.Mode != "icmp" || a.Port != 443 || a.MaxHops != 30 || a.Count != 10 {
		t.Errorf("default errati: %+v", a)
	}
}
