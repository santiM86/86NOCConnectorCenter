import React, { useState, useEffect, useRef } from 'react';
import {
  View,
  Text,
  ScrollView,
  StyleSheet,
  RefreshControl,
  TouchableOpacity,
} from 'react-native';
import axios from 'axios';
import { useAuth } from '../App';

export default function DashboardScreen({ navigation }) {
  const { API_BASE_URL } = useAuth();
  const [stats, setStats] = useState({
    critical: 0,
    high: 0,
    medium: 0,
    low: 0,
    total_active: 0,
    total_clients: 0,
    total_devices: 0,
  });
  const [recentAlerts, setRecentAlerts] = useState([]);
  const [refreshing, setRefreshing] = useState(false);
  const wsRef = useRef(null);

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
      const [statsRes, alertsRes] = await Promise.all([
        axios.get(`${API_BASE_URL}/stats/summary`),
        axios.get(`${API_BASE_URL}/alerts?limit=10&status=active`),
      ]);
      setStats(statsRes.data);
      setRecentAlerts(alertsRes.data);
    } catch (error) {
      console.error('Error fetching data:', error);
    }
  };

  const connectWebSocket = () => {
    const wsUrl = API_BASE_URL.replace('https://', 'wss://').replace('http://', 'ws://').replace('/api', '');
    wsRef.current = new WebSocket(`${wsUrl}/ws/alerts`);

    wsRef.current.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'new_alert') {
        setRecentAlerts((prev) => [data.alert, ...prev.slice(0, 9)]);
        setStats((prev) => ({
          ...prev,
          [data.alert.severity]: prev[data.alert.severity] + 1,
          total_active: prev.total_active + 1,
        }));
      }
    };

    wsRef.current.onclose = () => {
      setTimeout(connectWebSocket, 5000);
    };
  };

  const onRefresh = async () => {
    setRefreshing(true);
    await fetchData();
    setRefreshing(false);
  };

  const handleAcknowledge = async (alertId) => {
    try {
      await axios.patch(`${API_BASE_URL}/alerts/${alertId}`, { status: 'acknowledged' });
      fetchData();
    } catch (error) {
      console.error('Error acknowledging alert:', error);
    }
  };

  return (
    <ScrollView
      style={styles.container}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#FAFAFA" />
      }
    >
      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.title}>Dashboard</Text>
        <View style={styles.liveIndicator}>
          <View style={styles.liveDot} />
          <Text style={styles.liveText}>LIVE</Text>
        </View>
      </View>

      {/* Metric Cards */}
      <View style={styles.metricsGrid}>
        <MetricCard label="Critici" value={stats.critical} color="#F87171" />
        <MetricCard label="Alti" value={stats.high} color="#FBBF24" />
        <MetricCard label="Medi" value={stats.medium} color="#60A5FA" />
        <MetricCard label="Bassi" value={stats.low} color="#4ADE80" />
      </View>

      {/* Summary Stats */}
      <View style={styles.summaryRow}>
        <StatBox label="Alert Attivi" value={stats.total_active} />
        <StatBox label="Clienti" value={stats.total_clients} />
        <StatBox label="Dispositivi" value={stats.total_devices} />
      </View>

      {/* Recent Alerts */}
      <View style={styles.section}>
        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>ALERT ATTIVI</Text>
          <TouchableOpacity onPress={() => navigation.navigate('Alerts')}>
            <Text style={styles.viewAll}>Vedi tutti</Text>
          </TouchableOpacity>
        </View>

        {recentAlerts.length === 0 ? (
          <View style={styles.emptyState}>
            <Text style={styles.emptyText}>Nessun alert attivo</Text>
          </View>
        ) : (
          recentAlerts.map((alert) => (
            <AlertCard
              key={alert.id}
              alert={alert}
              onAcknowledge={() => handleAcknowledge(alert.id)}
              onPress={() => navigation.navigate('Alerts', {
                screen: 'AlertDetail',
                params: { alertId: alert.id }
              })}
            />
          ))
        )}
      </View>
    </ScrollView>
  );
}

// Components
const MetricCard = ({ label, value, color }) => (
  <View style={[styles.metricCard, { borderColor: color + '33' }]}>
    <Text style={[styles.metricValue, { color }]}>{value}</Text>
    <Text style={styles.metricLabel}>{label}</Text>
  </View>
);

