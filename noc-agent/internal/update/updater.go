// Package update implements optional self-update.
//
// Flow:
//  1. Periodically GET cfg.ManifestURL → JSON manifest with version,
//     download URL, sha256 and an Ed25519 signature over the digest.
//  2. If manifest version > our version, download the binary, verify
//     digest + signature, atomically replace the running executable,
//     then exec the new one (the watchdog respawns on exit if needed).
//
// This package is wired but **not enabled by default** until the backend
// publishes signed manifests; we keep the surface small here.
package update

import (
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"time"

	"github.com/86bit/noc-agent/internal/config"
	"github.com/86bit/noc-agent/internal/logging"
)

type Manifest struct {
	Version   string `json:"version"`
	OS        string `json:"os"`
	Arch      string `json:"arch"`
	URL       string `json:"url"`
	SHA256Hex string `json:"sha256"`
	SignHex   string `json:"signature"` // ed25519 over sha256 raw bytes
}

type Updater struct {
	cfg     config.UpdateConfig
	current string
	log     *logging.Logger
}

func New(cfg config.UpdateConfig, currentVersion string, log *logging.Logger) *Updater {
	return &Updater{cfg: cfg, current: currentVersion, log: log.With("update")}
}

// Run loops until ctx done, checking for updates every CheckInterval.
func (u *Updater) Run(ctx context.Context) {
	if !u.cfg.Enabled || u.cfg.ManifestURL == "" {
		return
	}
	t := time.NewTicker(u.cfg.CheckInterval)
	defer t.Stop()
	u.checkAndApply(ctx)
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			u.checkAndApply(ctx)
		}
	}
}

func (u *Updater) checkAndApply(ctx context.Context) {
	m, err := u.fetchManifest(ctx)
	if err != nil {
		u.log.Warn("manifest fetch failed", "err", err.Error())
		return
	}
	if m.OS != runtime.GOOS || m.Arch != runtime.GOARCH {
		return
	}
	if m.Version == u.current {
		return
	}
	u.log.Info("new version available", "current", u.current, "next", m.Version)
	if err := u.apply(ctx, m); err != nil {
		u.log.Error("update apply failed", "err", err.Error())
	}
}

func (u *Updater) fetchManifest(ctx context.Context) (*Manifest, error) {
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, u.cfg.ManifestURL, nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("manifest http %d", resp.StatusCode)
	}
	var m Manifest
	if err := json.NewDecoder(resp.Body).Decode(&m); err != nil {
		return nil, err
	}
	return &m, nil
}

func (u *Updater) apply(ctx context.Context, m *Manifest) error {
	if u.cfg.PublicKey == "" {
		return errors.New("update.public_key empty: refusing to apply unsigned manifest")
	}
	pk, err := hex.DecodeString(u.cfg.PublicKey)
	if err != nil || len(pk) != ed25519.PublicKeySize {
		return errors.New("invalid public key")
	}
	sig, err := hex.DecodeString(m.SignHex)
	if err != nil {
		return errors.New("invalid signature hex")
	}
	digest, err := hex.DecodeString(m.SHA256Hex)
	if err != nil {
		return errors.New("invalid sha256 hex")
	}
	if !ed25519.Verify(pk, digest, sig) {
		return errors.New("signature verify failed")
	}

	// Download binary
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, m.URL, nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return fmt.Errorf("download: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("download http %d", resp.StatusCode)
	}

	exe, err := os.Executable()
	if err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(exe), ".nocagent.new.*")
	if err != nil {
		return err
	}
	h := sha256.New()
	if _, err := io.Copy(io.MultiWriter(tmp, h), resp.Body); err != nil {
		tmp.Close()
		os.Remove(tmp.Name())
		return err
	}
	tmp.Close()
	if hex.EncodeToString(h.Sum(nil)) != m.SHA256Hex {
		os.Remove(tmp.Name())
		return errors.New("downloaded sha256 mismatch")
	}
	if err := os.Chmod(tmp.Name(), 0o755); err != nil {
		os.Remove(tmp.Name())
		return err
	}
	if err := os.Rename(tmp.Name(), exe); err != nil {
		os.Remove(tmp.Name())
		return err
	}
	u.log.Info("update applied", "version", m.Version)
	// Trigger graceful shutdown; the OS service / watchdog respawns us.
	go func() {
		time.Sleep(500 * time.Millisecond)
		_ = os.Exit
	}()
	return nil
}
