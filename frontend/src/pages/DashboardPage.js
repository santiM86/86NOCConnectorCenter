import { useState, useEffect, useRef } from "react";
import axios from "axios";
import { API } from "@/App";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { 
  Warning, 
  ShieldWarning, 
  Info, 
  CheckCircle,
  Pulse,
  HardDrives,
  Users,
  Clock
} from "@phosphor-icons/react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";

export default function DashboardPage() {
  const [stats, setStats] = useState({
    critical: 0,
    high: 0,
    medium: 0,
    low: 0,
    total_active: 0,
    total_clients: 0,
    total_devices: 0
  });
  const [trends, setTrends] = useState([]);
  const [recentAlerts, setRecentAlerts] = useState([]);
  const [syslogStream, setSyslogStream] = useState([]);
  const wsRef = useRef(null);
  const navigate = useNavigate();

  useEffect(() => {
    fetchData();
    connectWebSocket();

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  const fetchData = async () => {
    try {
      const [statsRes, trendsRes, alertsRes] = await Promise.all([
        axios.get(`${API}/stats/summary`),
        axios.get(`${API}/stats/trends?hours=24`),
        axios.get(`${API}/alerts?limit=20&status=active`)
      ]);
      
      setStats(statsRes.data);
      setTrends(trendsRes.data);
      setRecentAlerts(alertsRes.data);
      
      // Extract syslog-like entries from recent alerts
      const syslogEntries = alertsRes.data
        .filter(a => a.source_type === "syslog" || a.source_type === "snmp")
        .slice(0, 50)
        .map(a => ({
          id: a.id,
          timestamp: new Date(a.created_at).toLocaleTimeString(),
          ip: a.ip_address,
          message: a.message,
          severity: a.severity
        }));
      setSyslogStream(syslogEntries);
    } catch (error) {
      console.error("Error fetching data:", error);
    }
  };

  const connectWebSocket = () => {
    const wsUrl = process.env.REACT_APP_BACKEND_URL.replace("https://", "wss://").replace("http://", "ws://");
    wsRef.current = new WebSocket(`${wsUrl}/ws/alerts`);

    wsRef.current.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "new_alert") {
        setRecentAlerts(prev => [data.alert, ...prev.slice(0, 19)]);
        setStats(prev => ({
          ...prev,
          [data.alert.severity]: prev[data.alert.severity] + 1,
          total_active: prev.total_active + 1
        }));
        
        if (data.alert.source_type === "syslog" || data.alert.source_type === "snmp") {
          setSyslogStream(prev => [{
            id: data.alert.id,
            timestamp: new Date(data.alert.created_at).toLocaleTimeString(),
            ip: data.alert.ip_address,
            message: data.alert.message,
            severity: data.alert.severity
          }, ...prev.slice(0, 49)]);
        }
        
        if (data.alert.severity === "critical") {
          toast.error(`CRITICAL: ${data.alert.title}`, {
            description: `${data.alert.device_name} - ${data.alert.client_name}`
          });
        }
      }
    };

    wsRef.current.onclose = () => {
      setTimeout(connectWebSocket, 5000);
    };
  };

  const handleAcknowledge = async (alertId) => {
    try {
      await axios.patch(`${API}/alerts/${alertId}`, { status: "acknowledged" });
      setRecentAlerts(prev => prev.filter(a => a.id !== alertId));
      fetchData();
      toast.success("Alert acknowledged");
    } catch (error) {
      toast.error("Error acknowledging alert");
    }
  };

  const getSeverityColor = (severity) => {
    const colors = {
      critical: "#F87171",
      high: "#FBBF24",
      medium: "#60A5FA",
      low: "#4ADE80"
    };
    return colors[severity] || "#71717A";
  };

  const formatTrendHour = (hour) => {
    if (!hour) return "";
    return hour.split("T")[1]?.substring(0, 5) || "";
  };

  return (
    <div className="p-4 md:p-6 space-y-6" data-testid="dashboard-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-heading text-2xl font-bold text-zinc-100 tracking-tight">
            Dashboard
          </h1>
          <p className="text-zinc-500 text-sm mt-1">
            Monitoraggio alert in tempo reale
          </p>
        </div>
        <div className="live-indicator">
          <span className="live-dot"></span>
          <span className="font-mono uppercase tracking-wider">Live</span>
        </div>
      </div>

      {/* Metric Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          label="Critici"
          value={stats.critical}
          icon={<ShieldWarning size={20} weight="fill" />}
          color="critical"
          testId="metric-critical"
        />
        <MetricCard
          label="Alti"
          value={stats.high}
          icon={<Warning size={20} weight="fill" />}
          color="high"
          testId="metric-high"
        />
        <MetricCard
          label="Medi"
          value={stats.medium}
          icon={<Info size={20} weight="fill" />}
          color="medium"
          testId="metric-medium"
        />
        <MetricCard
          label="Bassi"
          value={stats.low}
          icon={<CheckCircle size={20} weight="fill" />}
          color="low"
          testId="metric-low"
        />
      </div>

      {/* Secondary Stats */}
      <div className="grid grid-cols-3 gap-4">
        <div className="noc-panel p-4 flex items-center gap-3">
          <Pulse size={24} className="text-zinc-500" />
          <div>
            <p className="text-zinc-500 text-xs uppercase tracking-wider">Alert Attivi</p>
            <p className="font-heading text-xl font-bold text-zinc-100">{stats.total_active}</p>
          </div>
        </div>
        <div className="noc-panel p-4 flex items-center gap-3">
          <Users size={24} className="text-zinc-500" />
          <div>
            <p className="text-zinc-500 text-xs uppercase tracking-wider">Clienti</p>
            <p className="font-heading text-xl font-bold text-zinc-100">{stats.total_clients}</p>
          </div>
        </div>
        <div className="noc-panel p-4 flex items-center gap-3">
          <HardDrives size={24} className="text-zinc-500" />
          <div>
            <p className="text-zinc-500 text-xs uppercase tracking-wider">Dispositivi</p>
            <p className="font-heading text-xl font-bold text-zinc-100">{stats.total_devices}</p>
          </div>
        </div>
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Alert Trends Chart */}
        <div className="lg:col-span-2 noc-panel p-4">
          <h3 className="font-heading text-sm font-medium text-zinc-400 uppercase tracking-wider mb-4">
            Trend Alert (24h)
          </h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={trends}>
                <CartesianGrid strokeDasharray="3 3" stroke="#27272A" />
                <XAxis 
                  dataKey="hour" 
                  tickFormatter={formatTrendHour}
                  stroke="#71717A"
                  fontSize={10}
                  fontFamily="JetBrains Mono"
                />
                <YAxis 
                  stroke="#71717A"
                  fontSize={10}
                  fontFamily="JetBrains Mono"
                />
                <Tooltip 
                  contentStyle={{
                    backgroundColor: "#0A0A0A",
                    border: "1px solid #27272A",
                    borderRadius: "2px",
                    fontFamily: "JetBrains Mono",
                    fontSize: "12px"
                  }}
                />
                <Line type="monotone" dataKey="critical" stroke="#F87171" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="high" stroke="#FBBF24" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="medium" stroke="#60A5FA" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="low" stroke="#4ADE80" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Syslog Stream */}
        <div className="noc-panel p-4">
          <h3 className="font-heading text-sm font-medium text-zinc-400 uppercase tracking-wider mb-4">
            Live Stream
          </h3>
          <ScrollArea className="h-64">
            <div className="syslog-stream h-full">
              {syslogStream.length === 0 ? (
                <p className="text-zinc-600 text-center py-8">
                  In attesa di messaggi...
                </p>
              ) : (
                syslogStream.map((entry, idx) => (
                  <div key={entry.id + idx} className="syslog-line">
                    <span className="syslog-timestamp">{entry.timestamp}</span>
                    {" "}
                    <span className="syslog-ip">{entry.ip}</span>
                    {" "}
                    <span style={{ color: getSeverityColor(entry.severity) }}>
                      {entry.message.substring(0, 80)}
                    </span>
                  </div>
                ))
              )}
            </div>
          </ScrollArea>
        </div>
      </div>

      {/* Recent Active Alerts */}
      <div className="noc-panel">
        <div className="p-4 border-b border-zinc-800 flex items-center justify-between">
          <h3 className="font-heading text-sm font-medium text-zinc-400 uppercase tracking-wider">
            Alert Attivi Non Confermati
          </h3>
          <Button 
            variant="ghost" 
            size="sm" 
            onClick={() => navigate("/alerts")}
            className="text-zinc-400 hover:text-zinc-100 rounded-sm"
            data-testid="view-all-alerts-btn"
          >
            Vedi Tutti
          </Button>
        </div>
        <div className="overflow-x-auto">
          <table className="alert-table" data-testid="recent-alerts-table">
            <thead>
              <tr>
                <th>Severità</th>
                <th>Titolo</th>
                <th>Dispositivo</th>
                <th>Cliente</th>
                <th>IP</th>
                <th>Ora</th>
                <th>Azioni</th>
              </tr>
            </thead>
            <tbody>
              {recentAlerts.length === 0 ? (
                <tr>
                  <td colSpan={7} className="text-center text-zinc-500 py-8">
                    Nessun alert attivo
                  </td>
                </tr>
              ) : (
                recentAlerts.slice(0, 10).map((alert) => (
                  <tr 
                    key={alert.id} 
                    className={alert.severity === "critical" ? "pulse-critical" : ""}
                    data-testid={`alert-row-${alert.severity}`}
                  >
                    <td>
                      <span className={`severity-badge severity-${alert.severity}`}>
                        {alert.severity}
                      </span>
                    </td>
                    <td 
                      className="cursor-pointer hover:text-zinc-100 transition-fast"
                      onClick={() => navigate(`/alerts/${alert.id}`)}
                    >
                      {alert.title}
                    </td>
                    <td className="font-mono text-zinc-400">{alert.device_name}</td>
                    <td>{alert.client_name}</td>
                    <td className="font-mono text-blue-400">{alert.ip_address}</td>
                    <td className="font-mono text-zinc-500 text-xs">
                      {new Date(alert.created_at).toLocaleTimeString()}
                    </td>
                    <td>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleAcknowledge(alert.id)}
                        className="rounded-sm text-xs h-7 border-zinc-700 hover:bg-zinc-800 hover:text-zinc-100"
                        data-testid={`ack-btn-${alert.id}`}
                      >
                        ACK
                      </Button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

const MetricCard = ({ label, value, icon, color, testId }) => {
  const colors = {
    critical: { text: "#F87171", bg: "rgba(248, 113, 113, 0.1)", border: "rgba(248, 113, 113, 0.2)" },
    high: { text: "#FBBF24", bg: "rgba(251, 191, 36, 0.1)", border: "rgba(251, 191, 36, 0.2)" },
    medium: { text: "#60A5FA", bg: "rgba(96, 165, 250, 0.1)", border: "rgba(96, 165, 250, 0.2)" },
    low: { text: "#4ADE80", bg: "rgba(74, 222, 128, 0.1)", border: "rgba(74, 222, 128, 0.2)" }
  };

  const colorSet = colors[color] || colors.low;

  return (
    <div 
      className="metric-card transition-fast hover:border-zinc-700"
      style={{ borderColor: colorSet.border }}
      data-testid={testId}
    >
      <div className="flex items-center justify-between mb-2">
        <span style={{ color: colorSet.text }}>{icon}</span>
        {value > 0 && color === "critical" && (
          <span className="live-dot" style={{ backgroundColor: colorSet.text }}></span>
        )}
      </div>
      <p className="metric-value" style={{ color: colorSet.text }}>{value}</p>
      <p className="metric-label">{label}</p>
    </div>
  );
};
