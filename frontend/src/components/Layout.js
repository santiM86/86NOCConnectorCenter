import { useState, useEffect, useRef } from "react";
import { Outlet, NavLink, useNavigate, useLocation } from "react-router-dom";
import { useAuth, API } from "@/App";
import axios from "axios";
import { motion, AnimatePresence } from "framer-motion";
import {
  ShieldWarning,
  ChartLineUp,
  Bell,
  Buildings,
  HardDrives,
  SignOut,
  List,
  X,
  User,
  Gear,
  Wrench,
  PlugsConnected,
  Users,
  Lock,
  CaretDown,
  Pulse,
  Shield,
  House,
  DotsThreeOutline,
  WifiHigh,
  FileText,
  ListChecks,
  Ticket,
  Plug,
  Database,
  Printer,
  Monitor,
  ShieldCheck,
  ChartLine,
  MagnifyingGlass,
  CalendarBlank,
  Lightning,
  Sliders,
  ArrowsDownUp,
  Globe,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

// ==================== NAV CONFIG ====================
const navConfig = [
  {
    id: "monitoring",
    label: "Monitoraggio",
    items: [
      { path: "/", icon: ChartLineUp, label: "Dashboard", roles: ["admin", "operator", "viewer"] },
      { path: "/alerts", icon: Bell, label: "Alert", hasBadge: true, roles: ["admin", "operator", "viewer"] },
      { path: "/network-status", icon: WifiHigh, label: "Stato Rete", roles: ["admin", "operator", "viewer"] },
      { path: "/devices", icon: HardDrives, label: "Dispositivi", roles: ["admin", "operator", "viewer"] },
      { path: "/inventory", icon: Database, label: "Inventario", roles: ["admin", "operator", "viewer"] },
      { path: "/port-monitor", icon: Plug, label: "Monitor Servizi", roles: ["admin", "operator"] },
      { path: "/printers", icon: Printer, label: "Stampanti", roles: ["admin", "operator", "viewer"] },
      { path: "/bandwidth", icon: ArrowsDownUp, label: "Bandwidth", roles: ["admin", "operator", "viewer"] },
      { path: "/backup", icon: Database, label: "Backup", roles: ["admin", "operator", "viewer"] },
      { path: "/trends", icon: ChartLine, label: "Grafici Trend", roles: ["admin", "operator", "viewer"] },
      { path: "/wan-monitor", icon: Globe, label: "Monitor WAN", roles: ["admin", "operator"] },
    ],
  },
  {
    id: "operations",
    label: "Operazioni",
    items: [
      { path: "/incidents", icon: Ticket, label: "Incidenti", roles: ["admin", "operator"] },
      { path: "/maintenance", icon: CalendarBlank, label: "Manutenzione", roles: ["admin", "operator"] },
      { path: "/reports", icon: FileText, label: "Report PDF", roles: ["admin", "operator"] },
    ],
  },
  {
    id: "infrastructure",
    label: "Infrastruttura",
    items: [
      { path: "/clients", icon: Buildings, label: "Clienti", roles: ["admin", "operator", "viewer"] },
      { path: "/connectors", icon: PlugsConnected, label: "Connettori", roles: ["admin", "operator"] },
      { path: "/discovery", icon: MagnifyingGlass, label: "Auto-Discovery", roles: ["admin", "operator"] },
    ],
  },
  {
    id: "security",
    label: "Sicurezza",
    items: [
      { path: "/vulnerability", icon: ShieldCheck, label: "Vulnerability Assessment", roles: ["admin", "operator"] },
      { path: "/correlation", icon: Lightning, label: "SOC AI Correlation", roles: ["admin", "operator"] },
      { path: "/vault", icon: Lock, label: "Vault Credenziali", roles: ["admin"] },
      { path: "/security-dashboard", icon: ShieldCheck, label: "Security Dashboard", roles: ["admin"] },
      { path: "/enterprise", icon: Shield, label: "Audit & Compliance", roles: ["admin"] },
      { path: "/users", icon: Users, label: "Gestione Utenti", roles: ["admin"] },
    ],
  },
  {
    id: "system",
    label: "Sistema",
    items: [
      { path: "/tv", icon: Monitor, label: "TV Dashboard", roles: ["admin", "operator", "viewer"], external: true },
      { path: "/settings", icon: Gear, label: "Impostazioni", roles: ["admin", "operator"] },
      { path: "/thresholds", icon: Sliders, label: "Soglie Alert", roles: ["admin"] },
    ],
  },
];

const mobileNavItems = [
  { path: "/", icon: House, label: "Home" },
  { path: "/alerts", icon: Bell, label: "Alert", hasBadge: true },
  { path: "/network-status", icon: WifiHigh, label: "Rete" },
  { path: "/clients", icon: Buildings, label: "Clienti" },
  { path: "more", icon: DotsThreeOutline, label: "Menu" },
];

// ==================== COLLAPSE ANIMATION ====================
const collapseVariants = {
  open: { height: "auto", opacity: 1, transition: { duration: 0.25, ease: [0.16, 1, 0.3, 1] } },
  closed: { height: 0, opacity: 0, transition: { duration: 0.2, ease: [0.16, 1, 0.3, 1] } },
};

// ==================== NAV ITEM ====================
function NavItem({ item, alertCount, onNavigate }) {
  const isExternal = item.external;
  const badge = item.hasBadge ? alertCount : 0;

  const content = (
    <>
      <item.icon size={18} weight="regular" className="nav-icon flex-shrink-0" />
      <span className="nav-item-label">{item.label}</span>
      {badge > 0 && (
        <span className={`nav-badge ${badge > 10 ? "nav-badge-pulse" : ""}`} data-testid={`nav-badge-${item.label.toLowerCase()}`}>
          {badge > 99 ? "99+" : badge}
        </span>
      )}
      {isExternal && (
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginLeft: "auto", opacity: 0.3 }}>
          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3" />
        </svg>
      )}
    </>
  );

  if (isExternal) {
    return (
      <a
        href={item.path}
        target="_blank"
        rel="noopener noreferrer"
        className="nav-item"
        data-testid={`nav-item-${item.path.replace(/\//g, "").replace(/\s+/g, "-") || "home"}`}
      >
        {content}
      </a>
    );
  }

  return (
    <NavLink
      to={item.path}
      end={item.path === "/"}
      onClick={onNavigate}
      className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
      data-testid={`nav-item-${item.path.replace(/\//g, "").replace(/\s+/g, "-") || "home"}`}
    >
      {content}
    </NavLink>
  );
}

