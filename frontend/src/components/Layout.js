import { useState, useEffect } from "react";
import { Outlet, NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "@/App";
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
  FileText,
  Wrench,
  PlugsConnected,
  Users,
  Lock
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
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < 768);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  const navItems = [
    { path: "/", icon: ChartLineUp, label: "Dashboard" },
    { path: "/alerts", icon: Bell, label: "Alert" },
    { path: "/clients", icon: Buildings, label: "Clienti" },
    { path: "/devices", icon: HardDrives, label: "Dispositivi" },
    { path: "/connectors", icon: PlugsConnected, label: "Connettori" },
    { path: "/users", icon: Users, label: "Utenti" },
    { path: "/enterprise", icon: Wrench, label: "Enterprise" },
    { path: "/vault", icon: Lock, label: "Vault" },
    { path: "/settings", icon: Gear, label: "Impostazioni" },
  ];

  const mobileNavItems = [
    { path: "/", icon: ChartLineUp, label: "Home" },
    { path: "/alerts", icon: Bell, label: "Alert" },
    { path: "/clients", icon: Buildings, label: "Clienti" },
    { path: "/devices", icon: HardDrives, label: "Dispositivi" },
    { path: "/settings", icon: Gear, label: "Altro" },
  ];

  return (
    <div className={`main-layout ${isMobile ? "has-bottom-nav" : ""}`} data-testid="main-layout">
      {sidebarOpen && (
        <div 
          className="sidebar-overlay md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <aside className={`sidebar ${sidebarOpen ? "open" : ""}`}>
        <div className="p-3 border-b border-[var(--bg-border)]">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-md bg-indigo-600/20 flex items-center justify-center">
                <ShieldWarning size={16} weight="fill" className="text-indigo-400" />
              </div>
              <span className="font-heading text-sm font-bold tracking-tight text-[var(--text-primary)]">
                NOC Center
              </span>
            </div>
            <button
              className="md:hidden text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
              onClick={() => setSidebarOpen(false)}
            >
              <X size={18} />
            </button>
          </div>
        </div>

        <nav className="flex-1 py-2">
          {navItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === "/"}
              onClick={() => setSidebarOpen(false)}
              className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
              data-testid={`nav-${item.label.toLowerCase()}`}
            >
              <item.icon size={18} />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="p-3 border-t border-[var(--bg-border)]">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button 
                className="w-full flex items-center gap-2 p-2 rounded-md hover:bg-[var(--bg-hover)] transition-all duration-150"
                data-testid="user-menu-btn"
              >
                <div className="w-7 h-7 rounded-md bg-indigo-600/20 flex items-center justify-center">
                  <User size={14} className="text-indigo-400" />
                </div>
                <div className="flex-1 text-left min-w-0">
                  <p className="text-xs text-[var(--text-primary)] truncate">{user?.name}</p>
                  <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">{user?.role}</p>
                </div>
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
        <header className="md:hidden sticky top-0 z-30 bg-[var(--bg-app)] border-b border-[var(--bg-border)] p-3 flex items-center justify-between">
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
            <span className="font-heading font-bold text-sm text-[var(--text-primary)]">NOC</span>
          </div>
          <div className="w-8" />
        </header>
        <Outlet />
      </main>

      {isMobile && (
        <nav className="mobile-bottom-nav" data-testid="mobile-bottom-nav">
          {mobileNavItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === "/"}
              className={({ isActive }) => isActive ? "active" : ""}
              data-testid={`mobile-nav-${item.label.toLowerCase()}`}
            >
              <item.icon size={20} weight="regular" />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
      )}
    </div>
  );
}
