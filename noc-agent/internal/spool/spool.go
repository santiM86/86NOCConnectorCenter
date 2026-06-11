// Package spool implements a persistent store-and-forward buffer for
// frames that cannot be delivered immediately to the backend.
//
// Inspired by the Zabbix Proxy buffer model: when the upstream link is
// down (or local in-memory queue saturates), polling results, logs and
// events are persisted to a local BoltDB file. As soon as the link is
// back the forwarder drains the spool in FIFO order and sends frames
// in batches to the backend. Each batch is acknowledged with a list
// of `seq` numbers — only acknowledged entries are removed from the
// spool, so a crash mid-flight cannot lose telemetry.
//
// Capacity is bounded (`MaxFrames`): once exceeded the oldest entries
// are dropped, preserving freshness for live monitoring at the cost
// of historical replay (same trade-off as `ProxyBufferMode=memory` on
// Zabbix small proxies). A counter is exposed for observability.
//
// Storage backend: BBolt — a pure-Go embedded KV store with crash
// safety via MVCC. No cgo, cross-compiles to Windows / Linux / macOS.
package spool

import (
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"sync/atomic"
	"time"

	bolt "go.etcd.io/bbolt"
)

const (
	bucketPending = "pending"
	bucketMeta    = "meta"
)

// Frame is the persistent envelope. Payload is opaque (JSON bytes of
// the WS Frame as produced by transport/ws.go). We do NOT decode the
// frame here — the spool only owns ordering, durability and ACKs.
type Frame struct {
	ID        uint64    `json:"id"`         // monotonic 8-byte big-endian key in bbolt
	Type      string    `json:"type"`       // agent.event / agent.log / ... (for stats only)
	Payload   []byte    `json:"payload"`    // raw JSON of proto.Frame
	CreatedAt time.Time `json:"created_at"` // when first enqueued
	Attempts  uint32    `json:"attempts"`   // forwarder retries
}

// Stats is exposed via the agent heartbeat so the NOC can show
// "spool depth = N, oldest = Xs ago, dropped since start = K".
type Stats struct {
	Depth        int       `json:"depth"`
	OldestAt     time.Time `json:"oldest_at,omitempty"`
	DroppedTotal uint64    `json:"dropped_total"`
	EnqueuedTotal uint64   `json:"enqueued_total"`
	AckedTotal   uint64    `json:"acked_total"`
}

// Spool persists frames that could not be delivered immediately.
// All methods are safe for concurrent use.
type Spool struct {
	db   *bolt.DB
	path string

	maxFrames int

	mu sync.Mutex // protects nextID
	// nextID is the monotonic key used when enqueueing. We persist
	// the last value in bucketMeta so wrap-around doesn't reuse keys
	// after restarts.
	nextID uint64

	droppedTotal  atomic.Uint64
	enqueuedTotal atomic.Uint64
	ackedTotal    atomic.Uint64
}

// Open creates or reopens a spool file. path is typically
// $LocalAppData/Argus/spool.db on Windows, /var/lib/argus/spool.db on
// Linux. maxFrames bounds the spool depth: 0 means default (100k).
func Open(path string, maxFrames int) (*Spool, error) {
	if maxFrames <= 0 {
		maxFrames = 100_000
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return nil, fmt.Errorf("spool: mkdir: %w", err)
	}
	// Timeout 5s so a stale lock from a crashed sibling does not hang
	// the agent boot — we will log and continue without persistence
	// (caller can decide to retry).
	db, err := bolt.Open(path, 0o600, &bolt.Options{Timeout: 5 * time.Second})
	if err != nil {
		return nil, fmt.Errorf("spool: open %q: %w", path, err)
	}
	s := &Spool{db: db, path: path, maxFrames: maxFrames}

	if err := db.Update(func(tx *bolt.Tx) error {
		if _, e := tx.CreateBucketIfNotExists([]byte(bucketPending)); e != nil {
			return e
		}
		b, e := tx.CreateBucketIfNotExists([]byte(bucketMeta))
		if e != nil {
			return e
		}
		if v := b.Get([]byte("next_id")); len(v) == 8 {
			s.nextID = binary.BigEndian.Uint64(v)
		}
		// Backfill: if there are existing entries with a key > nextID
		// (should not happen normally) re-sync to the actual max so we
		// never collide on Enqueue after a partial crash.
		pb := tx.Bucket([]byte(bucketPending))
		if pb != nil {
			if k, _ := pb.Cursor().Last(); k != nil && len(k) == 8 {
				maxK := binary.BigEndian.Uint64(k)
				if maxK > s.nextID {
					s.nextID = maxK
				}
			}
		}
		return nil
	}); err != nil {
		_ = db.Close()
		return nil, fmt.Errorf("spool: init buckets: %w", err)
	}
	return s, nil
}

// Close releases the underlying file lock.
func (s *Spool) Close() error {
	if s == nil || s.db == nil {
		return nil
	}
	return s.db.Close()
}

// Path returns the on-disk path of the spool file (for logs).
func (s *Spool) Path() string { return s.path }

