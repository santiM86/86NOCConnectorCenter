// Tests for the PTR enrichment helper.
package discovery

import "testing"

func TestSanitizePTR(t *testing.T) {
	cases := []struct {
		in, want string
	}{
		{"server1.bit86.local.", "server1.bit86.local"},
		{"  server1.bit86.local.  ", "server1.bit86.local"},
		{"server1.bit86.local", "server1.bit86.local"},
		// Reject synthetic in-addr.arpa replies.
		{"5.1.10.10.in-addr.arpa.", ""},
		{"5.1.10.10.IN-ADDR.ARPA.", ""},
		{"1.0.0.127.ip6.arpa.", ""},
		{"", ""},
		{".", ""},
		{"   ", ""},
	}
	for _, tc := range cases {
		got := sanitizePTR(tc.in)
		if got != tc.want {
			t.Errorf("sanitizePTR(%q) = %q, want %q", tc.in, got, tc.want)
		}
	}
}
