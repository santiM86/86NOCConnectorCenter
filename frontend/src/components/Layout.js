import { useState, useEffect } from "react";
import { Outlet, NavLink, useNavigate, useLocation } from "react-router-dom";
import { useAuth, API } from "@/App";
import axios from "axios";
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
  CaretRight,
  Pulse,
  Shield,
  House,
  DotsThreeOutline,
  WifiHigh
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export default function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(window.innerWidth < 768);
  const [collapsedGroups, setCollapsedGroups] = useState({});
  const [alertCount, setAlertCount] = useState(0);
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < 768);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
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

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  const toggleGroup = (group) => {
    setCollapsedGroups(prev => ({ ...prev, [group]: !prev[group] }));
  };

  const role = user?.role || "viewer";

  const navGroups = [
    {
      id: "monitoring",
      label: "Monitoraggio",
      items: [
        { path: "/", icon: ChartLineUp, label: "Dashboard", roles: ["admin", "operator", "viewer"] },
        { path: "/alerts", icon: Bell, label: "Alert", badge: alertCount, roles: ["admin", "operator", "viewer"] },
        { path: "/network-status", icon: WifiHigh, label: "Stato Rete", roles: ["admin", "operator", "viewer"] },
        { path: "/devices", icon: HardDrives, label: "Dispositivi", roles: ["admin", "operator", "viewer"] },
      ]
    },
    {
      id: "infrastructure",
      label: "Infrastruttura",
      items: [
        { path: "/clients", icon: Buildings, label: "Clienti", roles: ["admin", "operator", "viewer"] },
        { path: "/connectors", icon: PlugsConnected, label: "Connettori", roles: ["admin", "operator"] },
      ]
    },
    {
      id: "security",
      label: "Sicurezza",
      items: [
        { path: "/vault", icon: Lock, label: "Vault Credenziali", roles: ["admin"] },
        { path: "/enterprise", icon: Shield, label: "Audit & Compliance", roles: ["admin"] },
        { path: "/users", icon: Users, label: "Gestione Utenti", roles: ["admin"] },
      ]
    },
    {
      id: "system",
      label: "Sistema",
      items: [
        { path: "/settings", icon: Gear, label: "Impostazioni", roles: ["admin", "operator"] },
      ]
    },
  ];

  const filteredGroups = navGroups
    .map(g => ({ ...g, items: g.items.filter(i => i.roles.includes(role)) }))
    .filter(g => g.items.length > 0);

  const mobileNavItems = [
    { path: "/", icon: House, label: "Home" },
    { path: "/alerts", icon: Bell, label: "Alert", badge: alertCount },
    { path: "/network-status", icon: WifiHigh, label: "Rete" },
    { path: "/clients", icon: Buildings, label: "Clienti" },
    { path: "more", icon: DotsThreeOutline, label: "Menu" },
  ];

  return (
    <div className={`main-layout ${isMobile ? "has-bottom-nav" : ""}`} data-testid="main-layout">
      {sidebarOpen && (
        <div className="sidebar-overlay md:hidden" onClick={() => setSidebarOpen(false)} />
      )}

      <aside className={`sidebar ${sidebarOpen ? "open" : ""}`} data-testid="sidebar">
        <div className="sidebar-header">
          <div className="flex items-center gap-2.5">
            <div className="sidebar-logo">
              <ShieldWarning size={16} weight="fill" />
            </div>
            <div className="flex flex-col">
              <span className="font-heading text-[13px] font-bold tracking-tight text-[var(--text-primary)] leading-tight">
                NOC Center
              </span>
              <span className="text-[9px] text-[var(--text-muted)] uppercase tracking-[0.12em] leading-tight">
                86BIT Command
              </span>
            </div>
          </div>
          <button
            className="md:hidden text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
            onClick={() => setSidebarOpen(false)}
          >
            <X size={18} />
          </button>
        </div>

        <nav className="sidebar-nav" data-testid="sidebar-nav">
          {filteredGroups.map((group) => {
            const isCollapsed = collapsedGroups[group.id];
            const isActiveGroup = group.items.some(
              i => i.path === "/" ? location.pathname === "/" : location.pathname.startsWith(i.path)
            );

            return (
              <div key={group.id} className="nav-group" data-testid={`nav-group-${group.id}`}>
                <button
                  className={`nav-group-header ${isActiveGroup ? "active-group" : ""}`}
                  onClick={() => toggleGroup(group.id)}
                  data-testid={`nav-group-toggle-${group.id}`}
                >
                  <span className="nav-group-label">{group.label}</span>
                  {isCollapsed ? <CaretRight size={10} /> : <CaretDown size={10} />}
                </button>

                {!isCollapsed && (
                  <div className="nav-group-items">
                    {group.items.map((item) => (
                      <NavLink
                        key={item.path}
                        to={item.path}
                        end={item.path === "/"}
                        onClick={() => setSidebarOpen(false)}
                        className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
                        data-testid={`nav-${item.label.toLowerCase().replace(/\s+/g, '-')}`}
                      >
                        <item.icon size={16} weight="regular" />
                        <span className="nav-item-label">{item.label}</span>
                        {item.badge > 0 && (
                          <span className="nav-badge" data-testid={`nav-badge-${item.label.toLowerCase()}`}>
                            {item.badge > 99 ? "99+" : item.badge}
                          </span>
                        )}
                      </NavLink>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </nav>

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

      <main className="main-content">
        <header className="md:hidden sticky top-0 z-30 bg-[var(--bg-app)]/95 backdrop-blur-md border-b border-[var(--bg-border)] p-3 flex items-center justify-between">
          <Button
            variant="ghost" size="icon"
            onClick={() => setSidebarOpen(true)}
            className="text-[var(--text-secondary)] h-8 w-8"
            data-testid="mobile-menu-btn"
          >
            <List size={20} />
          </Button>
          <div className="flex items-center gap-2">
            <ShieldWarning size={18} weight="fill" className="text-indigo-400" />
            <span className="font-heading font-bold text-sm text-[var(--text-primary)]">NOC</span>
          </div>
          <div className="w-8" />
        </header>
        <Outlet />
      </main>

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
            return (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.path === "/"}
                className={({ isActive }) => isActive ? "active" : ""}
                data-testid={`mobile-nav-${item.label.toLowerCase()}`}
              >
                <item.icon size={20} weight="regular" />
                <span>{item.label}</span>
                {item.badge > 0 && (
                  <span className="mobile-nav-badge">{item.badge > 99 ? "99+" : item.badge}</span>
                )}
              </NavLink>
            );
          })}
        </nav>
      )}
    </div>
  );
}
