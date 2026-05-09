// Package webproxy implements an HTTP-over-WebSocket reverse proxy handler
// invoked when the backend receives a web console live request from a
// browser session. The agent fetches the requested URL on the local LAN
// (where the device's web UI is reachable) and returns the response so
// that the backend can stream it back to the browser through the
// catch-all /api/web-proxy/live/* endpoint.
package webproxy

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/cookiejar"
	"strings"
	"sync"
	"time"
)

// Args is the JSON shape sent by the backend (matches the legacy
// /connector/web-proxy/pending payload so the agent can be a drop-in
// replacement for the PowerShell connector).
type Args struct {
	RequestID       string            `json:"request_id"`
	SessionID       string            `json:"session_id"`
	DeviceIP        string            `json:"device_ip"`
	Port            int               `json:"port"`
	Scheme          string            `json:"scheme"` // http | https
	Path            string            `json:"path"`
	Method          string            `json:"method"`
	RequestBody     string            `json:"request_body"`
	BodyEncoding    string            `json:"request_body_encoding"`
	RequestHeaders  map[string]string `json:"request_headers"`
	SessionCookies  map[string]string `json:"session_cookies"`
}

// Result is what the agent returns. status_code/content_type/body match
// what the backend already understands from the legacy connector.
type Result struct {
	StatusCode      int                 `json:"status_code"`
	ContentType     string              `json:"content_type"`
	Body            string              `json:"body,omitempty"`
	BodyEncoding    string              `json:"body_encoding"` // text | base64
	ResponseHeaders map[string][]string `json:"response_headers"`
	Cookies         map[string]string   `json:"cookies"`
	DurationMs      int64               `json:"duration_ms"`
	Error           string              `json:"error,omitempty"`
}

// per-session cookie jars, capped to keep memory bounded. A single
// session typically corresponds to one browser tab opened on the live
// console; we evict the least recently used one when the cap is
// exceeded.
const maxJars = 100

type jarEntry struct {
	jar     *cookiejar.Jar
	lastUse time.Time
}

var (
	jarsMu sync.Mutex
	jars   = map[string]*jarEntry{}
)

func getJar(sessionID string) *cookiejar.Jar {
	jarsMu.Lock()
	defer jarsMu.Unlock()
	if e, ok := jars[sessionID]; ok {
		e.lastUse = time.Now()
		return e.jar
	}
	if len(jars) >= maxJars {
		// LRU eviction
		var oldestKey string
		var oldestAt time.Time
		first := true
		for k, e := range jars {
			if first || e.lastUse.Before(oldestAt) {
				oldestKey = k
				oldestAt = e.lastUse
				first = false
			}
		}
		if oldestKey != "" {
			delete(jars, oldestKey)
		}
	}
	j, _ := cookiejar.New(nil)
	jars[sessionID] = &jarEntry{jar: j, lastUse: time.Now()}
	return j
}

// sharedTransport is reused across all webproxy requests so HTTP/HTTPS
// connections to LAN devices benefit from keep-alive and connection
// pooling. Building a fresh transport per request — as the original
// code did — defeated keep-alive and produced a fresh TCP/TLS handshake
// for every browser asset (CSS, JS, images) loaded through the proxy.
var sharedTransport = &http.Transport{
	TLSClientConfig:     &tls.Config{InsecureSkipVerify: true}, //nolint:gosec // device certs are usually self-signed
	DisableCompression:  false,
	MaxIdleConns:        50,
	MaxIdleConnsPerHost: 8,
	IdleConnTimeout:     90 * time.Second,
}

// Handle executes the HTTP request and returns a Result.
func Handle(ctx context.Context, raw json.RawMessage) (any, error) {
	var a Args
	if err := json.Unmarshal(raw, &a); err != nil {
		return nil, fmt.Errorf("bad args: %w", err)
	}
	if a.DeviceIP == "" {
		return Result{Error: "device_ip required"}, nil
	}
	if a.Method == "" {
		a.Method = "GET"
	}
	if a.Scheme == "" {
		if a.Port == 443 || a.Port == 8443 || a.Port == 4443 {
			a.Scheme = "https"
		} else {
			a.Scheme = "http"
		}
	}
	if a.Port == 0 {
		if a.Scheme == "https" {
			a.Port = 443
		} else {
			a.Port = 80
		}
	}

	urlStr := fmt.Sprintf("%s://%s:%d%s", a.Scheme, a.DeviceIP, a.Port, a.Path)

	var bodyReader io.Reader
	if a.RequestBody != "" {
		switch strings.ToLower(a.BodyEncoding) {
		case "base64":
			b, err := base64.StdEncoding.DecodeString(a.RequestBody)
			if err != nil {
				return Result{Error: "bad base64 body"}, nil
			}
			bodyReader = bytes.NewReader(b)
		default:
			bodyReader = strings.NewReader(a.RequestBody)
		}
	}

	req, err := http.NewRequestWithContext(ctx, a.Method, urlStr, bodyReader)
	if err != nil {
		return Result{Error: err.Error()}, nil
	}
	for k, v := range a.RequestHeaders {
		// strip hop-by-hop headers
		switch strings.ToLower(k) {
		case "host", "connection", "transfer-encoding", "upgrade", "proxy-connection":
			continue
		}
		req.Header.Set(k, v)
	}
	jar := getJar(a.SessionID)
	for name, val := range a.SessionCookies {
		req.AddCookie(&http.Cookie{Name: name, Value: val})
	}

	cli := &http.Client{
		Transport: sharedTransport,
		Jar:       jar,
		Timeout:   25 * time.Second,
		// Don't auto-follow redirects: forward 30x to the browser so it can
		// keep state in its own URL bar (the catch-all proxy rewrites).
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}

	t0 := time.Now()
	resp, err := cli.Do(req)
	if err != nil {
		return Result{Error: err.Error(), DurationMs: time.Since(t0).Milliseconds()}, nil
	}
	defer resp.Body.Close()

	// Read at most 16 MB
	const maxBody = 16 * 1024 * 1024
	body, _ := io.ReadAll(io.LimitReader(resp.Body, maxBody))

	contentType := resp.Header.Get("Content-Type")
	encoding := "base64"
	bodyOut := base64.StdEncoding.EncodeToString(body)
	// Heuristic: text/* and application/json kept as text for ease of debug
	if strings.HasPrefix(contentType, "text/") ||
		strings.Contains(contentType, "json") ||
		strings.Contains(contentType, "xml") ||
		strings.Contains(contentType, "javascript") {
		encoding = "text"
		bodyOut = string(body)
	}

	headers := map[string][]string{}
	for k, v := range resp.Header {
		headers[k] = v
	}

	cookies := map[string]string{}
	for _, c := range resp.Cookies() {
		cookies[c.Name] = c.Value
	}

	return Result{
		StatusCode:      resp.StatusCode,
		ContentType:     contentType,
		Body:            bodyOut,
		BodyEncoding:    encoding,
		ResponseHeaders: headers,
		Cookies:         cookies,
		DurationMs:      time.Since(t0).Milliseconds(),
	}, nil
}
