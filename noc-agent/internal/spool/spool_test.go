package spool

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"testing"
)

func tmpSpool(t *testing.T, cap int) *Spool {
	t.Helper()
	dir, err := os.MkdirTemp("", "spool-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(dir) })
	s, err := Open(filepath.Join(dir, "buf.db"), cap)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = s.Close() })
	return s
}

func TestEnqueueDrainAck_RoundTrip(t *testing.T) {
	s := tmpSpool(t, 0)
	for i := 0; i < 5; i++ {
		if err := s.Enqueue("agent.event", []byte(fmt.Sprintf(`{"n":%d}`, i))); err != nil {
			t.Fatalf("enqueue %d: %v", i, err)
		}
	}
	if got := s.Depth(); got != 5 {
		t.Fatalf("depth want 5 got %d", got)
	}
	frames, err := s.Drain(10)
	if err != nil {
		t.Fatal(err)
	}
	if len(frames) != 5 {
		t.Fatalf("drained want 5 got %d", len(frames))
	}
	// FIFO order — IDs must be strictly increasing
	for i := 1; i < len(frames); i++ {
		if frames[i].ID <= frames[i-1].ID {
			t.Fatalf("not FIFO: %v", frames)
		}
	}
	// Ack 3 of 5; depth must go to 2
	ids := []uint64{frames[0].ID, frames[2].ID, frames[4].ID}
	rem, err := s.Ack(ids)
	if err != nil || rem != 3 {
		t.Fatalf("ack: rem=%d err=%v", rem, err)
	}
	if got := s.Depth(); got != 2 {
		t.Fatalf("depth want 2 got %d", got)
	}
}

func TestEnqueueOverCapacityDropsOldest(t *testing.T) {
	s := tmpSpool(t, 3) // very small
	for i := 0; i < 7; i++ {
		if err := s.Enqueue("k", []byte(fmt.Sprintf(`%d`, i))); err != nil {
			t.Fatal(err)
		}
	}
	if got := s.Depth(); got != 3 {
		t.Fatalf("depth must stay at cap=3, got %d", got)
	}
	frames, _ := s.Drain(10)
	// Oldest dropped → only the last 3 payloads survive (4,5,6)
	got := make([]string, 0, len(frames))
	for _, f := range frames {
		got = append(got, string(f.Payload))
	}
	sort.Strings(got)
	want := []string{"4", "5", "6"}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("survivors=%v want=%v", got, want)
		}
	}
	st := s.Stats()
	if st.DroppedTotal != 4 {
		t.Fatalf("DroppedTotal want 4 got %d", st.DroppedTotal)
	}
}

func TestPersistenceAcrossReopen(t *testing.T) {
	dir, _ := os.MkdirTemp("", "spool-persist-")
	t.Cleanup(func() { _ = os.RemoveAll(dir) })
	path := filepath.Join(dir, "buf.db")

	s, err := Open(path, 0)
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 3; i++ {
		_ = s.Enqueue("e", []byte(fmt.Sprintf(`%d`, i)))
	}
	idsBefore := []uint64{}
	frames, _ := s.Drain(10)
	for _, f := range frames {
		idsBefore = append(idsBefore, f.ID)
	}
	_ = s.Close()

	s2, err := Open(path, 0)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = s2.Close() }()
	if got := s2.Depth(); got != 3 {
		t.Fatalf("after reopen depth want 3 got %d", got)
	}
	// next Enqueue must NOT reuse keys — id must continue monotonic
	_ = s2.Enqueue("e", []byte("new"))
	frames2, _ := s2.Drain(10)
	if len(frames2) != 4 {
		t.Fatalf("expected 4 frames after reopen+enqueue, got %d", len(frames2))
	}
	maxOld := uint64(0)
	for _, id := range idsBefore {
		if id > maxOld {
			maxOld = id
		}
	}
	newID := frames2[len(frames2)-1].ID
	if newID <= maxOld {
		t.Fatalf("new id %d must be > maxOld %d (monotonic broken)", newID, maxOld)
	}
}

func TestStatsReportOldestAndDepth(t *testing.T) {
	s := tmpSpool(t, 0)
	for i := 0; i < 4; i++ {
		_ = s.Enqueue("h", []byte("x"))
	}
	st := s.Stats()
	if st.Depth != 4 {
		t.Fatalf("depth want 4 got %d", st.Depth)
	}
	if st.OldestAt.IsZero() {
		t.Fatal("OldestAt must be set when depth>0")
	}
	if st.EnqueuedTotal != 4 {
		t.Fatalf("EnqueuedTotal want 4 got %d", st.EnqueuedTotal)
	}
}
