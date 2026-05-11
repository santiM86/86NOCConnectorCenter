// Tests for parseARPLine across Linux/BSD/macOS/Windows output formats.
// Validates the Windows `arp -a` format that previously was unsupported.
package discovery

import "testing"

func TestParseARPLine_Windows(t *testing.T) {
	cases := []struct {
		name        string
		line        string
		wantIP, wantMAC string
	}{
		{
			name:    "windows dynamic entry",
			line:    "  10.10.1.220           00-11-22-33-44-55     dynamic",
			wantIP:  "10.10.1.220",
			wantMAC: "00:11:22:33:44:55",
		},
		{
			name:    "windows static entry",
			line:    "  192.168.0.1          aa-bb-cc-dd-ee-ff     static",
			wantIP:  "192.168.0.1",
			wantMAC: "aa:bb:cc:dd:ee:ff",
		},
		{
			name:    "windows mac uppercase",
			line:    "  10.0.0.42           AA-BB-CC-DD-EE-FF     dynamic",
			wantIP:  "10.0.0.42",
			wantMAC: "aa:bb:cc:dd:ee:ff",
		},
		{
			name:    "bsd with parentheses",
			line:    "? (192.168.1.1) at aa:bb:cc:dd:ee:ff on en0 ifscope [ethernet]",
			wantIP:  "192.168.1.1",
			wantMAC: "aa:bb:cc:dd:ee:ff",
		},
		{
			name: "windows interface header skipped",
			line: "Interface: 10.10.1.5 --- 0x4",
			// header non ha MAC, e parts[0]="Interface:" non e' un IP valido.
			// In scanCmd la riga viene scartata perche' mac=="".
			wantIP: "", wantMAC: "",
		},
		{
			name: "windows column header skipped",
			line: "  Internet Address      Physical Address      Type",
			// nessun IP né MAC validi
			wantIP: "", wantMAC: "",
		},
		{
			name: "empty line",
			line: "",
			wantIP: "", wantMAC: "",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			gotIP, gotMAC := parseARPLine(tc.line)
			if gotIP != tc.wantIP {
				t.Errorf("IP: got %q, want %q", gotIP, tc.wantIP)
			}
			if gotMAC != tc.wantMAC {
				t.Errorf("MAC: got %q, want %q", gotMAC, tc.wantMAC)
			}
		})
	}
}

func TestIsMACLike(t *testing.T) {
	good := []string{
		"aa:bb:cc:dd:ee:ff",
		"00-11-22-33-44-55",
		"AA-BB-CC-DD-EE-FF",
	}
	for _, m := range good {
		if !isMACLike(m) {
			t.Errorf("expected %q to be MAC-like", m)
		}
	}
	bad := []string{
		"",
		"not-a-mac-address",
		"aa:bb:cc:dd:ee",       // troppo corto
		"aa:bb:cc:dd:ee:ff:00", // troppo lungo
		"zz:bb:cc:dd:ee:ff",    // chars non hex
	}
	for _, m := range bad {
		if isMACLike(m) {
			t.Errorf("expected %q NOT to be MAC-like", m)
		}
	}
}
