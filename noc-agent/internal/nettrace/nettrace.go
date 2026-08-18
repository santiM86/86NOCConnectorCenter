// Package nettrace esegue una diagnosi di percorso (traceroute/MTR) verso un
// target, delegando ai tool nativi del sistema operativo e normalizzando
// l'output in una struttura comune consumata dal Center.
//
// Progettato per l'agent-SONDA installato nella sede del NOC: da lì il percorso
// rispecchia quello reale del NOC verso il cliente e funziona anche durante il
// blackout del cliente (la sonda non è dal cliente).
package nettrace

import (
	"context"
	"os/exec"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"time"
)

// Hop è un singolo salto del percorso.
type Hop struct {
	Hop     int     `json:"hop"`
	Host    string  `json:"host,omitempty"`
	IP      string  `json:"ip,omitempty"`
	LossPct float64 `json:"loss_pct"`
	AvgMs   float64 `json:"avg_ms"`
	Timeout bool    `json:"timeout"`
}

// Result è l'esito completo di un net_trace.
type Result struct {
	Target   string `json:"target"`
	Mode     string `json:"mode"`  // icmp|tcp|udp
	Port     int    `json:"port"`  // per tcp/udp
	Tool     string `json:"tool"`  // mtr|traceroute|tracert
	OS       string `json:"os"`
	Hops     []Hop  `json:"hops"`
	Reached  bool   `json:"reached"`
	Raw      string `json:"raw,omitempty"`
	Error    string `json:"error,omitempty"`
	Duration int64  `json:"duration_ms"`
}

// Args parametri del comando net_trace.
type Args struct {
	Target   string `json:"target"`
	Mode     string `json:"mode"`   // icmp (default) | tcp | udp
	Port     int    `json:"port"`   // default 443 per tcp
	MaxHops  int    `json:"max_hops"`
	Count    int    `json:"count"`  // cicli per hop (mtr)
}

func (a *Args) normalize() {
	a.Target = strings.TrimSpace(a.Target)
	if a.Mode == "" {
		a.Mode = "icmp"
	}
	if a.Port <= 0 {
		a.Port = 443
	}
	if a.MaxHops <= 0 || a.MaxHops > 40 {
		a.MaxHops = 30
	}
	if a.Count <= 0 || a.Count > 100 {
		a.Count = 10
	}
}

// hasTool ritorna true se un binario è nel PATH.
func hasTool(name string) bool {
	_, err := exec.LookPath(name)
	return err == nil
}

// Run esegue la diagnosi scegliendo il miglior tool disponibile per l'OS.
func Run(ctx context.Context, a Args) Result {
	a.normalize()
	res := Result{Target: a.Target, Mode: a.Mode, Port: a.Port, OS: runtime.GOOS}
	start := time.Now()
	defer func() { res.Duration = time.Since(start).Milliseconds() }()

	if a.Target == "" {
		res.Error = "target mancante"
		return res
	}

	var out string
	var err error
	switch runtime.GOOS {
	case "windows":
		res.Tool = "tracert"
		out, err = runCmd(ctx, "tracert", "-d", "-h", itoa(a.MaxHops), "-w", "1500", a.Target)
		res.Raw = out
		if err != nil && out == "" {
			res.Error = err.Error()
			return res
		}
		res.Hops = ParseTracert(out)
	default: // linux, darwin
		if hasTool("mtr") {
			res.Tool = "mtr"
			args := []string{"--report", "--report-cycles", itoa(a.Count), "-n", "-c", itoa(a.Count)}
			if a.Mode == "tcp" {
				args = append(args, "--tcp", "--port", itoa(a.Port))
			} else if a.Mode == "udp" {
				args = append(args, "--udp")
			}
			args = append(args, a.Target)
			out, err = runCmd(ctx, "mtr", args...)
			res.Raw = out
			if err != nil && out == "" {
				res.Error = err.Error()
				return res
			}
			res.Hops = ParseMTR(out)
		} else if hasTool("traceroute") {
			res.Tool = "traceroute"
			args := []string{"-n", "-m", itoa(a.MaxHops), "-w", "2"}
			if a.Mode == "tcp" {
				args = append(args, "-T", "-p", itoa(a.Port))
			} else if a.Mode == "udp" {
				args = append(args, "-U", "-p", itoa(a.Port))
			}
			args = append(args, a.Target)
			out, err = runCmd(ctx, "traceroute", args...)
			res.Raw = out
			if err != nil && out == "" {
				res.Error = err.Error()
				return res
			}
			res.Hops = ParseTraceroute(out)
		} else {
			res.Error = "nessun tool disponibile (installa 'mtr' o 'traceroute' sulla sonda)"
			return res
		}
	}

	// Determina se il target è stato raggiunto: ultimo hop con loss < 100%.
	for i := len(res.Hops) - 1; i >= 0; i-- {
		if !res.Hops[i].Timeout && res.Hops[i].LossPct < 100 {
			res.Reached = true
			break
		}
	}
	return res
}

