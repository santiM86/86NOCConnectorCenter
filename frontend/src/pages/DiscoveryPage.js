import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

export default function DiscoveryPage({ scopedClientId = null, scopedClientName = "" }) {
  const [clients, setClients] = useState([]);
  const [selectedClient, setSelectedClient] = useState(scopedClientId || "");
  const [subnet, setSubnet] = useState("");
  const [results, setResults] = useState(null);
  const [status, setStatus] = useState("none");
  const [scanning, setScanning] = useState(false);
  const token = localStorage.getItem("noc_token");
  const headers = { Authorization: `Bearer ${token}` };

  useEffect(() => {
    if (scopedClientId) {
      setSelectedClient(scopedClientId);
      return;
    }
    axios.get(`${API}/api/clients`, { headers }).then(r => {
      const cl = Array.isArray(r.data) ? r.data : r.data.clients || [];
      setClients(cl);
      if (cl.length > 0) setSelectedClient(cl[0].id);
    }).catch(() => {});
  }, [scopedClientId]);

  const fetchResults = useCallback(() => {
    if (!selectedClient) return;
    axios.get(`${API}/api/connector/discovery-results/${selectedClient}`, { headers })
      .then(r => setResults(r.data)).catch(() => {});
    axios.get(`${API}/api/connector/discovery-status/${selectedClient}`, { headers })
      .then(r => {
        setStatus(r.data.status);
        if (r.data.status === "in_progress") setScanning(true);
        else setScanning(false);
      }).catch(() => {});
  }, [selectedClient]);

  useEffect(() => { fetchResults(); }, [fetchResults]);

  // Poll during scan
  useEffect(() => {
    if (!scanning) return;
    const interval = setInterval(fetchResults, 5000);
    return () => clearInterval(interval);
  }, [scanning, fetchResults]);

  const startScan = () => {
    setScanning(true);
    setStatus("pending");
    axios.post(`${API}/api/connector/start-discovery`, { client_id: selectedClient, subnet }, { headers })
      .then(() => toast.success("Scansione discovery avviata! Il connettore eseguira il scan della rete."))
      .catch(err => {
        toast.error(err.response?.data?.detail || "Errore avvio discovery");
        setScanning(false);
      });
  };

  const approveDevice = (device) => {
    const name = prompt("Nome dispositivo:", device.hostname || device.ip);
    if (!name) return;
    axios.post(`${API}/api/discovery/approve`, {
      client_id: selectedClient,
      ip: device.ip,
      name,
      community: device.community || "public",
      device_type: device.type || "network",
      monitor_type: device.snmp_available ? "snmp" : "ping",
    }, { headers })
      .then(() => {
        toast.success(`${name} aggiunto ai dispositivi gestiti!`);
        fetchResults();
      })
      .catch(err => toast.error(err.response?.data?.detail || "Errore approvazione"));
  };

  const dismissDevice = (device) => {
    axios.post(`${API}/api/discovery/dismiss`, { client_id: selectedClient, ip: device.ip }, { headers })
      .then(() => {
        toast.success("Dispositivo ignorato");
        fetchResults();
      })
      .catch(() => toast.error("Errore"));
  };

  // ==================== BMC CANDIDATES (v3.6.14) ====================
  const [bmcCandidates, setBmcCandidates] = useState([]);
  const fetchBmcCandidates = useCallback(() => {
    if (!selectedClient) return;
    axios.get(`${API}/api/bmc-candidates?client_id=${selectedClient}`, { headers })
      .then(r => setBmcCandidates(r.data.items || []))
      .catch(() => {});
  }, [selectedClient]);
  useEffect(() => { fetchBmcCandidates(); }, [fetchBmcCandidates]);
  useEffect(() => {
    if (!scanning) return;
    const i = setInterval(fetchBmcCandidates, 10000);
    return () => clearInterval(i);
  }, [scanning, fetchBmcCandidates]);

  const importBmc = (bmc) => {
    axios.post(`${API}/api/bmc-candidates/${selectedClient}/${encodeURIComponent(bmc.ip)}/import`, {}, { headers })
      .then(r => {
        if (r.data.status === "already_exists") {
          toast.info(`Device gia' presente (${bmc.ip})`);
        } else {
          toast.success(`BMC ${bmc.ip} aggiunto come ${r.data.name}. Aggiungi credenziali iLO/iDRAC in Vault.`);
        }
        fetchBmcCandidates();
        fetchResults();
      })
      .catch(err => toast.error(err.response?.data?.detail || "Errore import"));
  };
  const dismissBmc = (bmc) => {
    axios.post(`${API}/api/bmc-candidates/${selectedClient}/${encodeURIComponent(bmc.ip)}/dismiss`, {}, { headers })
      .then(() => {
        toast.success("BMC ignorato");
        fetchBmcCandidates();
      })
      .catch(() => toast.error("Errore"));
  };
  const bmcStyles = {
    ilo: { bg: "bg-emerald-500/20", border: "border-emerald-500/40", text: "text-emerald-300", label: "HPE iLO" },
    idrac: { bg: "bg-sky-500/20", border: "border-sky-500/40", text: "text-sky-300", label: "Dell iDRAC" },
    ipmi: { bg: "bg-violet-500/20", border: "border-violet-500/40", text: "text-violet-300", label: "Supermicro IPMI" },
    xcc: { bg: "bg-amber-500/20", border: "border-amber-500/40", text: "text-amber-300", label: "Lenovo XCC" },
    redfish_generic: { bg: "bg-slate-500/20", border: "border-slate-500/40", text: "text-slate-300", label: "Redfish BMC" },
  };
  const bmcStyle = (kind) => bmcStyles[kind] || bmcStyles.redfish_generic;

  const managedIps = results?.managed_ips || [];
  const devices = (results?.devices || []).filter(d => !managedIps.includes(d.ip));

  return (
    <div className="space-y-6" data-testid="discovery-page">
      <div className="flex items-center justify-between">
        <div>
          {!scopedClientId && <h1 className="text-2xl font-bold text-[var(--text-primary)]">Auto-Discovery Rete</h1>}
          <p className="text-sm text-[var(--text-secondary)]">
            {scopedClientId ? `Scansiona la rete di ${scopedClientName} per trovare nuovi dispositivi` : "Scansiona la rete per trovare nuovi dispositivi"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {!scopedClientId && (
            <select value={selectedClient} onChange={e => setSelectedClient(e.target.value)}
              className="h-8 px-3 text-xs rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)]"
              data-testid="discovery-client-select">
              {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          )}
          <input type="text" value={subnet} onChange={e => setSubnet(e.target.value)}
            placeholder="Subnet (es. 192.168.1.0/24)"
            className="h-8 px-3 text-xs rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)] w-52"
            data-testid="discovery-subnet-input" />
          <button onClick={startScan} disabled={scanning || !selectedClient}
            className="h-8 px-4 text-xs font-semibold rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
            data-testid="discovery-scan-btn">
            {scanning ? "Scansione in corso..." : "Avvia Discovery"}
          </button>
        </div>
      </div>

      {/* Status banner */}
      {status === "in_progress" && (
        <div className="rounded-lg border border-blue-500/30 bg-blue-500/5 p-3 flex items-center gap-2" data-testid="discovery-scanning">
          <div className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
          <span className="text-xs text-blue-400 font-semibold">Il connettore sta scansionando la rete... I risultati appariranno automaticamente.</span>
        </div>
      )}

      {/* Stats */}
      {results && results.scanned_at && (
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)] p-3 text-center">
            <p className="text-2xl font-bold text-[var(--text-primary)]">{results.device_count || 0}</p>
            <p className="text-xs text-[var(--text-secondary)]">Dispositivi Trovati</p>
          </div>
          <div className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)] p-3 text-center">
            <p className="text-2xl font-bold text-emerald-500">{managedIps.length}</p>
            <p className="text-xs text-[var(--text-secondary)]">Gia Gestiti</p>
          </div>
          <div className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)] p-3 text-center">
            <p className="text-2xl font-bold text-amber-500">{devices.length}</p>
            <p className="text-xs text-[var(--text-secondary)]">Da Approvare</p>
          </div>
        </div>
      )}

      {/* BMC Candidates (v3.6.14) - auto-scoperti da Redfish probe */}
      {bmcCandidates.length > 0 && (
        <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/5 overflow-hidden" data-testid="bmc-candidates-panel">
          <div className="p-3 border-b border-emerald-500/30 flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-emerald-300 flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                Server BMC Rilevati (Redfish)
              </h3>
              <p className="text-[11px] text-[var(--text-secondary)] mt-0.5">
                iLO / iDRAC / IPMI scoperti automaticamente dal connector. Importa per attivare il polling hardware server.
              </p>
            </div>
            <span className="px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 text-[10px] font-bold">{bmcCandidates.length} nuovi</span>
          </div>
          <div className="divide-y divide-emerald-500/20">
            {bmcCandidates.map((b, i) => {
              const s = bmcStyle(b.bmc_kind);
              return (
              <div key={i} className="flex items-center justify-between p-3 hover:bg-emerald-500/5 transition-colors" data-testid={`bmc-candidate-${i}`}>
                <div className="flex items-center gap-3">
                  <div className={`w-10 h-10 rounded-md flex items-center justify-center ${s.bg} border ${s.border}`}>
                    <span className={`text-[10px] font-bold ${s.text} uppercase tracking-wider`}>BMC</span>
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-semibold text-[var(--text-primary)]">{s.label}</p>
                      {b.redfish_version && (
                        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[var(--bg-surface)] text-[var(--text-secondary)] border border-[var(--bg-border)]">
                          Redfish {b.redfish_version}
                        </span>
                      )}
                    </div>
                    <p className="text-[11px] font-mono text-[var(--text-secondary)]">
                      {b.ip}
                      {b.mac ? <> · MAC {b.mac}</> : null}
                      {b.switch_ip ? <> · via switch {b.switch_ip} porta {b.switch_port}</> : null}
                      {b.vlan ? <> · VLAN {b.vlan}</> : null}
                    </p>
                    {b.server_header && (
                      <p className="text-[10px] italic text-[var(--text-secondary)] opacity-70 truncate max-w-md" title={b.server_header}>
                        {b.server_header}
                      </p>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={() => importBmc(b)}
                    className="h-7 px-3 text-xs font-semibold rounded-md bg-emerald-600 text-white hover:bg-emerald-700"
                    data-testid={`import-bmc-${i}`}>
                    Importa come server
                  </button>
                  <button onClick={() => dismissBmc(b)}
                    className="h-7 px-3 text-xs rounded-md border border-[var(--bg-border)] text-[var(--text-secondary)] hover:bg-[var(--bg-surface)]"
                    data-testid={`dismiss-bmc-${i}`}>
                    Ignora
                  </button>
                </div>
              </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Discovered devices list */}
      {devices.length > 0 && (
        <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] overflow-hidden">
          <div className="p-3 border-b border-[var(--bg-border)]">
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">Dispositivi Scoperti</h3>
          </div>
          <div className="divide-y divide-[var(--bg-border)]">
            {devices.map((dev, i) => (
              <div key={i} className="flex items-center justify-between p-3 hover:bg-[var(--bg-surface)] transition-colors" data-testid={`discovered-device-${i}`}>
                <div className="flex items-center gap-3">
                  <div className={`w-2 h-2 rounded-full ${dev.reachable ? "bg-emerald-500" : "bg-red-500"}`} />
                  <div>
                    <p className="text-sm font-medium text-[var(--text-primary)]">{dev.hostname || dev.ip}</p>
                    <p className="text-xs text-[var(--text-secondary)]">
                      {dev.ip} {dev.mac ? `| MAC: ${dev.mac}` : ""} {dev.vendor ? `| ${dev.vendor}` : ""}
                      {dev.snmp_available ? " | SNMP" : " | Solo Ping"}
                      {dev.type ? ` | ${dev.type}` : ""}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={() => approveDevice(dev)}
                    className="h-7 px-3 text-xs font-semibold rounded-md bg-emerald-600 text-white hover:bg-emerald-700"
                    data-testid={`approve-device-${i}`}>
                    Approva
                  </button>
                  <button onClick={() => dismissDevice(dev)}
                    className="h-7 px-3 text-xs rounded-md border border-[var(--bg-border)] text-[var(--text-secondary)] hover:bg-[var(--bg-surface)]"
                    data-testid={`dismiss-device-${i}`}>
                    Ignora
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Already managed */}
      {results && managedIps.length > 0 && (
        <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-4">
          <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2">Dispositivi Gia Gestiti</h3>
          <div className="flex flex-wrap gap-2">
            {managedIps.map(ip => (
              <span key={ip} className="px-2 py-1 text-xs rounded-md bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                {ip}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Empty state */}
      {!results?.scanned_at && status === "none" && (
        <div className="text-center py-16">
          <svg className="w-12 h-12 mx-auto mb-3 text-[var(--text-secondary)] opacity-50" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
          </svg>
          <p className="text-sm text-[var(--text-secondary)]">Nessuna scansione eseguita. Clicca "Avvia Discovery" per scansionare la rete.</p>
        </div>
      )}

      {results?.scanned_at && (
        <p className="text-xs text-[var(--text-secondary)] text-center">
          Ultima scansione: {new Date(results.scanned_at).toLocaleString("it-IT")}
        </p>
      )}
    </div>
  );
}
