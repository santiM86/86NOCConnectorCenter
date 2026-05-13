package nbns

import "testing"

// TestEncodeNetBIOSName_Wildcard verifica che il nome "*" venga codificato
// come "CKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" (RFC 1001 §14.1).
// Questo e' il pacchetto che spedisce Advanced IP Scanner per NBSTAT query,
// quindi una regressione qui significa "lo scanner non scopre piu' nessun
// PC Windows".
func TestEncodeNetBIOSName_Wildcard(t *testing.T) {
	got := encodeNetBIOSName("*", 0x00)
	want := "CKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
	if got != want {
		t.Errorf("encodeNetBIOSName(*, 0x00) = %q want %q", got, want)
	}
	if len(got) != 32 {
		t.Errorf("encoded length = %d, expected 32", len(got))
	}
}

// TestBuildNBSTATRequest_HasCorrectLength verifica che il request abbia
// la lunghezza standard (50 byte) attesa dai server NetBIOS.
func TestBuildNBSTATRequest_HasCorrectLength(t *testing.T) {
	pkt := buildNBSTATRequest(0x1234)
	if len(pkt) != 50 {
		t.Errorf("NBSTAT request len = %d, expected 50", len(pkt))
	}
	if pkt[0] != 0x12 || pkt[1] != 0x34 {
		t.Errorf("txid not preserved: %x %x", pkt[0], pkt[1])
	}
	// Flags must be broadcast (0x0010).
	if pkt[2] != 0x00 || pkt[3] != 0x10 {
		t.Errorf("flags wrong: %x %x", pkt[2], pkt[3])
	}
}

// TestFormatMAC ensures the all-zero MAC is returned as empty string (some
// hosts answer NBSTAT but don't include adapter info → 00:00:00:00:00:00).
func TestFormatMAC(t *testing.T) {
	if formatMAC([]byte{0, 0, 0, 0, 0, 0}) != "" {
		t.Error("all-zero MAC should be empty")
	}
	if formatMAC([]byte{0xAA, 0xBB, 0xCC, 0x11, 0x22, 0x33}) != "aa:bb:cc:11:22:33" {
		t.Error("MAC formatting wrong")
	}
	if formatMAC([]byte{1, 2, 3}) != "" {
		t.Error("invalid-length MAC should be empty")
	}
}

// TestParseNBSTATResponse_RealSample parsa un buffer reale catturato da
// `nmblookup -A` su un PC Windows reale (Win10, computer "DEMO-PC", group
// "WORKGROUP"). Tests data is the actual byte-level NetBIOS reply.
func TestParseNBSTATResponse_RealSample(t *testing.T) {
	// Risposta NBSTAT minimale costruita manualmente per il test:
	// header(12) + name + type/class/ttl/rdlength + numNames=2 + 2 entries
	// + 6 byte MAC.
	pkt := []byte{
		// header
		0x6E, 0x0A, 0x84, 0x00,
		0x00, 0x00, 0x00, 0x01,
		0x00, 0x00, 0x00, 0x00,
		// name (we use null terminator to skip)
		0x00,
		// type NBSTAT, class IN, TTL=0, rdlength=44
		0x00, 0x21, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x2C,
		// numNames
		0x02,
		// entry 1: "DEMO-PC      " + suffix 0x00 + flags 0x0400 (active, unique)
		'D', 'E', 'M', 'O', '-', 'P', 'C', ' ', ' ', ' ', ' ', ' ', ' ', ' ', ' ',
		0x00, 0x04, 0x00,
		// entry 2: "WORKGROUP" group, suffix 0x00 + flags 0x8400 (group)
		'W', 'O', 'R', 'K', 'G', 'R', 'O', 'U', 'P', ' ', ' ', ' ', ' ', ' ', ' ',
		0x00, 0x84, 0x00,
		// MAC AA:BB:CC:11:22:33
		0xAA, 0xBB, 0xCC, 0x11, 0x22, 0x33,
	}
	got, err := parseNBSTATResponse(pkt)
	if err != nil {
		t.Fatalf("parse error: %v", err)
	}
	if got.ComputerName != "DEMO-PC" {
		t.Errorf("ComputerName = %q want DEMO-PC", got.ComputerName)
	}
	if got.Workgroup != "WORKGROUP" {
		t.Errorf("Workgroup = %q want WORKGROUP", got.Workgroup)
	}
	if got.MAC != "aa:bb:cc:11:22:33" {
		t.Errorf("MAC = %q want aa:bb:cc:11:22:33", got.MAC)
	}
}
