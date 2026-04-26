import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Shield, Plus, Trash, ArrowLeft, Warning, Globe, Lock, Eye, EyeSlash } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter
} from "@/components/ui/dialog";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle
} from "@/components/ui/alert-dialog";

export default function IPAllowlistPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [myIp, setMyIp] = useState({ client_ip: "", allowed: true, reason: "" });
  const [adding, setAdding] = useState(false);
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [newCidr, setNewCidr] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [newEnabled, setNewEnabled] = useState(true);
  const [forceConfirm, setForceConfirm] = useState(null); // {message, your_ip, rule}
  const [deleteCandidate, setDeleteCandidate] = useState(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [list, check] = await Promise.all([
        axios.get(`${API}/admin/security/allowed-ips`),
        axios.get(`${API}/admin/security/allowed-ips/check`),
      ]);
      setItems(list.data.items || []);
      setMyIp(check.data || { client_ip: "" });
    } catch (e) {
      toast.error("Errore caricamento allowlist", { description: e?.response?.data?.detail || e.message });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  const submitAdd = async (force = false) => {
    if (!newCidr.trim()) { toast.error("Inserisci un IP o range CIDR"); return; }
    setAdding(true);
    try {
      const url = `${API}/admin/security/allowed-ips${force ? "?force=true" : ""}`;
      await axios.post(url, {
        cidr: newCidr.trim(),
        description: newDesc.trim(),
        enabled: newEnabled,
      });
      toast.success("Regola aggiunta", { description: newCidr });
      setShowAddDialog(false);
      setForceConfirm(null);
      setNewCidr(""); setNewDesc(""); setNewEnabled(true);
      await loadAll();
    } catch (e) {
      const detail = e?.response?.data?.detail;
      // Lockout protection: backend ritorna 422 con detail.error="lockout_risk"
      if (e?.response?.status === 422 && detail?.error === "lockout_risk") {
        setForceConfirm(detail);
      } else {
        toast.error("Errore aggiunta regola", {
          description: typeof detail === "string" ? detail : (detail?.message || e.message),
        });
      }
    } finally {
      setAdding(false);
    }
  };

  const toggleEnabled = async (item) => {
    try {
      await axios.patch(`${API}/admin/security/allowed-ips/${item.id}`, { enabled: !item.enabled });
      toast.success(item.enabled ? "Regola disabilitata" : "Regola abilitata");
      await loadAll();
    } catch (e) {
      toast.error("Errore aggiornamento", { description: e?.response?.data?.detail || e.message });
    }
  };

  const deleteItem = async () => {
    if (!deleteCandidate) return;
    try {
      await axios.delete(`${API}/admin/security/allowed-ips/${deleteCandidate.id}`);
      toast.success("Regola eliminata");
      setDeleteCandidate(null);
      await loadAll();
    } catch (e) {
      toast.error("Errore eliminazione", { description: e?.response?.data?.detail || e.message });
    }
  };

  const allowlistActive = items.some(i => i.enabled);

  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto" data-testid="ip-allowlist-page">
      {/* Header */}
      <div className="flex items-center gap-3 mb-5">
        <Button variant="ghost" size="sm" onClick={() => navigate("/settings")}
          className="h-8 px-2" data-testid="back-to-settings-btn">
          <ArrowLeft size={14} />
        </Button>
        <div>
          <h1 className="text-[var(--text-primary)] text-base md:text-lg font-semibold flex items-center gap-2">
            <Shield size={18} className="text-emerald-400" /> IP Pubblici Autorizzati
          </h1>
          <p className="text-[var(--text-muted)] text-xs mt-0.5">
            Limita l'accesso ad endpoint admin e login solo a indirizzi IP/range di rete autorizzati.
          </p>
        </div>
      </div>

      {/* Status banner: il tuo IP attuale */}
      <div className="noc-panel p-4 mb-4 flex items-center gap-3" data-testid="my-ip-banner">
        <div className={`w-9 h-9 rounded-full flex items-center justify-center ${myIp.allowed ? 'bg-emerald-400/10 text-emerald-400' : 'bg-amber-400/10 text-amber-400'}`}>
          <Globe size={18} />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-[var(--text-primary)] text-xs font-medium">
            Il tuo IP attuale: <span className="font-mono text-emerald-400">{myIp.client_ip || "?"}</span>
          </p>
          <p className="text-[var(--text-muted)] text-[10px] mt-0.5">
            {myIp.reason === "empty_list" && "Allowlist disabilitata (vuota): tutti gli IP possono accedere."}
            {myIp.reason === "loopback" && "Loopback (server stesso): bypass automatico."}
            {myIp.reason?.startsWith("match:") && `Autorizzato dalla regola ${myIp.reason.replace("match:", "")}`}
            {myIp.reason === "not_in_allowlist" && "ATTENZIONE: il tuo IP NON è in allowlist. Se aggiungi altre regole rischi il lock-out."}
            {!myIp.reason && ""}
          </p>
        </div>
        <Button onClick={() => setShowAddDialog(true)} size="sm" className="h-8 rounded-md text-xs"
          data-testid="add-allowed-ip-btn">
          <Plus size={13} className="mr-1" /> Aggiungi
        </Button>
      </div>

      {/* Status allowlist */}
      <div className="mb-4">
        {allowlistActive ? (
          <div className="flex items-center gap-2 text-[11px] text-emerald-400 bg-emerald-400/5 border border-emerald-400/20 rounded-md px-3 py-2">
            <Lock size={13} /> Allowlist <strong>ATTIVA</strong> — solo gli IP/range elencati possono accedere a /api/admin/* e /api/auth/login.
          </div>
        ) : (
          <div className="flex items-center gap-2 text-[11px] text-amber-400 bg-amber-400/5 border border-amber-400/20 rounded-md px-3 py-2">
            <Warning size={13} /> Allowlist <strong>INATTIVA</strong> — nessuna regola abilitata. Aggiungine almeno una per attivare la protezione.
          </div>
        )}
      </div>

      {/* Lista */}
      <div className="noc-panel overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-[var(--text-muted)] text-xs">Caricamento...</div>
        ) : items.length === 0 ? (
          <div className="p-12 text-center">
            <Shield size={36} className="mx-auto mb-3 text-[var(--text-muted)] opacity-30" />
            <p className="text-[var(--text-muted)] text-xs">
              Nessuna regola configurata. Aggiungi un IP o range CIDR per attivare la protezione.
            </p>
            <Button onClick={() => setShowAddDialog(true)} size="sm" className="mt-3 h-7 rounded-md text-xs"
              data-testid="add-first-ip-btn">
              <Plus size={13} className="mr-1" /> Aggiungi primo IP
            </Button>
          </div>
        ) : (
          <table className="w-full text-xs" data-testid="allowed-ips-table">
            <thead>
              <tr className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider bg-[var(--bg-hover)]/50">
                <th className="text-left px-3 py-2 font-medium">CIDR / IP</th>
                <th className="text-left px-3 py-2 font-medium">Descrizione</th>
                <th className="text-left px-3 py-2 font-medium">Aggiunto da</th>
                <th className="text-center px-3 py-2 font-medium">Stato</th>
                <th className="text-right px-3 py-2 font-medium">Azioni</th>
              </tr>
            </thead>
            <tbody>
              {items.map(item => (
                <tr key={item.id} className="border-t border-[var(--bg-border)] hover:bg-[var(--bg-hover)]/30"
                  data-testid={`row-${item.id}`}>
                  <td className="px-3 py-2 font-mono text-[var(--text-primary)]">
                    {item.cidr}
                    {myIp.client_ip && ipMatchesCidr(myIp.client_ip, item.cidr) && (
                      <span className="ml-2 text-[9px] px-1.5 py-0.5 rounded bg-emerald-400/10 text-emerald-400">tu</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-[var(--text-secondary)]">
                    {item.description || <span className="text-[var(--text-muted)] italic">—</span>}
                  </td>
                  <td className="px-3 py-2 text-[var(--text-muted)] text-[10px]">
                    {item.created_by || "?"}<br />
                    <span className="opacity-60">{formatDate(item.created_at)}</span>
                  </td>
                  <td className="px-3 py-2 text-center">
                    <Switch checked={item.enabled} onCheckedChange={() => toggleEnabled(item)}
                      data-testid={`toggle-${item.id}`} />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Button size="sm" variant="ghost" onClick={() => setDeleteCandidate(item)}
                      className="h-7 w-7 p-0 hover:bg-red-500/10 hover:text-red-400"
                      data-testid={`delete-${item.id}`}>
                      <Trash size={13} />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <p className="text-[var(--text-muted)] text-[10px] mt-3 leading-relaxed">
        💡 Suggerimento: gli endpoint del connector (heartbeat, device-report) bypassano sempre l'allowlist
        perché autenticati via API key. Le regole bloccano solo l'accesso admin/login al Center.
      </p>

      {/* DIALOG: Aggiungi nuova regola */}
      <Dialog open={showAddDialog} onOpenChange={setShowAddDialog}>
        <DialogContent className="sm:max-w-md" data-testid="add-ip-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Plus size={16} /> Nuova regola allowlist
            </DialogTitle>
            <DialogDescription className="text-xs">
              Inserisci un IP singolo (es. 79.5.10.20) o un range CIDR (es. 79.5.0.0/16).
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label htmlFor="cidr-input" className="text-xs">IP o CIDR *</Label>
              <Input id="cidr-input" value={newCidr} onChange={(e) => setNewCidr(e.target.value)}
                placeholder="es. 79.5.10.20 oppure 79.5.0.0/16"
                className="mt-1 font-mono text-xs"
                autoFocus
                data-testid="cidr-input" />
            </div>
            <div>
              <Label htmlFor="desc-input" className="text-xs">Descrizione (opzionale)</Label>
              <Input id="desc-input" value={newDesc} onChange={(e) => setNewDesc(e.target.value)}
                placeholder="es. Ufficio 86bit Treviso"
                className="mt-1 text-xs"
                data-testid="description-input" />
            </div>
            <div className="flex items-center gap-3 py-1">
              <Switch checked={newEnabled} onCheckedChange={setNewEnabled} data-testid="enabled-toggle" />
              <Label className="text-xs cursor-pointer" onClick={() => setNewEnabled(v => !v)}>
                Attiva subito
              </Label>
            </div>
            <div className="text-[10px] text-[var(--text-muted)] bg-[var(--bg-hover)]/30 rounded p-2">
              Il tuo IP attuale: <span className="font-mono text-emerald-400">{myIp.client_ip || "?"}</span>
              {newCidr.trim() && myIp.client_ip && (
                <> — La regola lo include?{" "}
                  <span className={ipMatchesCidr(myIp.client_ip, normalizeCidrPreview(newCidr)) ? "text-emerald-400 font-medium" : "text-amber-400 font-medium"}>
                    {ipMatchesCidr(myIp.client_ip, normalizeCidrPreview(newCidr)) ? "SÌ ✓" : "NO ✗ (rischio lock-out)"}
                  </span>
                </>
              )}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowAddDialog(false)} data-testid="cancel-add-btn">
              Annulla
            </Button>
            <Button onClick={() => submitAdd(false)} disabled={adding || !newCidr.trim()}
              data-testid="confirm-add-btn">
              {adding ? "Salvataggio..." : "Salva"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ALERT: Lock-out risk confirm */}
      <AlertDialog open={!!forceConfirm} onOpenChange={(o) => !o && setForceConfirm(null)}>
        <AlertDialogContent data-testid="lockout-confirm-dialog">
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2 text-amber-400">
              <Warning size={18} /> Rischio lock-out rilevato
            </AlertDialogTitle>
            <AlertDialogDescription className="text-xs leading-relaxed">
              {forceConfirm?.message}
              <div className="mt-3 p-2 bg-amber-400/5 border border-amber-400/20 rounded text-[10px] text-amber-400">
                ⚠️ Salvando questa regola NON potrai più accedere al Center dal tuo IP attuale {forceConfirm?.your_ip}.
                Procedi solo se hai accesso a un IP che corrisponde alla regola.
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel data-testid="cancel-force-btn">Annulla (consigliato)</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => submitAdd(true)}
              className="bg-amber-500 hover:bg-amber-600 text-white"
              data-testid="confirm-force-btn">
              Salvo comunque (force)
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* ALERT: delete confirm */}
      <AlertDialog open={!!deleteCandidate} onOpenChange={(o) => !o && setDeleteCandidate(null)}>
        <AlertDialogContent data-testid="delete-confirm-dialog">
          <AlertDialogHeader>
            <AlertDialogTitle>Elimina regola</AlertDialogTitle>
            <AlertDialogDescription className="text-xs">
              Confermi l'eliminazione di <span className="font-mono text-emerald-400">{deleteCandidate?.cidr}</span>?
              <br />
              Se questa è l'unica regola che ti consente l'accesso, dopo l'eliminazione non potrai più accedere come admin.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel data-testid="cancel-delete-btn">Annulla</AlertDialogCancel>
            <AlertDialogAction onClick={deleteItem}
              className="bg-red-500 hover:bg-red-600 text-white"
              data-testid="confirm-delete-btn">
              Elimina
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

// ====== helpers (lightweight CIDR check, matches python ipaddress) ======
function ipToInt(ip) {
  const parts = ip.split(".").map(Number);
  if (parts.length !== 4 || parts.some(p => isNaN(p) || p < 0 || p > 255)) return null;
  return ((parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]) >>> 0;
}

function ipMatchesCidr(ip, cidr) {
  if (!ip || !cidr) return false;
  if (!cidr.includes("/")) cidr = cidr + "/32";
  const [net, bits] = cidr.split("/");
  const ipi = ipToInt(ip);
  const neti = ipToInt(net);
  const b = parseInt(bits, 10);
  if (ipi === null || neti === null || isNaN(b) || b < 0 || b > 32) return false;
  if (b === 0) return true;
  const mask = (~((1 << (32 - b)) - 1)) >>> 0;
  return (ipi & mask) === (neti & mask);
}

function normalizeCidrPreview(value) {
  value = value.trim();
  if (!value) return "";
  if (!value.includes("/")) return value + "/32";
  return value;
}

function formatDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("it-IT", { dateStyle: "short", timeStyle: "short" });
  } catch { return iso; }
}
