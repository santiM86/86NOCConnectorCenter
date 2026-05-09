// Package transport owns the persistent WebSocket connection to the
// 86NOC backend. It handles:
//
//   - hello/welcome handshake
//   - automatic reconnect with exponential backoff and jitter
//   - server-initiated keepalive (server.ping) and client-side heartbeat
//   - command dispatch to registered handlers
//   - outbound event/log queue with backpressure
//
// The contract is intentionally small: callers get a Client they can call
// PushEvent / PushLog on, and they Register command handlers. All wire
// concerns live here.
package transport

import (
	"context"
	"crypto/rand"
	"crypto/tls"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/http"
	"runtime"
	"sync"
	"sync/atomic"
	"time"

	"github.com/coder/websocket"

	"github.com/86bit/noc-agent/internal/config"
	"github.com/86bit/noc-agent/internal/logging"
	"github.com/86bit/noc-agent/pkg/proto"
)

// CommandHandler reacts to a server.command frame and returns the payload
// that will be wrapped into agent.reply. Returning an error produces a
// non-OK reply with Error set.
type CommandHandler func(ctx context.Context, args json.RawMessage) (any, error)

// Client is a long-lived WebSocket client with auto-reconnect.
type Client struct {
	cfg config.Config
	log *logging.Logger

	hello proto.AgentHello

	out       chan proto.Frame
	commands  map[string]CommandHandler
	cmdMu     sync.RWMutex
	seq       atomic.Uint64
	connected atomic.Bool

	// last welcome (config push from server) is exposed for the orchestrator
	welcomeMu sync.Mutex
	welcome   *proto.ServerWelcome
}

// New builds a Client. hello must contain identity + capabilities; backend
// uses it to authenticate and tag the session.
func New(cfg config.Config, log *logging.Logger, hello proto.AgentHello) *Client {
	return &Client{
		cfg:      cfg,
		log:      log.With("transport"),
		hello:    hello,
		out:      make(chan proto.Frame, 256),
		commands: make(map[string]CommandHandler),
	}
}

// Register installs a handler for a server command name. Registering the
// same name twice replaces the previous handler.
func (c *Client) Register(name string, h CommandHandler) {
	c.cmdMu.Lock()
	defer c.cmdMu.Unlock()
	c.commands[name] = h
}

// Connected reports the current connection state.
func (c *Client) Connected() bool { return c.connected.Load() }

// LastWelcome returns the most recent ServerWelcome (config push), or nil
// if the agent has not yet completed a handshake.
func (c *Client) LastWelcome() *proto.ServerWelcome {
	c.welcomeMu.Lock()
	defer c.welcomeMu.Unlock()
	return c.welcome
}

// PushEvent enqueues an unsolicited event toward the server. Returns
// false if the queue is full (backpressure).
func (c *Client) PushEvent(kind string, data any) bool {
	raw, err := json.Marshal(data)
	if err != nil {
		c.log.Errorf("marshal event %s: %v", kind, err)
		return false
	}
	ev, _ := json.Marshal(proto.AgentEvent{Kind: kind, Data: raw})
	return c.enqueue(proto.TypeAgentEvent, ev, "")
}

// PushLog enqueues a log entry toward the server.
func (c *Client) PushLog(e logging.Entry) bool {
	payload, _ := json.Marshal(proto.AgentLog{
		Level: e.Level, Module: e.Module, Msg: e.Msg, Fields: e.Fields,
	})
	return c.enqueue(proto.TypeAgentLog, payload, "")
}

// PushHeartbeat enqueues an agent heartbeat with self-telemetry.
func (c *Client) PushHeartbeat(hb proto.AgentHeartbeat) bool {
	payload, _ := json.Marshal(hb)
	return c.enqueue(proto.TypeAgentHeartbeat, payload, "")
}

func (c *Client) enqueue(typ string, payload json.RawMessage, corrID string) bool {
	f := proto.Frame{
		V:       proto.ProtocolVersion,
		Type:    typ,
		Seq:     c.seq.Add(1),
		CorrID:  corrID,
		SentAt:  time.Now().UTC(),
		Payload: payload,
	}
	select {
	case c.out <- f:
		return true
	default:
		return false
	}
}

// Run connects to the backend and blocks until ctx is done. It loops
// forever, reconnecting with backoff after every failure.
func (c *Client) Run(ctx context.Context) {
	backoff := c.cfg.ReconnectMin
	for {
		if ctx.Err() != nil {
			return
		}
		if err := c.session(ctx); err != nil && !errors.Is(err, context.Canceled) {
			c.log.Warn("session ended", "err", err.Error(), "next_retry", backoff.String())
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(jitter(backoff)):
		}
		backoff = nextBackoff(backoff, c.cfg.ReconnectMax)
	}
}

