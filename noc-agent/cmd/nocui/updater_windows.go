//go:build windows

package main

// updater_windows.go
//
// Auto-update controller per la tray UI nocagent-ui.exe:
//  1. ogni 1h interroga GitHub Releases per il repo configurato
//  2. compara il tag_name della latest release con la versione corrente
//  3. se trova una versione piu' recente:
//       - aggiorna tooltip tray ("aggiornamento v4.5.0 disponibile")
//       - mostra un balloon notification (una volta sola per release)
//       - registra il tag in `app` cosi' il menu "Aggiorna ora" sappia cosa scaricare
//
// L'update concreto NON viene fatto da qui (la UI gira come user, non come
// SYSTEM, quindi non puo' sovrascrivere C:\Program Files\86NocAgent\*.exe).
// "Aggiorna ora" delega allo script install-noc-agent.ps1 con UAC prompt.

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"sync"
	"time"
)

const (
	updateCheckInterval = 1 * time.Hour
	updateCheckTimeout  = 15 * time.Second
	defaultUpdateRepo   = "santiM86/86NOCConnectorCenter"
)

type latestReleaseInfo struct {
	mu          sync.RWMutex
	available   bool   // true se latestTag > currentVersion
	currentVer  string // versione attualmente installata (es. "4.4.0")
	latestTag   string // tag GitHub Release (es. "v4.5.0")
	latestVer   string // tag stripato del prefisso v (es. "4.5.0")
	publishedAt string // ISO date
	notified    string // tag per cui abbiamo gia' mostrato il balloon (evita spam)
}

// Snapshot ritorna una copia thread-safe dello stato corrente, comoda per le
// chiamate dall'UI thread.
func (l *latestReleaseInfo) Snapshot() latestReleaseInfo {
	l.mu.RLock()
	defer l.mu.RUnlock()
	return latestReleaseInfo{
		available:   l.available,
		currentVer:  l.currentVer,
		latestTag:   l.latestTag,
		latestVer:   l.latestVer,
		publishedAt: l.publishedAt,
		notified:    l.notified,
	}
}

type githubReleaseAPI struct {
	TagName     string `json:"tag_name"`
	Name        string `json:"name"`
	PublishedAt string `json:"published_at"`
	Draft       bool   `json:"draft"`
	Prerelease  bool   `json:"prerelease"`
	HTMLURL     string `json:"html_url"`
}

// startUpdateWatcher lancia una goroutine che periodicamente controlla la
// latest release. Notifica via balloon all'utente quando trova una versione
// nuova rispetto a app.agent.Version.
func startUpdateWatcher(app *App) {
	if app == nil {
		return
	}
	if app.update == nil {
		app.update = &latestReleaseInfo{currentVer: app.agent.Version}
	}

	// Primo check immediato (delay 10s per non rallentare lo startup).
	go func() {
		time.Sleep(10 * time.Second)
		runUpdateCheck(app)
		ticker := time.NewTicker(updateCheckInterval)
		defer ticker.Stop()
		for range ticker.C {
			runUpdateCheck(app)
		}
	}()
}

// runUpdateCheck esegue una singola query a GitHub API e aggiorna lo stato.
// Se trova una versione nuova non ancora notificata, fa scattare il balloon.
func runUpdateCheck(app *App) {
	repo := defaultUpdateRepo
	url := fmt.Sprintf("https://api.github.com/repos/%s/releases/latest", repo)

	client := &http.Client{Timeout: updateCheckTimeout}
	req, err := http.NewRequest(http.MethodGet, url, nil)
	if err != nil {
		logf("updater: NewRequest: %v", err)
		return
	}
	req.Header.Set("User-Agent", "86NocAgent-UI/auto-updater")
	req.Header.Set("Accept", "application/vnd.github.v3+json")
	resp, err := client.Do(req)
	if err != nil {
		logf("updater: GET releases/latest failed: %v", err)
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		logf("updater: GitHub API returned HTTP %d", resp.StatusCode)
		return
	}
	var rel githubReleaseAPI
	if err := json.NewDecoder(resp.Body).Decode(&rel); err != nil {
		logf("updater: decode: %v", err)
		return
	}
	if rel.Draft || rel.Prerelease || rel.TagName == "" {
		return // skippiamo draft / prerelease
	}

	latestVer := strings.TrimPrefix(rel.TagName, "v")
	currentVer := strings.TrimPrefix(app.agent.Version, "v")
	newer := isNewerVersion(latestVer, currentVer)

	app.update.mu.Lock()
	app.update.currentVer = currentVer
	app.update.latestTag = rel.TagName
	app.update.latestVer = latestVer
	app.update.publishedAt = rel.PublishedAt
	app.update.available = newer
	alreadyNotified := app.update.notified == rel.TagName
	app.update.mu.Unlock()

	logf("updater: current=%s latest=%s newer=%v notified=%v",
		currentVer, latestVer, newer, alreadyNotified)

	if newer && !alreadyNotified {
		showUpdateBalloon(app, latestVer)
		app.update.mu.Lock()
		app.update.notified = rel.TagName
		app.update.mu.Unlock()
	}
}

// isNewerVersion confronta due semver-like (es. "4.4.0" vs "4.5.0").
// Si limita a un confronto numerico per componenti, senza pretese di
// supportare metadati pre-release tipo "1.2.3-rc.1". Per la nostra
// convenzione di tag GitHub e' piu' che sufficiente.
func isNewerVersion(latest, current string) bool {
	if current == "" || current == "?" {
		// Se non conosciamo la versione installata consideriamo qualsiasi
		// release "piu' nuova" cosi' l'utente vede comunque l'avviso.
		return latest != ""
	}
	a := splitVersion(latest)
	b := splitVersion(current)
	for i := 0; i < 3; i++ {
		var av, bv int
		if i < len(a) {
			av = a[i]
		}
		if i < len(b) {
			bv = b[i]
		}
		if av > bv {
			return true
		}
		if av < bv {
			return false
		}
	}
	return false
}

func splitVersion(s string) []int {
	parts := strings.Split(s, ".")
	out := make([]int, 0, 3)
	for _, p := range parts {
		n := 0
		for _, c := range p {
			if c < '0' || c > '9' {
				break
			}
			n = n*10 + int(c-'0')
		}
		out = append(out, n)
	}
	return out
}

// showUpdateBalloon mostra una notifica balloon nella system tray. Deve
// essere invocata sul main thread (mw.Synchronize).
func showUpdateBalloon(app *App, latestVer string) {
	if app == nil {
		return
	}
	title := fmt.Sprintf("Aggiornamento disponibile: v%s", latestVer)
	msg := fmt.Sprintf("E' uscita una nuova versione del NOC Agent. Apri il menu della tray e clicca \"Aggiorna ora\" per installarla.")
	tryShow := func() {
		if app.tray == nil {
			return
		}
		// walk.NotifyIcon.ShowInfo richiede il main UI thread.
		_ = app.tray.ShowInfo(title, msg)
		// Aggiorna anche il tooltip cosi' resta visibile fino al prossimo refresh.
		_ = app.tray.SetToolTip(fmt.Sprintf("86bit NOC Agent v%s - aggiornamento v%s disponibile",
			app.agent.Version, latestVer))
	}
	if app.mw != nil {
		app.mw.Synchronize(tryShow)
		return
	}
	if app.hiddenMw != nil {
		app.hiddenMw.Synchronize(tryShow)
	}
}
