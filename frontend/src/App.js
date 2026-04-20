import { useState, useEffect, createContext, useContext } from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate, useNavigate, useLocation } from "react-router-dom";
import axios from "axios";
import { Toaster } from "@/components/ui/sonner";
import { toast } from "sonner";
import { PwaProvider } from "@/components/PwaProvider";
import { WebConsoleTabsProvider } from "@/components/WebConsoleTabs";
import { PwaInstallBanner, NotificationPermissionBanner, OfflineIndicator } from "@/components/PwaBanners";
import { UpdateBanner, VersionProvider } from "@/components/AppVersion";

// Pages
import LoginPage from "@/pages/LoginPage";
import SharedConsolePage from "@/pages/SharedConsolePage";
import DashboardPage from "@/pages/DashboardPage";
import AlertsPage from "@/pages/AlertsPage";
import AlertDetailPage from "@/pages/AlertDetailPage";
import ClientsPage from "@/pages/ClientsPage";
import DevicesPage from "@/pages/DevicesPage";
import SettingsPage from "@/pages/SettingsPage";
import TwoFactorPage from "@/pages/TwoFactorPage";
import EnterprisePage from "@/pages/EnterprisePage";
import ConnectorsPage from "@/pages/ConnectorsPage";
import ClientStatusPage from "@/pages/ClientStatusPage";
import UsersPage from "@/pages/UsersPage";
import VaultPage from "@/pages/VaultPage";
import ReportsPage from "@/pages/ReportsPage";
import InventoryPage from "@/pages/InventoryPage";
import IncidentsPage from "@/pages/IncidentsPage";
import PortMonitorPage from "@/pages/PortMonitorPage";
import PrintersPage from "@/pages/PrintersPage";
import PublicDashboard from "@/pages/PublicDashboard";
import TvDashboardPage from "@/pages/TvDashboardPage";
import VulnerabilityPage from "@/pages/VulnerabilityPage";
import TrendPage from "@/pages/TrendPage";
import DiscoveryPage from "@/pages/DiscoveryPage";
import MaintenancePage from "@/pages/MaintenancePage";
import CorrelationPage from "@/pages/CorrelationPage";
import ThresholdsPage from "@/pages/ThresholdsPage";
import BandwidthPage from "@/pages/BandwidthPage";
import BackupPage from "@/pages/BackupPage";
import ClientPortalPage from "@/pages/ClientPortalPage";
import ClientOverviewPage from "@/pages/ClientOverviewPage";
import OnCallPage from "@/pages/OnCallPage";
import SecurityDashboardPage from "@/pages/SecurityDashboardPage";
import ExternalMonitorPage from "@/pages/ExternalMonitorPage";
import Layout from "@/components/Layout";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

// Auth Context
const AuthContext = createContext(null);

export const useAuth = () => useContext(AuthContext);

