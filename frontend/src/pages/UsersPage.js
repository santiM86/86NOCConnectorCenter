import { useState, useEffect } from "react";
import axios from "axios";
import { API, useAuth } from "@/App";
import { toast } from "sonner";
import {
  Users,
  UserPlus,
  ShieldCheck,
  ShieldSlash,
  Trash,
  PencilSimple,
  QrCode,
  X,
  Eye,
  EyeSlash,
  CheckCircle,
  WarningCircle,
  Crown,
  UserCircle,
  MagnifyingGlass,
  Power,
  LockOpen
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const ROLES = [
  { value: "admin", label: "Admin", color: "text-amber-400", bg: "bg-amber-500/10 border-amber-500/20" },
  { value: "operator", label: "Operatore", color: "text-blue-400", bg: "bg-blue-500/10 border-blue-500/20" },
  { value: "viewer", label: "Viewer", color: "text-zinc-400", bg: "bg-zinc-500/10 border-zinc-500/20" }
];

function getRoleStyle(role) {
  return ROLES.find(r => r.value === role) || ROLES[2];
}

export default function UsersPage() {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [editingUser, setEditingUser] = useState(null);
  const [mfaSetup, setMfaSetup] = useState(null);
  const [mfaCode, setMfaCode] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [search, setSearch] = useState("");
  const [newUser, setNewUser] = useState({ name: "", email: "", password: "", role: "operator" });

  const isAdmin = currentUser?.role === "admin";

  useEffect(() => {
    fetchUsers();
  }, []);

  const fetchUsers = async () => {
    try {
      const res = await axios.get(`${API}/admin/users`);
      setUsers(res.data);
    } catch (err) {
      if (err.response?.status === 403) {
        toast.error("Accesso riservato agli amministratori");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    try {
      await axios.post(`${API}/admin/users`, newUser);
      toast.success(`Utente ${newUser.email} creato`);
      setNewUser({ name: "", email: "", password: "", role: "operator" });
      setShowCreate(false);
      fetchUsers();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Errore creazione utente");
    }
  };

  const handleUpdateRole = async (userId, newRole) => {
    try {
      await axios.put(`${API}/admin/users/${userId}`, { role: newRole });
      toast.success("Ruolo aggiornato");
      setEditingUser(null);
      fetchUsers();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Errore aggiornamento");
    }
  };

  const handleDelete = async (u) => {
    if (!window.confirm(`Eliminare l'utente ${u.email}?`)) return;
    try {
      await axios.delete(`${API}/admin/users/${u.id}`);
      toast.success("Utente eliminato");
      fetchUsers();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Errore eliminazione");
    }
  };

  const handleReset2FA = async (u) => {
    if (!window.confirm(`Reset 2FA per ${u.email}? L'utente dovrà riconfigurare l'autenticatore.`)) return;
    try {
      await axios.post(`${API}/admin/users/${u.id}/reset-2fa`);
      toast.success("2FA resettato");
      fetchUsers();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Errore reset 2FA");
    }
  };

  const handleToggleActive = async (u) => {
    const action = u.is_active !== false ? "disattivare" : "riattivare";
    if (!window.confirm(`Vuoi ${action} l'utente ${u.email}?`)) return;
    try {
      const res = await axios.put(`${API}/admin/users/${u.id}/toggle-active`);
      toast.success(`Utente ${res.data.is_active ? "attivato" : "disattivato"}`);
      fetchUsers();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Errore cambio stato");
    }
  };

  const handleUnlock = async (u) => {
    try {
      await axios.put(`${API}/admin/users/${u.id}/unlock`);
      toast.success(`Utente ${u.email} sbloccato`);
      fetchUsers();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Errore sblocco");
    }
  };

  const handleSetup2FA = async (u) => {
    try {
      const res = await axios.post(`${API}/admin/users/${u.id}/force-2fa`);
      setMfaSetup({ ...res.data, userId: u.id, userName: u.name });
      setMfaCode("");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Errore setup 2FA");
    }
  };

  const handleConfirm2FA = async () => {
    try {
      await axios.post(`${API}/admin/users/${mfaSetup.userId}/confirm-2fa`, { code: mfaCode });
      toast.success("2FA attivato con successo");
      setMfaSetup(null);
      setMfaCode("");
      fetchUsers();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Codice non valido");
    }
  };

  const filtered = users.filter(u =>
    u.name?.toLowerCase().includes(search.toLowerCase()) ||
    u.email?.toLowerCase().includes(search.toLowerCase())
  );

  if (!isAdmin) {
    return (
      <div className="p-4 md:p-5 animate-fade-in" data-testid="users-page-no-access">
        <div className="noc-panel p-8 text-center">
          <ShieldSlash size={40} className="text-red-400 mx-auto mb-3" />
          <h2 className="text-[var(--text-primary)] text-lg font-bold">Accesso Negato</h2>
          <p className="text-[var(--text-muted)] text-sm mt-1">Solo gli amministratori possono gestire gli utenti.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 md:p-5 animate-fade-in" data-testid="users-page">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="font-heading text-xl font-bold text-[var(--text-primary)] tracking-tight">Gestione Utenti</h1>
          <p className="text-[var(--text-muted)] text-xs mt-0.5">Crea utenti, assegna ruoli e gestisci MFA</p>
        </div>
        <Button
          onClick={() => setShowCreate(true)}
          size="sm"
          className="rounded-md text-xs h-8 bg-indigo-600 hover:bg-indigo-700 text-white"
          data-testid="create-user-btn"
        >
          <UserPlus size={14} className="mr-1.5" />
          Nuovo Utente
        </Button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-3 mb-5">
        <div className="noc-panel p-3">
          <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest">Totale</p>
          <p className="text-xl font-bold text-[var(--text-primary)] mt-1" data-testid="users-total">{users.length}</p>
        </div>
        <div className="noc-panel p-3">
          <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest">Attivi</p>
          <p className="text-xl font-bold text-emerald-400 mt-1" data-testid="users-active-count">{users.filter(u => u.is_active !== false).length}</p>
        </div>
        <div className="noc-panel p-3">
          <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest">MFA Attivo</p>
          <p className="text-xl font-bold text-blue-400 mt-1" data-testid="users-mfa-count">{users.filter(u => u.two_factor_enabled).length}</p>
        </div>
        <div className="noc-panel p-3">
          <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest">Admin</p>
          <p className="text-xl font-bold text-amber-400 mt-1" data-testid="users-admin-count">{users.filter(u => u.role === "admin").length}</p>
        </div>
      </div>

      {/* Search */}
      <div className="relative mb-4">
        <MagnifyingGlass size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
        <input
          type="text"
          placeholder="Cerca per nome o email..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full h-8 pl-9 pr-3 rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)] text-xs focus:outline-none focus:border-indigo-500"
          data-testid="users-search-input"
        />
      </div>

      {/* User List */}
      <div className="space-y-2" data-testid="users-list">
        {loading ? (
          <div className="noc-panel p-8 text-center text-[var(--text-muted)] text-sm">Caricamento...</div>
        ) : filtered.length === 0 ? (
          <div className="noc-panel p-8 text-center text-[var(--text-muted)] text-sm">Nessun utente trovato</div>
        ) : (
          filtered.map(u => (
            <UserRow
              key={u.id}
              user={u}
              currentUserId={currentUser?.id}
              editingUser={editingUser}
              onEdit={setEditingUser}
              onUpdateRole={handleUpdateRole}
              onDelete={handleDelete}
              onReset2FA={handleReset2FA}
              onSetup2FA={handleSetup2FA}
              onToggleActive={handleToggleActive}
              onUnlock={handleUnlock}
            />
          ))
        )}
      </div>

      {/* Create User Modal */}
      {showCreate && (
        <Modal onClose={() => setShowCreate(false)} title="Nuovo Utente">
          <form onSubmit={handleCreate} className="space-y-4">
            <div>
              <Label className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest">Nome *</Label>
              <Input
                value={newUser.name}
                onChange={(e) => setNewUser(p => ({ ...p, name: e.target.value }))}
                required
                placeholder="Mario Rossi"
                className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] text-xs h-9 mt-1"
                data-testid="new-user-name"
              />
            </div>
            <div>
              <Label className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest">Email *</Label>
              <Input
                type="email"
                value={newUser.email}
                onChange={(e) => setNewUser(p => ({ ...p, email: e.target.value }))}
                required
                placeholder="operatore@azienda.it"
                className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] text-xs h-9 mt-1"
                data-testid="new-user-email"
              />
            </div>
            <div>
              <Label className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest">Password *</Label>
              <div className="relative mt-1">
                <Input
                  type={showPassword ? "text" : "password"}
                  value={newUser.password}
                  onChange={(e) => setNewUser(p => ({ ...p, password: e.target.value }))}
                  required
                  minLength={8}
                  placeholder="Min. 8 caratteri"
                  className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] text-xs h-9 pr-9"
                  data-testid="new-user-password"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                >
                  {showPassword ? <EyeSlash size={14} /> : <Eye size={14} />}
                </button>
              </div>
            </div>
            <div>
              <Label className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest">Ruolo *</Label>
              <div className="flex gap-2 mt-2">
                {ROLES.map(r => (
                  <button
                    key={r.value}
                    type="button"
                    onClick={() => setNewUser(p => ({ ...p, role: r.value }))}
                    className={`flex-1 py-2 rounded-md text-xs font-medium border transition-all ${
                      newUser.role === r.value
                        ? `${r.bg} ${r.color} border-current`
                        : "border-[var(--bg-border)] text-[var(--text-muted)] hover:border-[var(--text-muted)]"
                    }`}
                    data-testid={`role-select-${r.value}`}
                  >
                    {r.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex gap-2 pt-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setShowCreate(false)}
                className="flex-1 rounded-md text-xs h-9 border-[var(--bg-border)] text-[var(--text-secondary)]"
              >
                Annulla
              </Button>
              <Button
                type="submit"
                size="sm"
                className="flex-1 rounded-md text-xs h-9 bg-indigo-600 hover:bg-indigo-700 text-white"
                data-testid="submit-create-user"
              >
                Crea Utente
              </Button>
            </div>
          </form>
        </Modal>
      )}

      {/* MFA Setup Modal */}
      {mfaSetup && (
        <Modal onClose={() => { setMfaSetup(null); setMfaCode(""); }} title="Configura Microsoft Authenticator">
          <div className="space-y-4">
            <div className="text-center">
              <p className="text-[var(--text-secondary)] text-xs mb-3">
                Scansiona il QR code con <strong className="text-[var(--text-primary)]">Microsoft Authenticator</strong> per l'utente:
              </p>
              <p className="text-indigo-400 font-mono text-sm mb-4">{mfaSetup.user_email}</p>
              <div className="inline-block bg-white p-3 rounded-lg">
                <img
                  src={`data:image/png;base64,${mfaSetup.qr_code}`}
                  alt="QR Code 2FA"
                  className="w-48 h-48"
                  data-testid="mfa-qr-code"
                />
              </div>
            </div>
            <div>
              <p className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest mb-1">Chiave manuale</p>
              <div className="bg-[var(--bg-hover)] rounded-md p-2 font-mono text-xs text-[var(--text-primary)] text-center select-all break-all" data-testid="mfa-secret-key">
                {mfaSetup.secret}
              </div>
            </div>
            <div>
              <Label className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest">Codice di verifica</Label>
              <Input
                type="text"
                inputMode="numeric"
                value={mfaCode}
                onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                placeholder="000000"
                maxLength={6}
                className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] text-center text-lg tracking-[0.3em] font-mono h-12 mt-1"
                data-testid="mfa-verify-code-input"
              />
              <p className="text-[var(--text-muted)] text-[10px] mt-1">Inserisci il codice a 6 cifre mostrato nell'app</p>
            </div>
            <Button
              onClick={handleConfirm2FA}
              disabled={mfaCode.length !== 6}
              className="w-full rounded-md text-xs h-9 bg-emerald-600 hover:bg-emerald-700 text-white disabled:opacity-50"
              data-testid="confirm-mfa-btn"
            >
              <ShieldCheck size={14} className="mr-1.5" />
              Attiva 2FA
            </Button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function UserRow({ user: u, currentUserId, editingUser, onEdit, onUpdateRole, onDelete, onReset2FA, onSetup2FA, onToggleActive, onUnlock }) {
  const roleStyle = getRoleStyle(u.role);
  const isCurrentUser = u.id === currentUserId;
  const isActive = u.is_active !== false;

  return (
    <div className={`noc-panel p-3 flex items-center gap-3 ${!isActive ? "opacity-50" : ""}`} data-testid={`user-row-${u.id}`}>
      <div className="w-9 h-9 rounded-md bg-[var(--bg-hover)] flex items-center justify-center flex-shrink-0">
        {u.role === "admin" ? (
          <Crown size={16} weight="fill" className="text-amber-400" />
        ) : (
          <UserCircle size={16} className="text-[var(--text-muted)]" />
        )}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <p className="text-[var(--text-primary)] text-sm font-medium truncate">{u.name}</p>
          {isCurrentUser && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">TU</span>
          )}
        </div>
        <p className="text-[var(--text-muted)] text-xs font-mono truncate">{u.email}</p>
      </div>

      {/* Role */}
      <div className="flex-shrink-0">
        {editingUser === u.id ? (
          <div className="flex gap-1">
            {ROLES.map(r => (
              <button
                key={r.value}
                onClick={() => onUpdateRole(u.id, r.value)}
                className={`px-2 py-1 rounded text-[10px] font-medium border transition-all ${
                  u.role === r.value
                    ? `${r.bg} ${r.color} border-current`
                    : "border-[var(--bg-border)] text-[var(--text-muted)] hover:border-[var(--text-muted)]"
                }`}
                data-testid={`edit-role-${r.value}-${u.id}`}
              >
                {r.label}
              </button>
            ))}
            <button onClick={() => onEdit(null)} className="text-[var(--text-muted)] hover:text-[var(--text-primary)] ml-1">
              <X size={12} />
            </button>
          </div>
        ) : (
          <span className={`text-[10px] px-2 py-1 rounded border font-medium ${roleStyle.bg} ${roleStyle.color}`} data-testid={`user-role-badge-${u.id}`}>
            {roleStyle.label}
          </span>
        )}
      </div>

      {/* Stato */}
      <div className="flex-shrink-0" data-testid={`user-status-${u.id}`}>
        {isActive ? (
          <span className="flex items-center gap-1 text-[10px] px-2 py-1 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
            <CheckCircle size={12} weight="fill" /> Attivo
          </span>
        ) : (
          <span className="flex items-center gap-1 text-[10px] px-2 py-1 rounded bg-red-500/10 border border-red-500/20 text-red-400">
            <WarningCircle size={12} /> Disattivato
          </span>
        )}
      </div>

      {/* 2FA Status */}
      <div className="flex-shrink-0" data-testid={`user-2fa-status-${u.id}`}>
        {u.two_factor_enabled ? (
          <span className="flex items-center gap-1 text-[10px] px-2 py-1 rounded bg-blue-500/10 border border-blue-500/20 text-blue-400">
            <ShieldCheck size={12} weight="fill" /> MFA
          </span>
        ) : (
          <span className="flex items-center gap-1 text-[10px] px-2 py-1 rounded bg-zinc-500/10 border border-zinc-500/20 text-zinc-500">
            No MFA
          </span>
        )}
      </div>

      {/* Actions */}
      {!isCurrentUser && (
        <div className="flex items-center gap-1 flex-shrink-0">
          <button
            onClick={() => onEdit(editingUser === u.id ? null : u.id)}
            className="p-1.5 rounded hover:bg-[var(--bg-hover)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-all"
            title="Modifica ruolo"
            data-testid={`edit-user-btn-${u.id}`}
          >
            <PencilSimple size={13} />
          </button>
          <button
            onClick={() => onToggleActive(u)}
            className={`p-1.5 rounded hover:bg-[var(--bg-hover)] transition-all ${isActive ? "text-[var(--text-muted)] hover:text-amber-400" : "text-amber-400 hover:text-emerald-400"}`}
            title={isActive ? "Disattiva utente" : "Riattiva utente"}
            data-testid={`toggle-active-btn-${u.id}`}
          >
            <Power size={13} />
          </button>
          <button
            onClick={() => onUnlock(u)}
            className="p-1.5 rounded hover:bg-[var(--bg-hover)] text-[var(--text-muted)] hover:text-blue-400 transition-all"
            title="Sblocca utente (brute force)"
            data-testid={`unlock-user-btn-${u.id}`}
          >
            <LockOpen size={13} />
          </button>
          {u.two_factor_enabled ? (
            <button
              onClick={() => onReset2FA(u)}
              className="p-1.5 rounded hover:bg-[var(--bg-hover)] text-[var(--text-muted)] hover:text-amber-400 transition-all"
              title="Reset 2FA"
              data-testid={`reset-2fa-btn-${u.id}`}
            >
              <ShieldSlash size={13} />
            </button>
          ) : (
            <button
              onClick={() => onSetup2FA(u)}
              className="p-1.5 rounded hover:bg-[var(--bg-hover)] text-[var(--text-muted)] hover:text-emerald-400 transition-all"
              title="Configura 2FA"
              data-testid={`setup-2fa-btn-${u.id}`}
            >
              <QrCode size={13} />
            </button>
          )}
          <button
            onClick={() => onDelete(u)}
            className="p-1.5 rounded hover:bg-[var(--bg-hover)] text-[var(--text-muted)] hover:text-red-400 transition-all"
            title="Elimina utente"
            data-testid={`delete-user-btn-${u.id}`}
          >
            <Trash size={13} />
          </button>
        </div>
      )}
    </div>
  );
}

function Modal({ onClose, title, children }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4" onClick={onClose}>
      <div
        className="noc-panel w-full max-w-md p-5 animate-fade-in"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4 pb-3 border-b border-[var(--bg-border)]">
          <h3 className="text-[var(--text-primary)] text-sm font-bold">{title}</h3>
          <button onClick={onClose} className="text-[var(--text-muted)] hover:text-[var(--text-primary)]">
            <X size={16} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
