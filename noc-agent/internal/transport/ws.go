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
        "strings"
        "sync"
        "sync/atomic"
        "time"

	"github.com/coder/websocket"

	"github.com/86bit/noc-agent/internal/config"
	"github.com/86bit/noc-agent/internal/logging"
	"github.com/86bit/noc-agent/internal/spool"
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
        // onWelcome is invoked (in the dispatch goroutine) every time the
        // server sends a server.welcome frame. Lets the orchestrator hot-apply
        // config without polling LastWelcome().
        onWelcome func(*proto.ServerWelcome)

        // v2026-06-04: rate-limited drop logging quando la queue `out` si
        // satura sotto burst. Senza questo i poll SNMP venivano persi
        // silenziosamente e il backend mostrava device come stale.
        dropMu      sync.Mutex
        dropCount   int
        lastDropLog time.Time

        // v4.23 — Zabbix-Proxy-style store-and-forward fallback.
        // Used whenever (a) the WS link is down, or (b) the in-memory
        // `out` channel is saturated. A forwarder goroutine drains
        // the spool back into `out` whenever the link is up again.
        spool *spool.Spool
}

// SetSpool installs the persistent store-and-forward buffer. Must be
// called BEFORE Run() — otherwise frames produced during early start
// will be dropped on disconnect. Pass nil to keep the legacy in-memory
// only behaviour.
func (c *Client) SetSpool(sp *spool.Spool) { c.spool = sp }

// SpoolStats exposes spool depth/oldest entry for the heartbeat.
// Returns zero value if no spool is wired.
func (c *Client) SpoolStats() spool.Stats {
        if c.spool == nil {
                return spool.Stats{}
        }
        return c.spool.Stats()
}

// OnWelcome registers a callback fired when the server sends server.welcome.
// The handler runs in the dispatch goroutine, so keep it cheap.
func (c *Client) OnWelcome(fn func(*proto.ServerWelcome)) {
        c.welcomeMu.Lock()
        c.onWelcome = fn
        c.welcomeMu.Unlock()
}

