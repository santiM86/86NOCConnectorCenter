//go:build !windows

// Stub Linux/macOS: Hyper-V e' solo Windows. Definiamo i tipi e funzioni
// vuoti per permettere la build cross-platform del binario.
package main

import (
	"context"
	"fmt"
)

type hyperVArgs struct {
	CommandID string `json:"command_id"`
	ClientID  string `json:"client_id"`
}

type hyperVSnapshot struct {
	CommandID     string                   `json:"command_id"`
	ClientID      string                   `json:"client_id"`
	AgentID       string                   `json:"agent_id"`
	Hostname      string                   `json:"hostname"`
	HyperVPresent bool                     `json:"hyperv_present"`
	VMs           []map[string]interface{} `json:"vms"`
	Error         string                   `json:"error,omitempty"`
}

func collectHyperV(_ context.Context, cmdID, clientID, agentID, hostname string) hyperVSnapshot {
	return hyperVSnapshot{
		CommandID: cmdID, ClientID: clientID, AgentID: agentID, Hostname: hostname,
		HyperVPresent: false, Error: "Hyper-V richiede Windows Server",
	}
}

func sendHyperVSnapshot(_ context.Context, _, _, _ string, _ hyperVSnapshot) error {
	return fmt.Errorf("hyperv non disponibile su questo OS")
}
