//go:build windows

// snmp_test_windows.go — comando WS "snmp_test" che esegue un quick
// snmpget di sysDescr (1.3.6.1.2.1.1.1.0) + sysUpTime (1.3.6.1.2.1.1.3.0)
// e ritorna il risultato al Center entro 8s.
//
// Permette al pulsante "Test SNMP" nella UI Center di validare le
// credenziali e la raggiungibilita' del device senza dover aspettare
// il prossimo ciclo di polling.
//
// Usa la stessa libreria SNMP del poller (gosnmp) per essere coerente
// con la configurazione di timeout/retry/protocolli SNMPv3.

package main

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/86bit/noc-agent/internal/logging"
	"github.com/86bit/noc-agent/internal/transport"
	g "github.com/gosnmp/gosnmp"
)

type snmpTestArgs struct {
	IP                  string `json:"ip"`
	Community           string `json:"community"`
	SNMPVersion         string `json:"snmp_version"`
	SNMPv3Username      string `json:"snmpv3_username"`
	SNMPv3AuthProtocol  string `json:"snmpv3_auth_protocol"`
	SNMPv3AuthPassword  string `json:"snmpv3_auth_password"`
	SNMPv3PrivProtocol  string `json:"snmpv3_priv_protocol"`
	SNMPv3PrivPassword  string `json:"snmpv3_priv_password"`
	SNMPv3SecurityLevel string `json:"snmpv3_security_level"`
}

const (
	oidSysDescr   = "1.3.6.1.2.1.1.1.0"
	oidSysUpTime  = "1.3.6.1.2.1.1.3.0"
	oidSysName    = "1.3.6.1.2.1.1.5.0"
	oidSysContact = "1.3.6.1.2.1.1.4.0"
)

func registerSNMPTestCommand(client *transport.Client, log *logging.Logger) {
	client.Register("snmp_test", func(_ context.Context, args json.RawMessage) (any, error) {
		var req snmpTestArgs
		if err := json.Unmarshal(args, &req); err != nil {
			return nil, fmt.Errorf("snmp_test payload invalido: %w", err)
		}
		if req.IP == "" {
			return nil, fmt.Errorf("snmp_test: ip mancante")
		}
		log.Info("snmp_test request", "ip", req.IP, "version", req.SNMPVersion)

		start := time.Now()
		params := &g.GoSNMP{
			Target:    req.IP,
			Port:      161,
			Timeout:   time.Duration(3) * time.Second,
			Retries:   1,
			MaxOids:   g.MaxOids,
		}
		// Versione + community/credentials
		switch strings.ToLower(req.SNMPVersion) {
		case "v1":
			params.Version = g.Version1
			params.Community = orDefault(req.Community, "public")
		case "v3":
			params.Version = g.Version3
			params.SecurityModel = g.UserSecurityModel
			usm := &g.UsmSecurityParameters{
				UserName:                 req.SNMPv3Username,
				AuthenticationProtocol:   parseAuthProto(req.SNMPv3AuthProtocol),
				AuthenticationPassphrase: req.SNMPv3AuthPassword,
				PrivacyProtocol:          parsePrivProto(req.SNMPv3PrivProtocol),
				PrivacyPassphrase:        req.SNMPv3PrivPassword,
			}
			params.SecurityParameters = usm
			switch req.SNMPv3SecurityLevel {
			case "noAuthNoPriv":
				params.MsgFlags = g.NoAuthNoPriv
			case "authNoPriv":
				params.MsgFlags = g.AuthNoPriv
			default:
				params.MsgFlags = g.AuthPriv
			}
		default: // v2c
			params.Version = g.Version2c
			params.Community = orDefault(req.Community, "public")
		}

		if err := params.Connect(); err != nil {
			return map[string]any{
				"reachable": false,
				"error":     fmt.Sprintf("connect failed: %v", err),
				"elapsed_ms": time.Since(start).Milliseconds(),
			}, nil
		}
		defer params.Conn.Close()

		oids := []string{oidSysDescr, oidSysUpTime, oidSysName, oidSysContact}
		res, err := params.Get(oids)
		if err != nil {
			return map[string]any{
				"reachable":  false,
				"error":      fmt.Sprintf("snmpget failed: %v", err),
				"elapsed_ms": time.Since(start).Milliseconds(),
			}, nil
		}

		out := map[string]any{
			"reachable":  true,
			"elapsed_ms": time.Since(start).Milliseconds(),
			"version":    req.SNMPVersion,
		}
		for _, v := range res.Variables {
			switch v.Name {
			case "." + oidSysDescr:
				out["sys_descr"] = asString(v.Value)
			case "." + oidSysUpTime:
				out["sys_uptime_ticks"] = v.Value
				if t, ok := v.Value.(uint32); ok {
					out["sys_uptime_human"] = formatUptime(int64(t))
				}
			case "." + oidSysName:
				out["sys_name"] = asString(v.Value)
			case "." + oidSysContact:
				out["sys_contact"] = asString(v.Value)
			}
		}
		return out, nil
	})
}

func orDefault(s, d string) string {
	if s == "" {
		return d
	}
	return s
}

func parseAuthProto(s string) g.SnmpV3AuthProtocol {
	switch strings.ToUpper(s) {
	case "MD5":
		return g.MD5
	case "SHA":
		return g.SHA
	case "SHA224":
		return g.SHA224
	case "SHA256":
		return g.SHA256
	case "SHA384":
		return g.SHA384
	case "SHA512":
		return g.SHA512
	default:
		return g.NoAuth
	}
}

func parsePrivProto(s string) g.SnmpV3PrivProtocol {
	switch strings.ToUpper(s) {
	case "DES":
		return g.DES
	case "AES", "AES128":
		return g.AES
	case "AES192":
		return g.AES192
	case "AES256":
		return g.AES256
	default:
		return g.NoPriv
	}
}

func asString(v interface{}) string {
	switch x := v.(type) {
	case string:
		return x
	case []byte:
		return string(x)
	default:
		return fmt.Sprintf("%v", v)
	}
}

func formatUptime(ticks int64) string {
	// gosnmp ritorna sys_uptime in centesimi di secondo (TimeTicks)
	secs := ticks / 100
	d := secs / 86400
	h := (secs % 86400) / 3600
	m := (secs % 3600) / 60
	s := secs % 60
	if d > 0 {
		return fmt.Sprintf("%dd %dh %dm %ds", d, h, m, s)
	}
	if h > 0 {
		return fmt.Sprintf("%dh %dm %ds", h, m, s)
	}
	if m > 0 {
		return fmt.Sprintf("%dm %ds", m, s)
	}
	return fmt.Sprintf("%ds", s)
}
