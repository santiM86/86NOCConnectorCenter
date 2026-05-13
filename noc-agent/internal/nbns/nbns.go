// Package nbns implementa il NetBIOS Name Service (RFC 1002) lato client,
// limitato alla query NBSTAT (node status request) che ritorna la lista di
// nomi NetBIOS registrati su un host UDP/137.
//
// Lo usiamo per due scopi distinti, condividendo la stessa implementazione:
//
//  1. Scanner UI (cmd/nocui/scanner_windows.go) — Advanced IP Scanner-style:
//     per ogni IP della /24 chiediamo NBSTAT in parallelo e otteniamo
//     hostname Windows reale senza dover fare reverse DNS.
//
//  2. Agent discovery (internal/discovery/) — risolve hostname PC Windows
//     quando il DNS aziendale non ha record PTR. Necessario per popolare
//     correttamente il campo `name` di managed_devices.
//
// Caratteristiche chiave:
//   - Zero dipendenze native (raw socket NON serve, UDP 137 + parsing puro).
//   - Timeout configurabile (default 200ms) — su LAN la risposta arriva in
//     5-50ms, quindi 200ms basta e avanza per non rallentare lo sweep.
//   - Parsing strict ma resiliente: pacchetti malformati ritornano errore,
//     mai panic.
//   - Estrae: ComputerName (unique 0x00), Workgroup (group 0x00),
//     LoggedUser (unique 0x03), MAC (NodeStatistics).
package nbns

import (
	"bytes"
	"encoding/binary"
	"errors"
	"fmt"
	"net"
	"strings"
	"time"
)

// NodeInfo aggrega le info estratte da una risposta NBSTAT.
type NodeInfo struct {
	ComputerName string // unique 0x00 - es. "PC-MARCO"
	Workgroup    string // group 0x00   - es. "WORKGROUP" o "AZIENDA.LOCAL"
	LoggedUser   string // unique 0x03 - es. "MARIO.ROSSI"
	MAC          string // dalle ultime 6 byte del MAC address field
	RawNames     []NameEntry
}

// NameEntry e' una singola voce del Node Name Array NBSTAT.
type NameEntry struct {
	Name    string // 15 chars trimmati
	Suffix  byte   // tipo NetBIOS (0x00=Workstation/Workgroup, 0x03=Messenger, 0x20=Server)
	IsGroup bool   // bit "group" del flags field
}

// DefaultTimeout e' il timeout consigliato per scan paralleli su LAN.
const DefaultTimeout = 200 * time.Millisecond

// Query invia un NBSTAT a target:137 e parsa la risposta.
// `timeout` zero -> usa DefaultTimeout.
func Query(target string, timeout time.Duration) (*NodeInfo, error) {
	if timeout <= 0 {
		timeout = DefaultTimeout
	}
	addr := net.JoinHostPort(target, "137")
	conn, err := net.DialTimeout("udp", addr, timeout)
	if err != nil {
		return nil, fmt.Errorf("dial udp/137: %w", err)
	}
	defer conn.Close()

	// Costruisci NBSTAT request:
	//   Transaction ID: random16 (qui usiamo 0x6E0A, scelto stabile per debug)
	//   Flags: 0x0010 (Broadcast=1)
	//   QDcount: 1, ANcount: 0, NScount: 0, ARcount: 0
	//   Question: encoded name "*" + 15 padding bytes (CKAA..AA) + suffix 0x00,
	//             type NBSTAT (0x0021), class IN (0x0001).
	pkt := buildNBSTATRequest(0x6E0A)
	if err := conn.SetWriteDeadline(time.Now().Add(timeout)); err != nil {
		return nil, err
	}
	if _, err := conn.Write(pkt); err != nil {
		return nil, fmt.Errorf("write: %w", err)
	}
	if err := conn.SetReadDeadline(time.Now().Add(timeout)); err != nil {
		return nil, err
	}
	buf := make([]byte, 1024)
	n, err := conn.Read(buf)
	if err != nil {
		return nil, fmt.Errorf("read: %w", err)
	}
	return parseNBSTATResponse(buf[:n])
}

// buildNBSTATRequest serializza il pacchetto di richiesta. La struttura e'
// fissa (vedi RFC 1002 §4.2.17) eccetto il transaction id, da random.
func buildNBSTATRequest(txid uint16) []byte {
	buf := new(bytes.Buffer)
	_ = binary.Write(buf, binary.BigEndian, txid)
	_ = binary.Write(buf, binary.BigEndian, uint16(0x0010)) // flags: broadcast
	_ = binary.Write(buf, binary.BigEndian, uint16(1))     // qdcount
	_ = binary.Write(buf, binary.BigEndian, uint16(0))
	_ = binary.Write(buf, binary.BigEndian, uint16(0))
	_ = binary.Write(buf, binary.BigEndian, uint16(0))
	// Encoded "*\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0" -> 32 byte L2-encoding
	encoded := encodeNetBIOSName("*", 0x00)
	buf.WriteByte(byte(len(encoded)))
	buf.WriteString(encoded)
	buf.WriteByte(0x00) // null terminator
	_ = binary.Write(buf, binary.BigEndian, uint16(0x0021)) // NBSTAT
	_ = binary.Write(buf, binary.BigEndian, uint16(0x0001)) // IN
	return buf.Bytes()
}