// ==================== NAV GROUP ====================
function NavGroup({ group, role, isOpen, onToggle, alertCount, onNavigate }) {
  const location = useLocation();
  const filteredItems = group.items.filter((i) => i.roles.includes(role));
  if (filteredItems.length === 0) return null;

  const hasActiveItem = filteredItems.some(
    (i) => (i.path === "/" ? location.pathname === "/" : location.pathname.startsWith(i.path))
  );

  return (
    <div className="nav-group" data-testid={`nav-group-${group.id}`}>
      <button
        className={`nav-group-header ${hasActiveItem ? "active-group" : ""}`}
        onClick={onToggle}
        data-testid={`nav-group-toggle-${group.id}`}
      >
        <span className="nav-group-label">{group.label}</span>
        <motion.div
          animate={{ rotate: isOpen ? 0 : -90 }}
          transition={{ duration: 0.2, ease: "easeOut" }}
          className="text-[var(--text-muted)]"
        >
          <CaretDown size={10} />
        </motion.div>
      </button>

      <AnimatePresence initial={false}>
        {isOpen && (
          <motion.div
            key={`group-${group.id}`}
            initial="closed"
            animate="open"
            exit="closed"
            variants={collapseVariants}
            style={{ overflow: "hidden" }}
          >
            <div className="nav-group-items">
              {filteredItems.map((item) => (
                <NavItem key={item.path} item={item} alertCount={alertCount} onNavigate={onNavigate} />
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ==================== MAIN LAYOUT ====================
export default function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(() => {
    if (typeof window !== "undefined") {
      return window.innerWidth < 768 || window.matchMedia("(max-width: 767px)").matches;
    }
    return false;
  });
  const [openGroups, setOpenGroups] = useState(() => {
    // All groups open by default
    const map = {};
    navConfig.forEach((g) => (map[g.id] = true));
    return map;
  });
  const [alertCount, setAlertCount] = useState(0);
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 767px)");
    const handler = (e) => setIsMobile(e.matches);
    mq.addEventListener("change", handler);
    setIsMobile(mq.matches);
    return () => mq.removeEventListener("change", handler);
  }, []);

  useEffect(() => {
    const fetchAlertCount = async () => {
      try {
        const res = await axios.get(`${API}/stats/summary`);
        setAlertCount(res.data.total_active || 0);
      } catch {}
    };
    fetchAlertCount();
    const interval = setInterval(fetchAlertCount, 30000);
    return () => clearInterval(interval);
  }, []);

  // Auto-open group containing active route
  useEffect(() => {
    navConfig.forEach((g) => {
      const hasActive = g.items.some(
        (i) => (i.path === "/" ? location.pathname === "/" : location.pathname.startsWith(i.path))
      );
      if (hasActive) {
        setOpenGroups((prev) => ({ ...prev, [g.id]: true }));
      }
    });
  }, [location.pathname]);

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  const closeSidebar = () => setSidebarOpen(false);
  const toggleGroup = (id) => setOpenGroups((prev) => ({ ...prev, [id]: !prev[id] }));
  const role = user?.role || "viewer";

  return (
    <div className={`main-layout ${isMobile ? "has-bottom-nav" : ""}`} data-testid="main-layout">
      {/* Overlay mobile */}
      <AnimatePresence>
        {sidebarOpen && isMobile && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="sidebar-overlay md:hidden"
            onClick={closeSidebar}
          />
        )}
      </AnimatePresence>

      {/* ==================== SIDEBAR ==================== */}
      <aside className={`sidebar ${sidebarOpen ? "open" : ""}`} data-testid="sidebar">
        {/* Header */}
        <div className="sidebar-header">
          <div className="flex items-center gap-2.5">
            <div className="sidebar-logo">
              <ShieldWarning size={16} weight="fill" />
            </div>
            <div className="flex flex-col">
              <span className="text-[13px] font-bold tracking-tight text-[var(--text-primary)] leading-tight">
                Argus
              </span>
              <span className="text-[9px] text-[var(--text-muted)] uppercase tracking-[0.12em] leading-tight font-mono">
                by 86BIT
              </span>
            </div>
          </div>
          <button
            className="md:hidden text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors p-1"
            onClick={closeSidebar}
            data-testid="sidebar-close-btn"
          >
            <X size={18} />
          </button>
        </div>

        {/* Navigation */}
        <nav className="sidebar-nav" data-testid="sidebar-nav">
          {navConfig.map((group) => (
            <NavGroup
              key={group.id}
              group={group}
              role={role}
              isOpen={openGroups[group.id]}
              onToggle={() => toggleGroup(group.id)}
              alertCount={alertCount}
              onNavigate={closeSidebar}
            />
          ))}
        </nav>

        {/* Footer / User */}
        <div className="sidebar-footer">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button className="sidebar-user-btn" data-testid="user-menu-btn">
                <div className="sidebar-user-avatar">
                  <User size={13} />
                </div>
                <div className="flex-1 text-left min-w-0">
                  <p className="text-xs text-[var(--text-primary)] truncate leading-tight">{user?.name}</p>
                  <p className="sidebar-user-role">{role}</p>
                </div>
                <CaretDown size={10} className="text-[var(--text-muted)]" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="end"
              className="w-44 bg-[var(--bg-panel)] border-[var(--bg-border)] rounded-lg"
            >
              <DropdownMenuItem
                onClick={handleLogout}
                className="text-red-400 focus:text-red-300 focus:bg-red-900/20 rounded-md cursor-pointer text-xs"
                data-testid="logout-btn"
              >
                <SignOut size={14} className="mr-2" />
                Logout
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </aside>

      {/* ==================== MAIN CONTENT ==================== */}
      <main className="main-content">
        <header className="md:hidden sticky top-0 z-30 bg-[var(--bg-app)]/95 backdrop-blur-md border-b border-[var(--bg-border)] p-3 flex items-center justify-between">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setSidebarOpen(true)}
            className="text-[var(--text-secondary)] h-8 w-8"
            data-testid="mobile-menu-btn"
          >
            <List size={20} />
          </Button>
          <div className="flex items-center gap-2">
            <ShieldWarning size={18} weight="fill" className="text-indigo-400" />
            <span className="font-bold text-sm text-[var(--text-primary)]">Argus</span>
          </div>
          <div className="w-8" />
        </header>
        <Outlet />
      </main>

      {/* ==================== MOBILE BOTTOM NAV ==================== */}
      {isMobile && (
        <nav className="mobile-bottom-nav" data-testid="mobile-bottom-nav">
          {mobileNavItems.map((item) => {
            if (item.path === "more") {
              return (
                <button
                  key="more"
                  onClick={() => setSidebarOpen(true)}
                  className={sidebarOpen ? "active" : ""}
                  data-testid="mobile-nav-menu"
                >
                  <item.icon size={20} weight="regular" />
                  <span>{item.label}</span>
                </button>
              );
            }
            const badge = item.hasBadge ? alertCount : 0;
            return (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.path === "/"}
                className={({ isActive }) => (isActive ? "active" : "")}
                data-testid={`mobile-nav-${item.label.toLowerCase()}`}
              >
                <item.icon size={20} weight="regular" />
                <span>{item.label}</span>
                {badge > 0 && (
                  <span className="mobile-nav-badge">{badge > 99 ? "99+" : badge}</span>
                )}
              </NavLink>
            );
          })}
        </nav>
      )}
    </div>
  );
}
