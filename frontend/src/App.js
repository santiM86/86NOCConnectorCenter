import { useState, useEffect, createContext, useContext, lazy, Suspense } from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate, useNavigate, useLocation } from "react-router-dom";
import axios from "axios";
import { Toaster } from "@/components/ui/sonner";
import { toast } from "sonner";
import { PwaProvider } from "@/components/PwaProvider";
import { WebConsoleTabsProvider } from "@/components/WebConsoleTabs";
import { PwaInstallBanner, NotificationPermissionBanner, OfflineIndicator } from "@/components/PwaBanners";
import { UpdateBanner, VersionProvider } from "@/components/AppVersion";
import SecurityGuard from "@/components/SecurityGuard";

// Pages
import LoginPage from "@/pages/LoginPage";
import SharedConsolePage from "@/pages/SharedConsolePage";
import DashboardPage from "@/pages/DashboardPage";
import TwoFactorPage from "@/pages/TwoFactorPage";
import Layout from "@/components/Layout";

// Code-splitting: ogni pagina è un chunk separato caricato al primo accesso.
// lazyRetry: dopo un deploy i vecchi chunk non esistono più (ChunkLoadError) →
// ricarica la pagina una sola volta per prendere la build nuova.
const lazyRetry = (importer) => lazy(() =>
  importer().catch((err) => {
    const key = "argus_chunk_reload";
    if (!sessionStorage.getItem(key)) {
      sessionStorage.setItem(key, "1");
      window.location.reload();
      return new Promise(() => {});
    }
    sessionStorage.removeItem(key);
    throw err;
  }).then((m) => { sessionStorage.removeItem("argus_chunk_reload"); return m; })
);
const AlertsPage = lazyRetry(() => import("@/pages/AlertsPage"));
const AlertDetailPage = lazyRetry(() => import("@/pages/AlertDetailPage"));
const ClientsPage = lazyRetry(() => import("@/pages/ClientsPage"));
const DevicesPage = lazyRetry(() => import("@/pages/DevicesPage"));
const SettingsPage = lazyRetry(() => import("@/pages/SettingsPage"));
const IPAllowlistPage = lazyRetry(() => import("@/pages/IPAllowlistPage"));
const HornetsecuritySettingsPage = lazyRetry(() => import("@/pages/HornetsecuritySettingsPage"));
const DattoRmmSettingsPage = lazyRetry(() => import("@/pages/DattoRmmSettingsPage"));
const ZyxelNebulaSettingsPage = lazyRetry(() => import("@/pages/ZyxelNebulaSettingsPage"));
const NetworkPathDiagnosisPage = lazyRetry(() => import("@/pages/NetworkPathDiagnosisPage"));
const DiagnosisCatalogPage = lazyRetry(() => import("@/pages/DiagnosisCatalogPage"));
const EntityInventoryPage = lazyRetry(() => import("@/pages/EntityInventoryPage"));
const AlertEngineSettingsPage = lazyRetry(() => import("@/pages/AlertEngineSettingsPage"));
const FingerbankSettingsPage = lazyRetry(() => import("@/pages/FingerbankSettingsPage"));
const OutageSourcesSettingsPage = lazyRetry(() => import("@/pages/OutageSourcesSettingsPage"));
const EncryptionPage = lazyRetry(() => import("@/pages/EncryptionPage"));
const AuditPage = lazyRetry(() => import("@/pages/AuditPage"));
const TwoFactorSetupPage = lazyRetry(() => import("@/pages/TwoFactorSetupPage"));
const EnterprisePage = lazyRetry(() => import("@/pages/EnterprisePage"));
const AgentsPage = lazyRetry(() => import("@/pages/AgentsPage"));
const ServerMetricsPage = lazyRetry(() => import("@/pages/ServerMetricsPage"));
const ClientStatusPage = lazyRetry(() => import("@/pages/ClientStatusPage"));
const UsersPage = lazyRetry(() => import("@/pages/UsersPage"));
const PasskeysPage = lazyRetry(() => import("@/pages/PasskeysPage"));
const VaultPage = lazyRetry(() => import("@/pages/VaultPage"));
const ReportsPage = lazyRetry(() => import("@/pages/ReportsPage"));
const InventoryPage = lazyRetry(() => import("@/pages/InventoryPage"));
const IncidentsPage = lazyRetry(() => import("@/pages/IncidentsPage"));
const PortMonitorPage = lazyRetry(() => import("@/pages/PortMonitorPage"));
const SwitchPortsPage = lazyRetry(() => import("@/pages/SwitchPortsPage"));
const PrintersPage = lazyRetry(() => import("@/pages/PrintersPage"));
const PrinterDiscoveryPage = lazyRetry(() => import("@/pages/PrinterDiscoveryPage"));
const PublicDashboard = lazyRetry(() => import("@/pages/PublicDashboard"));
const TvDashboardPage = lazyRetry(() => import("@/pages/TvDashboardPage"));
const MobileConsolePage = lazyRetry(() => import("@/pages/MobileConsolePage"));
const MobileMonitorPage = lazyRetry(() => import("@/pages/MobileMonitorPage"));
const MobileAccessPage = lazyRetry(() => import("@/pages/MobileAccessPage"));
const VulnerabilityPage = lazyRetry(() => import("@/pages/VulnerabilityPage"));
const OsintPage = lazyRetry(() => import("@/pages/OsintPage"));
const RogueDevicesPage = lazyRetry(() => import("@/pages/RogueDevicesPage"));
const TrendPage = lazyRetry(() => import("@/pages/TrendPage"));
const DeviceMetricsPage = lazyRetry(() => import("@/pages/DeviceMetricsPage"));
const SyslogPage = lazyRetry(() => import("@/pages/SyslogPage"));
const TrapsPage = lazyRetry(() => import("@/pages/TrapsPage"));
const DiscoveryPage = lazyRetry(() => import("@/pages/DiscoveryPage"));
const LanScannerPage = lazyRetry(() => import("@/pages/LanScannerPage"));
const MaintenancePage = lazyRetry(() => import("@/pages/MaintenancePage"));
const CorrelationPage = lazyRetry(() => import("@/pages/CorrelationPage"));
const ThresholdsPage = lazyRetry(() => import("@/pages/ThresholdsPage"));
const TemperatureManagementPage = lazyRetry(() => import("@/pages/TemperatureManagementPage"));
const DiagnosisCertaintyPage = lazyRetry(() => import("@/pages/DiagnosisCertaintyPage"));
const BandwidthPage = lazyRetry(() => import("@/pages/BandwidthPage"));
const BackupPage = lazyRetry(() => import("@/pages/BackupPage"));
const ClientPortalPage = lazyRetry(() => import("@/pages/ClientPortalPage"));
const ClientOverviewPage = lazyRetry(() => import("@/pages/ClientOverviewPage"));
const OnCallPage = lazyRetry(() => import("@/pages/OnCallPage"));
const SecurityDashboardPage = lazyRetry(() => import("@/pages/SecurityDashboardPage"));
const CMDBPage = lazyRetry(() => import("@/pages/CMDBPage"));
const RunbooksPage = lazyRetry(() => import("@/pages/RunbooksPage"));
const DeviceProfilesPage = lazyRetry(() => import("@/pages/DeviceProfilesPage"));
const SLAPage = lazyRetry(() => import("@/pages/SLAPage"));
const RemediationPage = lazyRetry(() => import("@/pages/RemediationPage"));
const LifecyclePage = lazyRetry(() => import("@/pages/LifecyclePage"));
const IntelligencePage = lazyRetry(() => import("@/pages/IntelligencePage"));
const ChannelHealthPage = lazyRetry(() => import("@/pages/ChannelHealthPage"));
const CustomerPortalPage = lazyRetry(() => import("@/pages/CustomerPortalPage"));
const ExternalMonitorPage = lazyRetry(() => import("@/pages/ExternalMonitorPage"));

