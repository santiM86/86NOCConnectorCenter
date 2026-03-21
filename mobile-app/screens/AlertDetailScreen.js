import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  ScrollView,
  StyleSheet,
  TouchableOpacity,
  Alert,
} from 'react-native';
import axios from 'axios';
import { useAuth } from '../App';

export default function AlertDetailScreen({ route, navigation }) {
  const { alertId } = route.params;
  const { API_BASE_URL } = useAuth();
  const [alert, setAlert] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchAlert();
  }, [alertId]);

  const fetchAlert = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/alerts/${alertId}`);
      setAlert(response.data);
    } catch (error) {
      Alert.alert('Errore', 'Alert non trovato');
      navigation.goBack();
    } finally {
      setLoading(false);
    }
  };

  const handleAcknowledge = async () => {
    try {
      await axios.patch(`${API_BASE_URL}/alerts/${alertId}`, { status: 'acknowledged' });
      fetchAlert();
    } catch (error) {
      Alert.alert('Errore', 'Impossibile confermare alert');
    }
  };

  const handleResolve = async () => {
    try {
      await axios.patch(`${API_BASE_URL}/alerts/${alertId}`, { status: 'resolved' });
      fetchAlert();
    } catch (error) {
      Alert.alert('Errore', 'Impossibile risolvere alert');
    }
  };

  if (loading || !alert) {
    return (
      <View style={styles.loadingContainer}>
        <Text style={styles.loadingText}>Caricamento...</Text>
      </View>
    );
  }

  const severityColors = {
    critical: '#F87171',
    high: '#FBBF24',
    medium: '#60A5FA',
    low: '#4ADE80',
  };
  const color = severityColors[alert.severity] || '#71717A';

  return (
    <ScrollView style={styles.container}>
      {/* Header Card */}
      <View style={[styles.headerCard, { borderColor: color + '40' }]}>
        <View style={styles.headerTop}>
          <View style={[styles.severityBadge, { backgroundColor: color + '20', borderColor: color + '40' }]}>
            <Text style={[styles.severityText, { color }]}>
              {alert.severity.toUpperCase()}
            </Text>
          </View>
          <Text style={[styles.statusText, { 
            color: alert.status === 'active' ? '#F87171' : 
                   alert.status === 'acknowledged' ? '#FBBF24' : '#4ADE80' 
          }]}>
            {alert.status.toUpperCase()}
          </Text>
        </View>

        <Text style={styles.title}>{alert.title}</Text>
        <Text style={styles.message}>{alert.message}</Text>

        {/* Actions */}
        <View style={styles.actions}>
          {alert.status === 'active' && (
            <TouchableOpacity style={styles.actionBtn} onPress={handleAcknowledge}>
              <Text style={styles.actionText}>CONFERMA</Text>
            </TouchableOpacity>
          )}
          {alert.status !== 'resolved' && (
            <TouchableOpacity 
              style={[styles.actionBtn, styles.resolveBtn]} 
              onPress={handleResolve}
            >
              <Text style={[styles.actionText, styles.resolveText]}>RISOLVI</Text>
            </TouchableOpacity>
          )}
        </View>
      </View>

      {/* Details Card */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>DETTAGLI</Text>
        
        <DetailRow label="Dispositivo" value={alert.device_name} />
        <DetailRow label="Tipo" value={alert.device_type?.toUpperCase()} />
        <DetailRow label="IP" value={alert.ip_address} mono />
        <DetailRow label="Cliente" value={alert.client_name} />
        <DetailRow label="Fonte" value={alert.source_type?.toUpperCase()} />
        <DetailRow label="Data/Ora" value={new Date(alert.created_at).toLocaleString('it-IT')} />
        
        {alert.acknowledged_at && (
          <DetailRow 
            label="Confermato" 
            value={`${alert.acknowledged_by} - ${new Date(alert.acknowledged_at).toLocaleString('it-IT')}`} 
          />
        )}
        {alert.resolved_at && (
          <DetailRow 
            label="Risolto" 
            value={new Date(alert.resolved_at).toLocaleString('it-IT')} 
          />
        )}
      </View>

      {/* Raw Data Card */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>DATI GREZZI ({alert.source_type?.toUpperCase()})</Text>
        <View style={styles.codeBlock}>
          <Text style={styles.codeText}>
            {alert.raw_data ? formatRawData(alert.raw_data) : 'Nessun dato grezzo disponibile'}
          </Text>
        </View>
      </View>
    </ScrollView>
  );
}

const DetailRow = ({ label, value, mono }) => (
  <View style={styles.detailRow}>
    <Text style={styles.detailLabel}>{label}</Text>
    <Text style={[styles.detailValue, mono && styles.monoText]}>{value}</Text>
  </View>
);

const formatRawData = (rawData) => {
  try {
    const parsed = JSON.parse(rawData);
    return JSON.stringify(parsed, null, 2);
  } catch {
    return rawData;
  }
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#050505',
  },
  loadingContainer: {
    flex: 1,
    backgroundColor: '#050505',
    justifyContent: 'center',
    alignItems: 'center',
  },
  loadingText: {
    color: '#71717A',
    fontSize: 14,
  },
  headerCard: {
    backgroundColor: '#0A0A0A',
    borderWidth: 1,
    margin: 16,
    padding: 16,
    borderRadius: 2,
  },
  headerTop: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  severityBadge: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 2,
    borderWidth: 1,
  },
  severityText: {
    fontSize: 12,
    fontWeight: '600',
    letterSpacing: 0.5,
  },
  statusText: {
    fontSize: 11,
    fontWeight: '500',
    letterSpacing: 0.5,
  },
  title: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#FAFAFA',
    marginBottom: 8,
  },
  message: {
    fontSize: 14,
    color: '#A1A1AA',
    lineHeight: 20,
    marginBottom: 16,
  },
  actions: {
    flexDirection: 'row',
    borderTopWidth: 1,
    borderTopColor: '#27272A',
    paddingTop: 16,
  },
  actionBtn: {
    flex: 1,
    backgroundColor: '#27272A',
    paddingVertical: 12,
    borderRadius: 2,
    alignItems: 'center',
    marginRight: 8,
  },
  actionText: {
    color: '#FAFAFA',
    fontSize: 12,
    fontWeight: '600',
    letterSpacing: 1,
  },
  resolveBtn: {
    backgroundColor: 'transparent',
    borderWidth: 1,
    borderColor: '#4ADE80',
    marginRight: 0,
  },
  resolveText: {
    color: '#4ADE80',
  },
  card: {
    backgroundColor: '#0A0A0A',
    borderWidth: 1,
    borderColor: '#27272A',
    marginHorizontal: 16,
    marginBottom: 16,
    padding: 16,
    borderRadius: 2,
  },
  cardTitle: {
    fontSize: 11,
    color: '#A1A1AA',
    letterSpacing: 1,
    marginBottom: 16,
  },
  detailRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#1a1a1a',
  },
  detailLabel: {
    fontSize: 12,
    color: '#71717A',
  },
  detailValue: {
    fontSize: 12,
    color: '#FAFAFA',
    flex: 1,
    textAlign: 'right',
  },
  monoText: {
    fontFamily: 'monospace',
    color: '#60A5FA',
  },
  codeBlock: {
    backgroundColor: '#000',
    padding: 12,
    borderRadius: 2,
    borderWidth: 1,
    borderColor: '#1a1a1a',
  },
  codeText: {
    fontSize: 11,
    color: '#4ADE80',
    fontFamily: 'monospace',
    lineHeight: 18,
  },
});
