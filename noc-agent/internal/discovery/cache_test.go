package discovery

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/86bit/noc-agent/internal/logging"
	"github.com/86bit/noc-agent/pkg/proto"
)

func TestWriteAndLoadCacheRoundtrip(t *testing.T) {
	tmp := t.TempDir()
	cache := filepath.Join(tmp, "discovery_cache.json")

	m := NewManager(logging.New(), time.Minute, nil, nil)
	m.SetCachePath(cache)

	now := time.Now().UTC()
	m.mu.Lock()
	m.endpoints["10.0.0.1"] = proto.DiscoveredEndpoint{
		IP: "10.0.0.1", MAC: "aa:bb:cc:dd:ee:ff", Hostname: "router",
		Vendor: "Cisco", Source: "arp",
		FirstSeenAt: now.Add(-time.Hour), LastSeenAt: now,
	}
	m.endpoints["10.0.0.2"] = proto.DiscoveredEndpoint{
		IP: "10.0.0.2", Hostname: "printer", Source: "mdns",
		FirstSeenAt: now, LastSeenAt: now,
	}
	m.lastScanAt = now
	m.mu.Unlock()

	if err := m.WriteCache(); err != nil {
		t.Fatalf("WriteCache: %v", err)
	}
	if _, err := os.Stat(cache); err != nil {
		t.Fatalf("cache file not created: %v", err)
	}

	m2 := NewManager(logging.New(), time.Minute, nil, nil)
	m2.SetCachePath(cache)
	if err := m2.LoadCache(); err != nil {
		t.Fatalf("LoadCache: %v", err)
	}
	got := m2.Snapshot()
	if len(got) != 2 {
		t.Fatalf("expected 2 endpoints after load, got %d", len(got))
	}
	if got[0].IP != "10.0.0.1" || got[1].IP != "10.0.0.2" {
		t.Fatalf("unexpected order/IPs: %+v", got)
	}
	if got[0].Hostname != "router" {
		t.Fatalf("missing hostname: %+v", got[0])
	}
}

func TestForceTriggerConsumed(t *testing.T) {
	tmp := t.TempDir()
	trigger := filepath.Join(tmp, "rescan.tick")

	m := NewManager(logging.New(), time.Minute, nil, nil)
	m.SetForceTriggerPath(trigger)

	if m.consumeForceTrigger() {
		t.Fatal("expected false when trigger file absent")
	}

	if err := os.WriteFile(trigger, []byte("now"), 0o644); err != nil {
		t.Fatal(err)
	}
	if !m.consumeForceTrigger() {
		t.Fatal("expected true when trigger file present")
	}
	if _, err := os.Stat(trigger); !os.IsNotExist(err) {
		t.Fatalf("trigger file should be deleted, err=%v", err)
	}
	if m.consumeForceTrigger() {
		t.Fatal("expected false after consume")
	}
}

func TestLoadCacheDropsStaleEntries(t *testing.T) {
	tmp := t.TempDir()
	cache := filepath.Join(tmp, "c.json")

	m := NewManager(logging.New(), time.Minute, nil, nil)
	m.SetCachePath(cache)
	m.retainAfter = 10 * time.Minute

	old := time.Now().UTC().Add(-30 * time.Minute)
	fresh := time.Now().UTC().Add(-time.Minute)
	m.mu.Lock()
	m.endpoints["1.1.1.1"] = proto.DiscoveredEndpoint{IP: "1.1.1.1", LastSeenAt: old}
	m.endpoints["2.2.2.2"] = proto.DiscoveredEndpoint{IP: "2.2.2.2", LastSeenAt: fresh}
	m.mu.Unlock()

	if err := m.WriteCache(); err != nil {
		t.Fatal(err)
	}
	m2 := NewManager(logging.New(), time.Minute, nil, nil)
	m2.SetCachePath(cache)
	m2.retainAfter = 10 * time.Minute
	if err := m2.LoadCache(); err != nil {
		t.Fatal(err)
	}
	got := m2.Snapshot()
	if len(got) != 1 || got[0].IP != "2.2.2.2" {
		t.Fatalf("expected only fresh entry, got %+v", got)
	}
}
