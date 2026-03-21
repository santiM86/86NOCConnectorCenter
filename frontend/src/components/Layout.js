import { useState } from "react";
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
  Gear
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
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  const navItems = [
    { path: "/", icon: ChartLineUp, label: "Dashboard" },
    { path: "/alerts", icon: Bell, label: "Alert" },
    { path: "/clients", icon: Buildings, label: "Clienti" },
    { path: "/devices", icon: HardDrives, label: "Dispositivi" },
    { path: "/settings", icon: Gear, label: "Impostazioni" },
  ];

  return (
    <div className="main-layout" data-testid="main-layout">
      {/* Mobile Overlay */}
      {sidebarOpen && (
        <div 
          className="sidebar-overlay md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside className={`sidebar ${sidebarOpen ? "open" : ""}`}>
        {/* Logo */}
        <div className="p-4 border-b border-zinc-800">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <ShieldWarning size={24} weight="fill" className="text-zinc-100" />
              <span className="font-heading text-lg font-bold tracking-tight text-zinc-100">
                NOC
              </span>
            </div>
            <button
              className="md:hidden text-zinc-400 hover:text-zinc-100"
              onClick={() => setSidebarOpen(false)}
            >
              <X size={20} />
            </button>
          </div>
          <p className="text-zinc-600 text-xs font-mono mt-1">COMMAND CENTER</p>
        </div>

        {/* Navigation */}
        <nav className="flex-1 py-4">
          {navItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === "/"}
              onClick={() => setSidebarOpen(false)}
              className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
              data-testid={`nav-${item.label.toLowerCase()}`}
            >
              <item.icon size={20} />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>

        {/* User Menu */}
        <div className="p-4 border-t border-zinc-800">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button 
                className="w-full flex items-center gap-3 p-2 rounded-sm hover:bg-zinc-800 transition-fast"
                data-testid="user-menu-btn"
              >
                <div className="w-8 h-8 rounded-sm bg-zinc-700 flex items-center justify-center">
                  <User size={16} className="text-zinc-300" />
                </div>
                <div className="flex-1 text-left">
                  <p className="text-sm text-zinc-200 truncate">{user?.name}</p>
                  <p className="text-xs text-zinc-500 uppercase tracking-wider">{user?.role}</p>
                </div>
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent 
              align="end" 
              className="w-48 bg-zinc-900 border-zinc-800 rounded-sm"
            >
              <DropdownMenuItem 
                onClick={handleLogout}
                className="text-red-400 focus:text-red-300 focus:bg-red-900/20 rounded-sm cursor-pointer"
                data-testid="logout-btn"
              >
                <SignOut size={16} className="mr-2" />
                Logout
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </aside>

      {/* Main Content */}
      <main className="main-content">
        {/* Mobile Header */}
        <header className="md:hidden sticky top-0 z-30 bg-[#050505] border-b border-zinc-800 p-4 flex items-center justify-between">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setSidebarOpen(true)}
            className="text-zinc-400"
            data-testid="mobile-menu-btn"
          >
            <List size={24} />
          </Button>
          <div className="flex items-center gap-2">
            <ShieldWarning size={20} weight="fill" className="text-zinc-100" />
            <span className="font-heading font-bold text-zinc-100">NOC</span>
          </div>
          <div className="w-10" /> {/* Spacer */}
        </header>

        {/* Page Content */}
        <Outlet />
      </main>
    </div>
  );
}