const StatBox = ({ label, value }) => (
  <View style={styles.statBox}>
    <Text style={styles.statValue}>{value}</Text>
    <Text style={styles.statLabel}>{label}</Text>
  </View>
);

const AlertCard = ({ alert, onAcknowledge, onPress }) => {
  const severityColors = {
    critical: '#F87171',
    high: '#FBBF24',
    medium: '#60A5FA',
    low: '#4ADE80',
  };
  const color = severityColors[alert.severity] || '#71717A';

  return (
    <TouchableOpacity style={styles.alertCard} onPress={onPress}>
      <View style={styles.alertHeader}>
        <View style={[styles.severityBadge, { backgroundColor: color + '20', borderColor: color + '40' }]}>
          <Text style={[styles.severityText, { color }]}>
            {alert.severity.toUpperCase()}
          </Text>
        </View>
        <Text style={styles.alertTime}>
          {new Date(alert.created_at).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })}
        </Text>
      </View>
      <Text style={styles.alertTitle} numberOfLines={1}>{alert.title}</Text>
      <Text style={styles.alertDevice}>{alert.device_name} • {alert.client_name}</Text>
      
      <TouchableOpacity style={styles.ackButton} onPress={onAcknowledge}>
        <Text style={styles.ackButtonText}>ACK</Text>
      </TouchableOpacity>
    </TouchableOpacity>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#050505',
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 16,
    paddingTop: 8,
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#FAFAFA',
  },
  liveIndicator: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  liveDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: '#4ADE80',
    marginRight: 6,
  },
  liveText: {
    fontSize: 11,
    color: '#4ADE80',
    fontWeight: '600',
    letterSpacing: 1,
  },
  metricsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    padding: 8,
  },
  metricCard: {
    width: '48%',
    margin: '1%',
    backgroundColor: '#0A0A0A',
    borderWidth: 1,
    padding: 16,
    borderRadius: 2,
  },
  metricValue: {
    fontSize: 36,
    fontWeight: 'bold',
  },
  metricLabel: {
    fontSize: 11,
    color: '#71717A',
    marginTop: 4,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  summaryRow: {
    flexDirection: 'row',
    padding: 8,
    marginBottom: 8,
  },
  statBox: {
    flex: 1,
    backgroundColor: '#0A0A0A',
    borderWidth: 1,
    borderColor: '#27272A',
    margin: 4,
    padding: 12,
    borderRadius: 2,
    alignItems: 'center',
  },
  statValue: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#FAFAFA',
  },
  statLabel: {
    fontSize: 10,
    color: '#71717A',
    marginTop: 2,
    textTransform: 'uppercase',
  },
  section: {
    padding: 16,
  },
  sectionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  sectionTitle: {
    fontSize: 12,
    color: '#A1A1AA',
    letterSpacing: 1,
  },
  viewAll: {
    fontSize: 12,
    color: '#71717A',
  },
  emptyState: {
    backgroundColor: '#0A0A0A',
    borderWidth: 1,
    borderColor: '#27272A',
    padding: 32,
    borderRadius: 2,
    alignItems: 'center',
  },
  emptyText: {
    color: '#71717A',
    fontSize: 14,
  },
  alertCard: {
    backgroundColor: '#0A0A0A',
    borderWidth: 1,
    borderColor: '#27272A',
    padding: 12,
    borderRadius: 2,
    marginBottom: 8,
  },
  alertHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  severityBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 2,
    borderWidth: 1,
  },
  severityText: {
    fontSize: 10,
    fontWeight: '600',
    letterSpacing: 0.5,
  },
  alertTime: {
    fontSize: 11,
    color: '#71717A',
    fontFamily: 'monospace',
  },
  alertTitle: {
    fontSize: 14,
    color: '#FAFAFA',
    marginBottom: 4,
  },
  alertDevice: {
    fontSize: 12,
    color: '#71717A',
    marginBottom: 12,
  },
  ackButton: {
    backgroundColor: '#27272A',
    paddingVertical: 8,
    borderRadius: 2,
    alignItems: 'center',
  },
  ackButtonText: {
    color: '#FAFAFA',
    fontSize: 12,
    fontWeight: '600',
    letterSpacing: 1,
  },
});
