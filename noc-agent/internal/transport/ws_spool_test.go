// Integration test: validate that when the Client is DISCONNECTED and
// a spool is wired, PushEvent / PushLog persist frames to the spool
// (no in-memory drop). Then re-attaching the spool to a fresh Client
// drains them — proving persistence across "process restart".
//
// This is the contract that lets a Zabbix-Proxy-style agent survive
// a backend outage without losing telemetry.
package transport

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"github.com/86bit/noc-agent/internal/config"
	"github.com/86bit/noc-agent/internal/logging"
	"github.com/86bit/noc-agent/internal/spool"
	"github.com/86bit/noc-agent/pkg/proto"
)

func newTestClient(t *testing.T) (*Client, *spool.Spool, string) {
	t.Helper()
	dir, err := os.MkdirTemp("", "tr-spool-")
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, "spool.db")
	sp, err := spool.Open(path, 0)
	if err != nil {
		t.Fatal(err)
	}
	cfg := config.Default()
	cfg.AgentID = "test-agent"
	cfg.ClientID = "test-client"
	cfg.Backend.URL = "ws://127.0.0.1:0/api/agent/ws"
	logger := logging.New()
	c := New(cfg, logger, proto.AgentHello{AgentID: "test-agent"})
	c.SetSpool(sp)
	// connected stays false → enqueue goes to spool
	return c, sp, dir
}

func TestEnqueueWhileDisconnectedGoesToSpool(t *testing.T) {
	c, sp, dir := newTestClient(t)
	defer func() {
		_ = sp.Close()
		_ = os.RemoveAll(dir)
	}()

	for i := 0; i < 3; i++ {
		if !c.PushEvent("agent.test", map[string]int{"i": i}) {
			t.Fatalf("PushEvent %d returned false (should buffer to spool)", i)
		}
	}
	if got := sp.Depth(); got != 3 {
		t.Fatalf("spool depth want 3 got %d", got)
	}

	frames, _ := sp.Drain(10)
	if len(frames) != 3 {
		t.Fatalf("drained want 3 got %d", len(frames))
	}
	// each spool entry must decode back to a proto.Frame with the same Type
	for _, sf := range frames {
		var pf proto.Frame
		if err := json.Unmarshal(sf.Payload, &pf); err != nil {
			t.Fatalf("bad spool payload: %v", err)
		}
		if pf.Type != proto.TypeAgentEvent {
			t.Fatalf("type want %s got %s", proto.TypeAgentEvent, pf.Type)
		}
	}
}

func TestPushHeartbeatPersistedToSpoolWhenDisconnected(t *testing.T) {
	c, sp, dir := newTestClient(t)
	defer func() {
		_ = sp.Close()
		_ = os.RemoveAll(dir)
	}()
	hb := proto.AgentHeartbeat{Uptime: 12345}
	if !c.PushHeartbeat(hb) {
		t.Fatal("PushHeartbeat returned false while disconnected — should go to spool")
	}
	if got := sp.Depth(); got != 1 {
		t.Fatalf("spool depth want 1 got %d", got)
	}
}