func (c *Client) session(parent context.Context) error {
	dialCtx, cancel := context.WithTimeout(parent, 15*time.Second)
	defer cancel()

	httpClient := &http.Client{
		Transport: &http.Transport{
			TLSClientConfig:       &tls.Config{InsecureSkipVerify: c.cfg.Backend.InsecureSkip}, //nolint:gosec
			ResponseHeaderTimeout: 15 * time.Second,
			DialContext:           (&net.Dialer{Timeout: 10 * time.Second}).DialContext,
		},
	}

	hdr := http.Header{}
	hdr.Set("Authorization", "Bearer "+c.cfg.Token)
	hdr.Set("X-Agent-Id", c.hello.AgentID)
	hdr.Set("X-Client-Id", c.cfg.ClientID)
	hdr.Set("User-Agent", fmt.Sprintf("86NocAgent/%s (%s/%s)", c.hello.AgentVersion, runtime.GOOS, runtime.GOARCH))

	conn, _, err := websocket.Dial(dialCtx, c.cfg.Backend.URL, &websocket.DialOptions{
		HTTPClient: httpClient,
		HTTPHeader: hdr,
	})
	if err != nil {
		return fmt.Errorf("dial: %w", err)
	}
	conn.SetReadLimit(1 << 20) // 1 MiB

	c.connected.Store(true)
	c.log.Info("connected", "url", c.cfg.Backend.URL)
	defer func() {
		c.connected.Store(false)
		_ = conn.Close(websocket.StatusNormalClosure, "bye")
	}()

	// Send hello synchronously so it is the very first frame on the wire,
	// before the writeLoop drains any logs that accumulated while we were
	// disconnected. The server expects agent.hello as the first message.
	helloPayload, _ := json.Marshal(c.hello)
	helloFrame := proto.Frame{
		V:       proto.ProtocolVersion,
		Type:    proto.TypeAgentHello,
		Seq:     c.seq.Add(1),
		SentAt:  time.Now().UTC(),
		Payload: helloPayload,
	}
	helloBytes, err := json.Marshal(helloFrame)
	if err != nil {
		return fmt.Errorf("marshal hello: %w", err)
	}
	hctx, hcancel := context.WithTimeout(parent, 10*time.Second)
	if err := conn.Write(hctx, websocket.MessageText, helloBytes); err != nil {
		hcancel()
		return fmt.Errorf("write hello: %w", err)
	}
	hcancel()

	sessCtx, cancelSess := context.WithCancel(parent)
	defer cancelSess()

	errCh := make(chan error, 2)
	go func() { errCh <- c.writeLoop(sessCtx, conn) }()
	go func() { errCh <- c.readLoop(sessCtx, conn) }()

	return <-errCh
}

func (c *Client) writeLoop(ctx context.Context, conn *websocket.Conn) error {
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case f := <-c.out:
			data, err := json.Marshal(f)
			if err != nil {
				c.log.Errorf("marshal frame: %v", err)
				continue
			}
			wctx, cancel := context.WithTimeout(ctx, 10*time.Second)
			err = conn.Write(wctx, websocket.MessageText, data)
			cancel()
			if err != nil {
				return fmt.Errorf("write: %w", err)
			}
		}
	}
}

func (c *Client) readLoop(ctx context.Context, conn *websocket.Conn) error {
	for {
		_, data, err := conn.Read(ctx)
		if err != nil {
			return fmt.Errorf("read: %w", err)
		}
		var f proto.Frame
		if err := json.Unmarshal(data, &f); err != nil {
			c.log.Warn("malformed frame", "err", err.Error())
			continue
		}
		c.dispatch(ctx, f)
	}
}

func (c *Client) dispatch(ctx context.Context, f proto.Frame) {
	switch f.Type {
	case proto.TypeServerWelcome:
		var w proto.ServerWelcome
		if err := json.Unmarshal(f.Payload, &w); err == nil {
			c.welcomeMu.Lock()
			c.welcome = &w
			c.welcomeMu.Unlock()
			c.log.Info("welcome received", "session_id", w.SessionID)
		}
	case proto.TypeServerPing:
		// reply with an empty heartbeat; backend uses it as RTT measurement
		_ = c.enqueue(proto.TypeAgentReply, json.RawMessage(`{"ok":true}`), f.CorrID)
	case proto.TypeServerCommand:
		go c.handleCommand(ctx, f)
	case proto.TypeServerConfig:
		// future: hot-reload runtime config; for now just log
		c.log.Info("server.config received (hot reload not yet wired)")
	default:
		c.log.Warn("unknown frame type", "type", f.Type)
	}
}

func (c *Client) handleCommand(ctx context.Context, f proto.Frame) {
	var cmd proto.ServerCommand
	if err := json.Unmarshal(f.Payload, &cmd); err != nil {
		c.replyErr(f.CorrID, fmt.Errorf("bad command payload: %w", err))
		return
	}
	c.cmdMu.RLock()
	h, ok := c.commands[cmd.Name]
	c.cmdMu.RUnlock()
	if !ok {
		c.replyErr(f.CorrID, fmt.Errorf("unknown command %q", cmd.Name))
		return
	}
	cctx, cancel := context.WithTimeout(ctx, 60*time.Second)
	defer cancel()
	res, err := h(cctx, cmd.Args)
	if err != nil {
		c.replyErr(f.CorrID, err)
		return
	}
	raw, _ := json.Marshal(res)
	reply, _ := json.Marshal(proto.AgentReply{OK: true, Result: raw})
	c.enqueue(proto.TypeAgentReply, reply, f.CorrID)
}

func (c *Client) replyErr(corrID string, err error) {
	reply, _ := json.Marshal(proto.AgentReply{OK: false, Error: err.Error()})
	c.enqueue(proto.TypeAgentReply, reply, corrID)
}

func nextBackoff(cur, max time.Duration) time.Duration {
	next := cur * 2
	if next > max {
		return max
	}
	return next
}

func jitter(d time.Duration) time.Duration {
	var b [2]byte
	_, _ = rand.Read(b[:])
	frac := float64(uint16(b[0])<<8|uint16(b[1])) / 65535.0
	return d + time.Duration(float64(d)*0.25*frac)
}

// NewAgentID returns a fresh hex-encoded random id (used at first start).
func NewAgentID() string {
	var b [16]byte
	_, _ = rand.Read(b[:])
	return hex.EncodeToString(b[:])
}