// New builds a Client. hello must contain identity + capabilities; backend
// uses it to authenticate and tag the session.
func New(cfg config.Config, log *logging.Logger, hello proto.AgentHello) *Client {
        return &Client{
                cfg:      cfg,
                log:      log.With("transport"),
                hello:    hello,
                out:      make(chan proto.Frame, 2048),
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
        // v4.23 store-and-forward path: if the WS link is currently down,
        // skip the in-memory queue entirely and persist to spool. This
        // prevents the in-mem queue from being filled with stale frames
        // and lets the forwarder replay them in FIFO order on resume.
        if c.spool != nil && !c.connected.Load() {
                if data, err := json.Marshal(f); err == nil {
                        if e := c.spool.Enqueue(typ, data); e == nil {
                                return true
                        } else {
                                c.log.Warn("spool enqueue failed (offline)", "err", e.Error())
                        }
                }
                // fall through to in-mem queue as last-resort buffer
        }
        // v2026-06-04 fix critico "silenzio backend": prima il drop su queue
        // piena era silenzioso e i poll result SNMP venivano persi → backend
        // non riceveva mai update di last_poll → device apparivano stale per
        // settimane. Ora: fast-path → slow-path 5s → spool fallback → drop
        // con log aggregato (rate-limit 30s per evitare flood).
        select {
        case c.out <- f:
                return true
        default:
        }
        select {
        case c.out <- f:
                return true
        case <-time.After(5 * time.Second):
                // v4.23: prima del drop, prova a persistere su spool.
                // Cosi' anche sotto burst saturanti i dati non si perdono.
                if c.spool != nil {
                        if data, err := json.Marshal(f); err == nil {
                                if e := c.spool.Enqueue(typ, data); e == nil {
                                        return true
                                }
                        }
                }
                c.dropMu.Lock()
                c.dropCount++
                shouldLog := time.Since(c.lastDropLog) > 30*time.Second
                cnt := c.dropCount
                if shouldLog {
                        c.lastDropLog = time.Now()
                        c.dropCount = 0
                }
                c.dropMu.Unlock()
                if shouldLog {
                        c.log.Warn("ws send queue saturated, dropping frames",
                                "dropped_in_window", fmt.Sprintf("%d", cnt),
                                "frame_type", typ,
                                "queue_capacity", fmt.Sprintf("%d", cap(c.out)))
                }
                return false
        }
}

// Run connects to the backend and blocks until ctx is done. It loops
// forever, reconnecting with backoff after every failure.
func (c *Client) Run(ctx context.Context) {
        // v4.23: avvia il forwarder dello spool in parallelo al loop di
        // reconnect. E' safe se spool e' nil (la goroutine esce subito).
        if c.spool != nil {
                go c.spoolForwarderLoop(ctx)
        }
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

        // Difesa contro agent.yaml "naked" (es. "https://argus.86bit.it" o
        // "wss://argus.86bit.it" senza il path /api/agent/ws). E' una
        // regressione che si manifesta come "expected handshake response
        // status code 101 but got 200" (server risponde con HTML del
        // frontend). Normalizziamo l'URL appendendo /api/agent/ws se
        // manca. La WebSocket library accetta sia http:// che ws://.
        wsURL := c.cfg.Backend.URL
        if !strings.HasSuffix(wsURL, "/api/agent/ws") {
                wsURL = strings.TrimRight(wsURL, "/") + "/api/agent/ws"
        }

        // Log DETTAGLIATO del tentativo di connessione: utile per debug
        // in produzione (perche' il WS non si aggancia? wrong URL? token
        // scaduto? proxy aziendale che blocca?).
        c.log.Info("ws dial attempt",
                "url", wsURL,
                "client_id", c.cfg.ClientID,
                "agent_id", c.hello.AgentID,
                "token_prefix", tokenPrefix(c.cfg.Token),
                "insecure_skip_tls", fmt.Sprintf("%t", c.cfg.Backend.InsecureSkip),
        )
        conn, _, err := websocket.Dial(dialCtx, wsURL, &websocket.DialOptions{
                HTTPClient: httpClient,
                HTTPHeader: hdr,
        })
        if err != nil {
                c.log.Error("ws dial failed",
                        "url", wsURL,
                        "err", err.Error(),
                )
                return fmt.Errorf("dial: %w", err)
        }
        conn.SetReadLimit(1 << 20) // 1 MiB

        c.connected.Store(true)
        c.log.Info("connected", "url", wsURL)
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

        errCh := make(chan error, 3)
        go func() { errCh <- c.writeLoop(sessCtx, conn) }()
        go func() { errCh <- c.readLoop(sessCtx, conn) }()
        // v4.14.x: client-side keepalive — WebSocket protocol-level Ping ogni
        // 25 sec. Critico per LAN con NAT/firewall (es. Galvan) che killano
        // connessioni TCP idle dopo 60-120 sec. Senza traffico WS visibile
        // (es. nessun command, nessun event), il dispositivo intermedio
        // chiude la sessione → "read tcp: failed to read frame header"
        // → reconnect + bounce dei dispositivi monitorati per 5-10 sec.
        go func() { errCh <- c.keepaliveLoop(sessCtx, conn) }()

        return <-errCh
}

// keepaliveLoop invia un Ping WebSocket protocol-level ogni 25 secondi per
// mantenere viva la TCP connection contro idle-timeout di NAT/firewall.
// Se Pong non arriva entro 10 sec, restituisce errore -> readLoop/writeLoop
// vengono interrotti e la sessione si chiude pulita -> reconnect immediato.
func (c *Client) keepaliveLoop(ctx context.Context, conn *websocket.Conn) error {
        tk := time.NewTicker(25 * time.Second)
        defer tk.Stop()
        for {
                select {
                case <-ctx.Done():
                        return ctx.Err()
                case <-tk.C:
                        pctx, cancel := context.WithTimeout(ctx, 10*time.Second)
                        if err := conn.Ping(pctx); err != nil {
                                cancel()
                                c.log.Warn("ws keepalive ping failed", "err", err.Error())
                                return fmt.Errorf("keepalive ping: %w", err)
                        }
                        cancel()
                }
        }
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
                        cb := c.onWelcome
                        c.welcomeMu.Unlock()
                        c.log.Info("welcome received", "session_id", w.SessionID)
                        if cb != nil {
                                cb(&w)
                        }
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

// spoolForwarderLoop periodically drains the persistent spool into the
// in-memory `out` channel whenever the WS link is up. Each frame is
// removed from the spool only AFTER it has been accepted into `out`
// (handing off ownership to writeLoop). If the channel is saturated,
// the frame stays in the spool and is retried next cycle.
//
// This is the at-least-once forwarder: a writeLoop crash mid-flight
// will resurface the frame on the next session (TCP-level), but the
// duplicate window is bounded by FlushInterval (~2s by default).
func (c *Client) spoolForwarderLoop(ctx context.Context) {
        if c.spool == nil {
                return
        }
        flush := c.cfg.Spool.FlushInterval
        if flush <= 0 {
                flush = 2 * time.Second
        }
        batchSize := c.cfg.Spool.BatchSize
        if batchSize <= 0 {
                batchSize = 256
        }
        tk := time.NewTicker(flush)
        defer tk.Stop()
        for {
                select {
                case <-ctx.Done():
                        return
                case <-tk.C:
                }
                if !c.connected.Load() {
                        continue
                }
                frames, err := c.spool.Drain(batchSize)
                if err != nil {
                        c.log.Warn("spool drain failed", "err", err.Error())
                        continue
                }
                if len(frames) == 0 {
                        continue
                }
                acked := make([]uint64, 0, len(frames))
                for _, sf := range frames {
                        var pf proto.Frame
                        if err := json.Unmarshal(sf.Payload, &pf); err != nil {
                                // Corrupted spool entry — ack to remove it so
                                // it doesn't block the queue forever.
                                acked = append(acked, sf.ID)
                                continue
                        }
                        select {
                        case c.out <- pf:
                                acked = append(acked, sf.ID)
                        case <-ctx.Done():
                                // best-effort ack what we got so far and exit
                                if len(acked) > 0 {
                                        _, _ = c.spool.Ack(acked)
                                }
                                return
                        case <-time.After(200 * time.Millisecond):
                                // give up on this frame for now; will retry next cycle
                        }
                        if !c.connected.Load() {
                                // session dropped mid-flush; stop pushing
                                break
                        }
                }
                if len(acked) > 0 {
                        if _, err := c.spool.Ack(acked); err != nil {
                                c.log.Warn("spool ack failed", "err", err.Error(), "count", fmt.Sprintf("%d", len(acked)))
                        } else {
                                c.log.Debug("spool flushed",
                                        "acked", fmt.Sprintf("%d", len(acked)),
                                        "remaining", fmt.Sprintf("%d", c.spool.Depth()),
                                )
                        }
                }
        }
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


// tokenPrefix returns a short, safe excerpt of the token for log output.
// We never log the full token to avoid leaking credentials in case the log
// file is shared for support; the prefix is enough to confirm "il token che
// l'agent sta usando e' quello giusto" (compare con la pagina Clienti).
func tokenPrefix(token string) string {
        if token == "" {
                return "(empty)"
        }
        if len(token) <= 8 {
                return token[:len(token)/2] + "..."
        }
        return token[:8] + "..."
}