// encodeNetBIOSName applica l'encoding "first-level" RFC 1001 §14.1: ogni
// byte del nome (15 char + suffix, padded a 16) viene split in due nibble e
// sommati a 'A'. Per il wildcard "*" il padding e' 0x00 (RFC 1002 §4.2.18),
// per nomi utente normali il padding e' lo spazio 0x20. Il nostro caso
// d'uso e' SEMPRE NBSTAT con wildcard "*", quindi padding-zero e' corretto.
func encodeNetBIOSName(name string, suffix byte) string {
	padded := make([]byte, 16)
	copy(padded, []byte(name))
	// padded e' gia' zero-inizializzato da make: i byte da len(name) a 14
	// restano 0x00, che e' esattamente cio' che vogliamo per il wildcard "*".
	padded[15] = suffix
	encoded := make([]byte, 32)
	for i, b := range padded {
		encoded[i*2] = 'A' + (b >> 4)
		encoded[i*2+1] = 'A' + (b & 0x0F)
	}
	return string(encoded)
}

// parseNBSTATResponse decodifica una risposta NBSTAT estraendo nomi e MAC.
func parseNBSTATResponse(raw []byte) (*NodeInfo, error) {
	if len(raw) < 12 {
		return nil, errors.New("response too short for NBNS header")
	}
	// Header NBNS (12 byte): txid(2) flags(2) qd(2) an(2) ns(2) ar(2)
	anCount := binary.BigEndian.Uint16(raw[6:8])
	if anCount == 0 {
		return nil, errors.New("no answer records")
	}
	// Salta il nome della risposta (compressed o full L1 encoding).
	off := 12
	// Skip name field: byte di lunghezza + bytes seguenti, terminator 0x00.
	// Implementazione robusta: salta finche' non trova 0x00.
	for off < len(raw) && raw[off] != 0x00 {
		l := int(raw[off])
		if l&0xC0 == 0xC0 { // pointer compression
			off += 2
			break
		}
		off += 1 + l
	}
	if off < len(raw) && raw[off] == 0x00 {
		off++
	}
	if off+10 > len(raw) {
		return nil, errors.New("truncated answer header")
	}
	// type(2) class(2) ttl(4) rdlength(2)
	off += 10
	if off >= len(raw) {
		return nil, errors.New("no answer payload")
	}
	numNames := int(raw[off])
	off++
	if off+numNames*18 > len(raw) {
		return nil, errors.New("truncated node name array")
	}
	out := &NodeInfo{}
	for i := 0; i < numNames; i++ {
		nm := strings.TrimRight(string(raw[off:off+15]), " \x00")
		suffix := raw[off+15]
		flags := binary.BigEndian.Uint16(raw[off+16 : off+18])
		isGroup := flags&0x8000 != 0
		entry := NameEntry{Name: nm, Suffix: suffix, IsGroup: isGroup}
		out.RawNames = append(out.RawNames, entry)
		switch {
		case suffix == 0x00 && !isGroup && out.ComputerName == "":
			out.ComputerName = nm
		case suffix == 0x00 && isGroup && out.Workgroup == "":
			out.Workgroup = nm
		case suffix == 0x03 && !isGroup && out.LoggedUser == "":
			out.LoggedUser = nm
		}
		off += 18
	}
	// MAC address: 6 byte alla fine del payload Node Statistics (46 byte tot,
	// ma a noi servono solo i primi 6).
	if off+6 <= len(raw) {
		out.MAC = formatMAC(raw[off : off+6])
	}
	return out, nil
}

// formatMAC ritorna "aa:bb:cc:dd:ee:ff" lowercase con separatore ':'.
func formatMAC(b []byte) string {
	if len(b) != 6 {
		return ""
	}
	// All-zero MAC = host non ha riportato MAC nei NodeStatistics; meglio
	// ritornare stringa vuota cosi' chi consuma il valore non lo confonde
	// con un MAC reale.
	allZero := true
	for _, c := range b {
		if c != 0 {
			allZero = false
			break
		}
	}
	if allZero {
		return ""
	}
	return fmt.Sprintf("%02x:%02x:%02x:%02x:%02x:%02x", b[0], b[1], b[2], b[3], b[4], b[5])
}