func runCmd(ctx context.Context, name string, args ...string) (string, error) {
	cctx, cancel := context.WithTimeout(ctx, 90*time.Second)
	defer cancel()
	cmd := exec.CommandContext(cctx, name, args...)
	b, err := cmd.CombinedOutput()
	return string(b), err
}

func itoa(n int) string { return strconv.Itoa(n) }

// ---------------- Parsers (pura logica, unit-testabili) ----------------

var (
	// mtr --report riga: " 1.|-- 192.168.1.1  Loss% Snt Last Avg ..."
	//   colonne: Loss% Snt Last Avg Best Wrst StDev → catturiamo Loss e Avg (4° numero).
	reMTR = regexp.MustCompile(`^\s*(\d+)\.\|--\s+(\S+)\s+([\d.]+)%\s+\d+\s+[\d.]+\s+([\d.]+)`)
	// traceroute -n riga: " 3  10.0.0.1  1.234 ms  1.111 ms  1.222 ms"
	reTR = regexp.MustCompile(`^\s*(\d+)\s+(.*)$`)
	reTRip = regexp.MustCompile(`(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})`)
	reTRms = regexp.MustCompile(`([\d.]+)\s*ms`)
	// tracert riga: "  3    12 ms    11 ms    13 ms  10.0.0.1"
	reWinIP = regexp.MustCompile(`(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})`)
	reWinHop = regexp.MustCompile(`^\s*(\d+)\s+`)
	reWinMs  = regexp.MustCompile(`(\d+)\s*ms`)
)

// ParseMTR normalizza l'output di `mtr --report`.
func ParseMTR(out string) []Hop {
	var hops []Hop
	for _, line := range strings.Split(out, "\n") {
		m := reMTR.FindStringSubmatch(line)
		if m == nil {
			continue
		}
		n, _ := strconv.Atoi(m[1])
		loss, _ := strconv.ParseFloat(m[3], 64)
		avg, _ := strconv.ParseFloat(m[4], 64)
		host := m[2]
		h := Hop{Hop: n, LossPct: loss, AvgMs: avg}
		if host == "???" {
			h.Timeout = true
			h.LossPct = 100
		} else if reTRip.MatchString(host) {
			h.IP = host
		} else {
			h.Host = host
		}
		hops = append(hops, h)
	}
	return hops
}

// ParseTraceroute normalizza l'output di `traceroute -n`.
func ParseTraceroute(out string) []Hop {
	var hops []Hop
	for _, line := range strings.Split(out, "\n") {
		if strings.HasPrefix(strings.TrimSpace(line), "traceroute") {
			continue
		}
		m := reTR.FindStringSubmatch(line)
		if m == nil {
			continue
		}
		n, err := strconv.Atoi(m[1])
		if err != nil {
			continue
		}
		rest := m[2]
		h := Hop{Hop: n}
		if strings.Contains(rest, "* * *") || strings.TrimSpace(rest) == "*" || !reTRip.MatchString(rest) {
			h.Timeout = true
			h.LossPct = 100
		} else {
			if ip := reTRip.FindString(rest); ip != "" {
				h.IP = ip
			}
			ms := reTRms.FindAllStringSubmatch(rest, -1)
			if len(ms) > 0 {
				var sum float64
				for _, mm := range ms {
					v, _ := strconv.ParseFloat(mm[1], 64)
					sum += v
				}
				h.AvgMs = sum / float64(len(ms))
			}
			// loss stimato dalla presenza di '*' misti alle risposte
			stars := strings.Count(rest, "*")
			probes := len(ms) + stars
			if probes > 0 {
				h.LossPct = float64(stars) / float64(probes) * 100
			}
		}
		hops = append(hops, h)
	}
	return hops
}

// ParseTracert normalizza l'output di Windows `tracert -d`.
func ParseTracert(out string) []Hop {
	var hops []Hop
	for _, line := range strings.Split(out, "\n") {
		hm := reWinHop.FindStringSubmatch(line)
		if hm == nil {
			continue
		}
		n, _ := strconv.Atoi(hm[1])
		h := Hop{Hop: n}
		ip := reWinIP.FindString(line)
		stars := strings.Count(line, "*")
		ms := reWinMs.FindAllStringSubmatch(line, -1)
		if ip == "" && stars > 0 {
			h.Timeout = true
			h.LossPct = 100
		} else {
			h.IP = ip
			if len(ms) > 0 {
				var sum float64
				for _, mm := range ms {
					v, _ := strconv.ParseFloat(mm[1], 64)
					sum += v
				}
				h.AvgMs = sum / float64(len(ms))
			}
			probes := len(ms) + stars
			if probes > 0 {
				h.LossPct = float64(stars) / float64(probes) * 100
			}
		}
		hops = append(hops, h)
	}
	return hops
}