// Enqueue persists one frame. If the spool is at MaxFrames the oldest
// entry is dropped before the new one is appended, and DroppedTotal is
// incremented (so the heartbeat can warn).
func (s *Spool) Enqueue(frameType string, payload []byte) error {
	if s == nil || s.db == nil {
		return errors.New("spool: closed")
	}
	s.mu.Lock()
	s.nextID++
	id := s.nextID
	s.mu.Unlock()

	env := Frame{
		ID:        id,
		Type:      frameType,
		Payload:   payload,
		CreatedAt: time.Now().UTC(),
	}
	enc, err := json.Marshal(env)
	if err != nil {
		return fmt.Errorf("spool: marshal: %w", err)
	}
	key := make([]byte, 8)
	binary.BigEndian.PutUint64(key, id)

	return s.db.Update(func(tx *bolt.Tx) error {
		b := tx.Bucket([]byte(bucketPending))
		if b == nil {
			return errors.New("spool: pending bucket missing")
		}
		// Drop oldest until under cap (-1 because we are about to insert)
		st := b.Stats()
		if st.KeyN >= s.maxFrames {
			c := b.Cursor()
			toDrop := st.KeyN - s.maxFrames + 1
			for k, _ := c.First(); k != nil && toDrop > 0; k, _ = c.Next() {
				if e := b.Delete(k); e != nil {
					return e
				}
				toDrop--
				s.droppedTotal.Add(1)
			}
		}
		if err := b.Put(key, enc); err != nil {
			return err
		}
		// Persist nextID so a restart doesn't reuse it
		mb := tx.Bucket([]byte(bucketMeta))
		buf := make([]byte, 8)
		binary.BigEndian.PutUint64(buf, id)
		if err := mb.Put([]byte("next_id"), buf); err != nil {
			return err
		}
		s.enqueuedTotal.Add(1)
		return nil
	})
}

// Drain returns up to batchSize oldest frames WITHOUT removing them.
// The caller forwards them and calls Ack(ids) on success. Frames stay
// in the spool until acknowledged, so a forwarder crash will simply
// re-send them on next start (at-least-once semantics).
func (s *Spool) Drain(batchSize int) ([]Frame, error) {
	if s == nil || s.db == nil {
		return nil, errors.New("spool: closed")
	}
	if batchSize <= 0 {
		batchSize = 256
	}
	out := make([]Frame, 0, batchSize)
	err := s.db.View(func(tx *bolt.Tx) error {
		b := tx.Bucket([]byte(bucketPending))
		if b == nil {
			return nil
		}
		c := b.Cursor()
		for k, v := c.First(); k != nil && len(out) < batchSize; k, v = c.Next() {
			var f Frame
			if e := json.Unmarshal(v, &f); e != nil {
				// Corrupted entry — skip but don't fail the whole drain.
				// Forwarder can issue a separate Compact() to remove it.
				continue
			}
			out = append(out, f)
		}
		return nil
	})
	return out, err
}

// Ack removes the specified ids from the spool. Idempotent: missing
// ids are silently ignored. Returns the number of entries actually
// removed (useful for metrics).
func (s *Spool) Ack(ids []uint64) (int, error) {
	if s == nil || s.db == nil {
		return 0, errors.New("spool: closed")
	}
	if len(ids) == 0 {
		return 0, nil
	}
	removed := 0
	err := s.db.Update(func(tx *bolt.Tx) error {
		b := tx.Bucket([]byte(bucketPending))
		if b == nil {
			return nil
		}
		key := make([]byte, 8)
		for _, id := range ids {
			binary.BigEndian.PutUint64(key, id)
			if v := b.Get(key); v != nil {
				if e := b.Delete(key); e != nil {
					return e
				}
				removed++
			}
		}
		return nil
	})
	if err == nil {
		s.ackedTotal.Add(uint64(removed))
	}
	return removed, err
}

// Stats returns a snapshot of the spool for the heartbeat.
func (s *Spool) Stats() Stats {
	st := Stats{
		DroppedTotal:  s.droppedTotal.Load(),
		EnqueuedTotal: s.enqueuedTotal.Load(),
		AckedTotal:    s.ackedTotal.Load(),
	}
	if s == nil || s.db == nil {
		return st
	}
	_ = s.db.View(func(tx *bolt.Tx) error {
		b := tx.Bucket([]byte(bucketPending))
		if b == nil {
			return nil
		}
		st.Depth = b.Stats().KeyN
		if k, v := b.Cursor().First(); k != nil {
			var f Frame
			if json.Unmarshal(v, &f) == nil {
				st.OldestAt = f.CreatedAt
			}
		}
		return nil
	})
	return st
}

// Depth is a fast path for tests / spot checks (no oldest lookup).
func (s *Spool) Depth() int {
	if s == nil || s.db == nil {
		return 0
	}
	depth := 0
	_ = s.db.View(func(tx *bolt.Tx) error {
		if b := tx.Bucket([]byte(bucketPending)); b != nil {
			depth = b.Stats().KeyN
		}
		return nil
	})
	return depth
}
