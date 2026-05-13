package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestGetOrCreateStableAgentID_GeneratesAndPersists garantisce che la prima
// chiamata generi un UUID valido E lo scriva su disco, e che la seconda
// chiamata lo legga (idempotenza).
func TestGetOrCreateStableAgentID_GeneratesAndPersists(t *testing.T) {
	dir := t.TempDir()
	// Redirige il path di persistenza sul tmpdir.
	t.Setenv("ProgramData", dir)
	t.Setenv("HOME", dir)

	first := getOrCreateStableAgentID()
	if !isValidAgentID(first) {
		t.Fatalf("primo id non valido: %q", first)
	}

	second := getOrCreateStableAgentID()
	if second != first {
		t.Errorf("id non persistente: first=%q second=%q", first, second)
	}

	// Verifica che il file esista nel path atteso (Windows usa ProgramData,
	// gli altri /var/lib).
	path := defaultAgentIDFile()
	if _, err := os.Stat(path); err != nil {
		// Il path linux è /var/lib/... non temp; skip se non scrivibile.
		if strings.HasPrefix(path, "/var/") {
			t.Skipf("path linux non scrivibile in test: %s", path)
		}
		t.Errorf("file id non scritto: %v", err)
	}
}

// TestIsValidAgentID verifies the strict 32-hex check used to reject corrupted
// agent_id.txt content (truncated writes, wrong file, etc.).
func TestIsValidAgentID(t *testing.T) {
	cases := map[string]bool{
		"":                                  false,
		"abc":                               false,
		"ca27f434727a988b3870c33f9ea26d37":  true,
		"ca27f434727a988b3870c33f9ea26d3":   false, // 31 char
		"ca27f434727a988b3870c33f9ea26d377": false, // 33 char
		"CA27F434727A988B3870C33F9EA26D37":  false, // upper not allowed
		"ca27f434727a988b3870c33f9ea26d3g":  false, // 'g' non hex
	}
	for in, want := range cases {
		if got := isValidAgentID(in); got != want {
			t.Errorf("isValidAgentID(%q)=%v want %v", in, got, want)
		}
	}
}

// TestGetOrCreateStableAgentID_RejectsCorrupted ensures we regenerate when the
// persisted file contains an invalid id (e.g. half-written, manual edit).
func TestGetOrCreateStableAgentID_RejectsCorrupted(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("ProgramData", dir)
	t.Setenv("HOME", dir)

	path := defaultAgentIDFile()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("not-a-uuid"), 0o644); err != nil {
		t.Fatal(err)
	}

	id := getOrCreateStableAgentID()
	if !isValidAgentID(id) {
		t.Fatalf("regenerated id non valido: %q", id)
	}
	if id == "not-a-uuid" {
		t.Errorf("accettato id corrotto")
	}
}