const PageLoader = () => (
  <div className="flex items-center justify-center h-[60vh]" data-testid="page-loader">
    <div className="w-6 h-6 rounded-full border-2 border-indigo-500/30 border-t-indigo-400 animate-spin" />
  </div>
);

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
      // 403 = token ristretto 2FA-pending (verifica o enrollment): NON fare
      // logout, altrimenti si cancella il token necessario a completare il 2FA.
      if (error.response?.status === 403) {
        setUser(null);
      } else {
        console.error("Auth error:", error);
        logout();
      }
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
    if (response.data.requires_2fa_setup) {
      return { requires_2fa_setup: true };
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
          <Suspense fallback={<PageLoader />}>
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
              <Route path="diagnosis-catalog" element={<DiagnosisCatalogPage />} />
              <Route path="cmdb-entities" element={<EntityInventoryPage />} />
              <Route path="enterprise" element={<EnterprisePage />} />
              <Route path="agents" element={<AgentsPage />} />
              <Route path="server-metrics" element={<ServerMetricsPage />} />
              <Route path="network-status" element={<ClientStatusPage />} />
              <Route path="users" element={<UsersPage />} />
              <Route path="passkeys" element={<PasskeysPage />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="settings/ip-allowlist" element={<IPAllowlistPage />} />
              <Route path="settings/hornetsecurity" element={<HornetsecuritySettingsPage />} />
              <Route path="settings/datto" element={<DattoRmmSettingsPage />} />
              <Route path="settings/zyxel" element={<ZyxelNebulaSettingsPage />} />
              <Route path="tools/path-trace" element={<NetworkPathDiagnosisPage />} />
              <Route path="settings/alert-engine" element={<AlertEngineSettingsPage />} />
              <Route path="settings/fingerbank" element={<FingerbankSettingsPage />} />
              <Route path="settings/outage-sources" element={<OutageSourcesSettingsPage />} />
              <Route path="settings/encryption" element={<EncryptionPage />} />
              <Route path="settings/audit" element={<AuditPage />} />
              <Route path="settings/mobile-access" element={<MobileAccessPage />} />
              <Route path="oncall" element={<OnCallPage />} />
              <Route path="vault" element={<VaultPage />} />
              <Route path="reports" element={<ReportsPage />} />
              <Route path="inventory" element={<InventoryPage />} />
              <Route path="incidents" element={<IncidentsPage />} />
              <Route path="port-monitor" element={<PortMonitorPage />} />
              <Route path="switch-ports/:deviceIp" element={<SwitchPortsPage />} />
              <Route path="printers" element={<PrintersPage />} />
              <Route path="clients/:clientId/printer-discovery" element={<PrinterDiscoveryPage />} />
              <Route path="vulnerability" element={<VulnerabilityPage />} />
              <Route path="osint" element={<OsintPage />} />
              <Route path="rogue-devices" element={<RogueDevicesPage />} />
              <Route path="trends" element={<TrendPage />} />
              <Route path="device-metrics" element={<DeviceMetricsPage />} />
              <Route path="syslog" element={<SyslogPage />} />
              <Route path="snmp-traps" element={<TrapsPage />} />
              <Route path="discovery" element={<DiscoveryPage />} />
              <Route path="lan-scanner" element={<LanScannerPage />} />
              <Route path="maintenance" element={<MaintenancePage />} />
              <Route path="correlation" element={<CorrelationPage />} />
              <Route path="thresholds" element={<ThresholdsPage />} />
              <Route path="temperature" element={<TemperatureManagementPage />} />
              <Route path="certainty" element={<DiagnosisCertaintyPage />} />
              <Route path="bandwidth" element={<BandwidthPage />} />
              <Route path="backup" element={<BackupPage />} />
              <Route path="security-dashboard" element={<SecurityDashboardPage />} />
              <Route path="wan-monitor" element={<ExternalMonitorPage />} />
              <Route path="cmdb" element={<CMDBPage />} />
              <Route path="runbooks" element={<RunbooksPage />} />
              <Route path="sla" element={<SLAPage />} />
              <Route path="remediation" element={<RemediationPage />} />
              <Route path="lifecycle" element={<LifecyclePage />} />
              <Route path="intelligence" element={<IntelligencePage />} />
              <Route path="channel-health" element={<ChannelHealthPage />} />
              <Route path="device-profiles" element={<DeviceProfilesPage />} />
            </Route>
            <Route path="/public/:token" element={<PublicDashboard />} />
            <Route path="/tv" element={<TvDashboardPage />} />
            <Route path="/m" element={<MobileMonitorPage />} />
            <Route path="/mobile" element={<ProtectedRoute><MobileConsolePage /></ProtectedRoute>} />
            <Route path="/portal" element={<ClientPortalPage />} />
            <Route path="/customer-portal" element={<CustomerPortalPage />} />
            <Route path="/2fa" element={<TwoFactorPage />} />
            <Route path="/2fa-setup" element={<TwoFactorSetupPage />} />
          </Routes>
          </Suspense>
          <SecurityGuard />
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