const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(localStorage.getItem("noc_token"));
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (token) {
      axios.defaults.headers.common["Authorization"] = `Bearer ${token}`;
      fetchUser();
    } else {
      setLoading(false);
    }
  }, [token]);

  const fetchUser = async () => {
    try {
      const response = await axios.get(`${API}/auth/me`);
      setUser(response.data);
    } catch (error) {
      console.error("Auth error:", error);
      logout();
    } finally {
      setLoading(false);
    }
  };

  const login = async (email, password) => {
    const response = await axios.post(`${API}/auth/login`, { email, password });
    const { token: newToken, refresh_token, user: userData, requires_2fa } = response.data;
    localStorage.setItem("noc_token", newToken);
    if (refresh_token) localStorage.setItem("noc_refresh_token", refresh_token);
    setToken(newToken);
    axios.defaults.headers.common["Authorization"] = `Bearer ${newToken}`;
    
    if (requires_2fa) {
      return { requires_2fa: true };
    }
    
    setUser(userData);
    return userData;
  };

  const register = async (email, password, name) => {
    const response = await axios.post(`${API}/auth/register`, { email, password, name });
    const { token: newToken, user: userData } = response.data;
    localStorage.setItem("noc_token", newToken);
    setToken(newToken);
    setUser(userData);
    axios.defaults.headers.common["Authorization"] = `Bearer ${newToken}`;
    return userData;
  };

  const logout = async () => {
    try {
      await axios.post(`${API}/auth/logout`);
    } catch {}
    localStorage.removeItem("noc_token");
    localStorage.removeItem("noc_refresh_token");
    setToken(null);
    setUser(null);
    delete axios.defaults.headers.common["Authorization"];
  };

  // Axios interceptor for automatic token refresh
  useEffect(() => {
    const interceptor = axios.interceptors.response.use(
      (res) => res,
      async (error) => {
        const originalRequest = error.config;
        if (error.response?.status === 401 && !originalRequest._retry && !originalRequest.url?.includes("/auth/")) {
          originalRequest._retry = true;
          const refreshToken = localStorage.getItem("noc_refresh_token");
          if (refreshToken) {
            try {
              const res = await axios.post(`${API}/auth/refresh`, { refresh_token: refreshToken });
              const { token: newToken, refresh_token: newRefresh } = res.data;
              localStorage.setItem("noc_token", newToken);
              if (newRefresh) localStorage.setItem("noc_refresh_token", newRefresh);
              setToken(newToken);
              axios.defaults.headers.common["Authorization"] = `Bearer ${newToken}`;
              originalRequest.headers["Authorization"] = `Bearer ${newToken}`;
              return axios(originalRequest);
            } catch {
              logout();
            }
          } else {
            logout();
          }
        }
        return Promise.reject(error);
      }
    );
    return () => axios.interceptors.response.eject(interceptor);
  }, []);

  return (
    <AuthContext.Provider value={{ user, token, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

// Protected Route
const ProtectedRoute = ({ children }) => {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-[#050505]">
        <div className="text-zinc-400">Loading...</div>
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return children;
};

function App() {
  return (
    <div className="App">
      <AuthProvider>
        <VersionProvider>
        <PwaProvider>
        <WebConsoleTabsProvider>
        <BrowserRouter>
          <OfflineIndicator />
          <UpdateBanner />
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/shared-console/:token" element={<SharedConsolePage />} />
            <Route
              path="/"
              element={
                <ProtectedRoute>
                  <Layout />
                </ProtectedRoute>
              }
            >
              <Route index element={<DashboardPage />} />
              <Route path="alerts" element={<AlertsPage />} />
              <Route path="alerts/:id" element={<AlertDetailPage />} />
              <Route path="clients" element={<ClientsPage />} />
              <Route path="client/:clientId" element={<ClientOverviewPage />} />
              <Route path="devices" element={<DevicesPage />} />
              <Route path="enterprise" element={<EnterprisePage />} />
              <Route path="connectors" element={<ConnectorsPage />} />
              <Route path="network-status" element={<ClientStatusPage />} />
              <Route path="users" element={<UsersPage />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="oncall" element={<OnCallPage />} />
              <Route path="vault" element={<VaultPage />} />
              <Route path="reports" element={<ReportsPage />} />
              <Route path="inventory" element={<InventoryPage />} />
              <Route path="incidents" element={<IncidentsPage />} />
              <Route path="port-monitor" element={<PortMonitorPage />} />
              <Route path="printers" element={<PrintersPage />} />
              <Route path="vulnerability" element={<VulnerabilityPage />} />
              <Route path="trends" element={<TrendPage />} />
              <Route path="discovery" element={<DiscoveryPage />} />
              <Route path="maintenance" element={<MaintenancePage />} />
              <Route path="correlation" element={<CorrelationPage />} />
              <Route path="thresholds" element={<ThresholdsPage />} />
              <Route path="bandwidth" element={<BandwidthPage />} />
              <Route path="backup" element={<BackupPage />} />
              <Route path="security-dashboard" element={<SecurityDashboardPage />} />
              <Route path="wan-monitor" element={<ExternalMonitorPage />} />
            </Route>
            <Route path="/public/:token" element={<PublicDashboard />} />
            <Route path="/tv" element={<TvDashboardPage />} />
            <Route path="/portal" element={<ClientPortalPage />} />
            <Route path="/2fa" element={<TwoFactorPage />} />
          </Routes>
          <PwaInstallBanner />
          <NotificationPermissionBanner />
        </BrowserRouter>
        <Toaster position="top-right" theme="dark" />
        </WebConsoleTabsProvider>
        </PwaProvider>
        </VersionProvider>
      </AuthProvider>
    </div>
  );
}

export default App;
