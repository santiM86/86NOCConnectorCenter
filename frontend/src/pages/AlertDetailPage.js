import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { 
  ArrowLeft, 
  Clock, 
  HardDrive, 
  MapPin,
  User,
  CheckCircle,
  Warning
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export default function AlertDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [alert, setAlert] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchAlert();
  }, [id]);

  const fetchAlert = async () => {
    try {
      const response = await axios.get(`${API}/alerts/${id}`);
      setAlert(response.data);
    } catch (error) {
      toast.error("Alert non trovato");
      navigate("/alerts");
    } finally {
      setLoading(false);
    }
  };

  const handleAcknowledge = async () => {
    try {
      await axios.patch(`${API}/alerts/${id}`, { status: "acknowledged" });
      fetchAlert();
      toast.success("Alert confermato");
    } catch (error) {
      toast.error("Errore");
    }
  };

  const handleResolve = async () => {
    try {
      await axios.patch(`${API}/alerts/${id}`, { status: "resolved" });
      fetchAlert();
      toast.success("Alert risolto");
    } catch (error) {
      toast.error("Errore");
    }
  };

  if (loading) {
    return (
      <div className="p-6 flex items-center justify-center">
        <p className="text-zinc-500">Caricamento...</p>
      </div>
    );
  }

  if (!alert) {
    return null;
  }

  const severityColors = {
    critical: { text: "#F87171", bg: "rgba(248, 113, 113, 0.1)", border: "rgba(248, 113, 113, 0.3)" },
    high: { text: "#FBBF24", bg: "rgba(251, 191, 36, 0.1)", border: "rgba(251, 191, 36, 0.3)" },
    medium: { text: "#60A5FA", bg: "rgba(96, 165, 250, 0.1)", border: "rgba(96, 165, 250, 0.3)" },
    low: { text: "#4ADE80", bg: "rgba(74, 222, 128, 0.1)", border: "rgba(74, 222, 128, 0.3)" }
  };

  const colors = severityColors[alert.severity] || severityColors.low;

  return (
    <div className="p-4 md:p-6" data-testid="alert-detail-page">
      {/* Back Button */}
      <Button
        variant="ghost"
        size="sm"
        onClick={() => navigate("/alerts")}
        className="mb-4 text-zinc-400 hover:text-zinc-100 rounded-sm gap-2"
        data-testid="back-btn"
      >
        <ArrowLeft size={16} />
        Torna agli Alert
      </Button>

      {/* Two Pane Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left Pane - Metadata */}
        <div className="space-y-4">
          {/* Header Card */}
          <div 
            className="noc-panel p-6"
            style={{ borderColor: colors.border }}
          >
            {/* Severity Badge */}
            <div className="flex items-start justify-between mb-4">
              <span 
                className="severity-badge text-sm px-3 py-1"
                style={{ 
                  color: colors.text, 
                  backgroundColor: colors.bg,
                  borderColor: colors.border
                }}
              >
                {alert.severity.toUpperCase()}
              </span>
              <span 
                className={`text-xs uppercase tracking-wider status-${alert.status}`}
                data-testid="alert-status"
              >
                {alert.status}
              </span>
            </div>

            {/* Title */}
            <h1 
              className="font-heading text-xl font-bold text-zinc-100 mb-2"
              data-testid="alert-title"
            >
              {alert.title}
            </h1>

            {/* Message */}
            <p className="text-zinc-400 text-sm mb-6">
              {alert.message}
            </p>

            {/* Actions */}
            <div className="flex gap-2">
              {alert.status === "active" && (
                <Button
                  onClick={handleAcknowledge}
                  className="rounded-sm bg-zinc-800 hover:bg-zinc-700 text-zinc-100"
                  data-testid="ack-btn"
                >
                  <Warning size={16} className="mr-2" />
                  Conferma
                </Button>
              )}
              {alert.status !== "resolved" && (
                <Button
                  onClick={handleResolve}
                  variant="outline"
                  className="rounded-sm border-green-800 text-green-400 hover:bg-green-900/30"
                  data-testid="resolve-btn"
                >
                  <CheckCircle size={16} className="mr-2" />
                  Risolvi
                </Button>
              )}
            </div>
          </div>

          {/* Details Card */}
          <div className="noc-panel p-6">
            <h3 className="font-heading text-sm font-medium text-zinc-400 uppercase tracking-wider mb-4">
              Dettagli
            </h3>

            <div className="space-y-4">
              <DetailRow
                icon={<HardDrive size={18} />}
                label="Dispositivo"
                value={alert.device_name}
                subValue={alert.device_type?.toUpperCase()}
              />
              <DetailRow
                icon={<MapPin size={18} />}
                label="Indirizzo IP"
                value={alert.ip_address}
                mono
              />
              <DetailRow
                icon={<User size={18} />}
                label="Cliente"
                value={alert.client_name}
              />
              <DetailRow
                icon={<Clock size={18} />}
                label="Data/Ora"
                value={new Date(alert.created_at).toLocaleString("it-IT")}
                mono
              />
              {alert.acknowledged_at && (
                <DetailRow
                  icon={<CheckCircle size={18} />}
                  label="Confermato"
                  value={`${alert.acknowledged_by} - ${new Date(alert.acknowledged_at).toLocaleString("it-IT")}`}
                />
              )}
              {alert.resolved_at && (
                <DetailRow
                  icon={<CheckCircle size={18} />}
                  label="Risolto"
                  value={new Date(alert.resolved_at).toLocaleString("it-IT")}
                  mono
                />
              )}
            </div>
          </div>

          {/* Source Info */}
          <div className="noc-panel p-6">
            <h3 className="font-heading text-sm font-medium text-zinc-400 uppercase tracking-wider mb-4">
              Fonte
            </h3>
            <div className="flex items-center gap-3">
              <Badge 
                variant="outline" 
                className="rounded-sm border-zinc-700 text-zinc-300 uppercase"
              >
                {alert.source_type}
              </Badge>
              <span className="text-zinc-500 text-sm">
                Alert ID: <span className="font-mono text-zinc-400">{alert.id.substring(0, 8)}</span>
              </span>
            </div>
          </div>
        </div>

        {/* Right Pane - Raw Data */}
        <div className="noc-panel p-6">
          <h3 className="font-heading text-sm font-medium text-zinc-400 uppercase tracking-wider mb-4">
            Dati Grezzi ({alert.source_type.toUpperCase()})
          </h3>
          <div className="terminal-block rounded-sm" data-testid="raw-data-block">
            <pre className="text-green-400 text-xs leading-relaxed">
              <code>
                {alert.raw_data ? formatRawData(alert.raw_data) : "Nessun dato grezzo disponibile"}
              </code>
            </pre>
          </div>

          {/* Timestamp Footer */}
          <div className="mt-4 pt-4 border-t border-zinc-800">
            <p className="text-zinc-600 text-xs font-mono">
              Ultimo aggiornamento: {new Date().toLocaleString("it-IT")}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

const DetailRow = ({ icon, label, value, subValue, mono }) => (
  <div className="flex items-start gap-3">
    <span className="text-zinc-500 mt-0.5">{icon}</span>
    <div className="flex-1">
      <p className="text-zinc-500 text-xs uppercase tracking-wider mb-0.5">{label}</p>
      <p className={`text-zinc-200 ${mono ? "font-mono" : ""}`}>
        {value}
        {subValue && (
          <span className="ml-2 text-xs text-zinc-500 uppercase">{subValue}</span>
        )}
      </p>
    </div>
  </div>
);

const formatRawData = (rawData) => {
  try {
    const parsed = JSON.parse(rawData);
    return JSON.stringify(parsed, null, 2);
  } catch {
    return rawData;
  }
};
