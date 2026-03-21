import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  FlatList,
  StyleSheet,
  RefreshControl,
  TouchableOpacity,
} from 'react-native';
import axios from 'axios';
import { useAuth } from '../App';

export default function AlertsScreen({ navigation }) {
  const { API_BASE_URL } = useAuth();
  const [alerts, setAlerts] = useState([]);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState('all'); // all, critical, high, medium, low

  useEffect(() => {
    fetchAlerts();
  }, [filter]);

  const fetchAlerts = async () => {
    try {
      let url = `${API_BASE_URL}/alerts?limit=100`;
      if (filter !== 'all') {
        url += `&severity=${filter}`;
      }
      const response = await axios.get(url);
      setAlerts(response.data);
    } catch (error) {
      console.error('Error fetching alerts:', error);
    }
  };

  const onRefresh = async () => {
    setRefreshing(true);
    await fetchAlerts();
    setRefreshing(false);
  };

  const handleAcknowledge = async (alertId) => {
    try {
      await axios.patch(`${API_BASE_URL}/alerts/${alertId}`, { status: 'acknowledged' });
      fetchAlerts();
    } catch (error) {
      console.error('Error:', error);
    }
  };

  const handleResolve = async (alertId) => {
    try {
      await axios.patch(`${API_BASE_URL}/alerts/${alertId}`, { status: 'resolved' });
      fetchAlerts();
    } catch (error) {
      console.error('Error:', error);
    }
  };

  const filterOptions = [
    { key: 'all', label: 'Tutti' },
    { key: 'critical', label: 'Critici', color: '#F87171' },
    { key: 'high', label: 'Alti', color: '#FBBF24' },
    { key: 'medium', label: 'Medi', color: '#60A5FA' },
    { key: 'low', label: 'Bassi', color: '#4ADE80' },
  ];

  const renderAlert = ({ item }) => {
    const severityColors = {
      critical: '#F87171',
      high: '#FBBF24',
      medium: '#60A5FA',
      low: '#4ADE80',
    };
    const color = severityColors[item.severity] || '#71717A';

    return (
      <TouchableOpacity
        style={styles.alertCard}
        onPress={() => navigation.navigate('AlertDetail', { alertId: item.id })}
      >
        <View style={styles.alertHeader}>
          <View style={[styles.severityBadge, { backgroundColor: color + '20', borderColor: color + '40' }]}>
            <Text style={[styles.severityText, { color }]}>
              {item.severity.toUpperCase()}
            </Text>
          </View>
          <Text style={[styles.statusText, { color: item.status === 'active' ? '#F87171' : item.status === 'acknowledged' ? '#FBBF24' : '#4ADE80' }]}>
            {item.status.toUpperCase()}
          </Text>
        </View>

        <Text style={styles.alertTitle} numberOfLines={2}>{item.title}</Text>
        <Text style={styles.alertMessage} numberOfLines={1}>{item.message}</Text>

        <View style={styles.alertMeta}>
          <Text style={styles.metaText}>{item.device_name}</Text>
          <Text style={styles.metaDot}>•</Text>
          <Text style={styles.metaText}>{item.client_name}</Text>
        </View>

        <View style={styles.alertFooter}>
          <Text style={styles.timeText}>
            {new Date(item.created_at).toLocaleString('it-IT')}
          </Text>
          <View style={styles.actions}>
            {item.status === 'active' && (
              <TouchableOpacity
                style={styles.actionBtn}
                onPress={() => handleAcknowledge(item.id)}
              >
                <Text style={styles.actionText}>ACK</Text>
              </TouchableOpacity>
            )}
            {item.status !== 'resolved' && (
              <TouchableOpacity
                style={[styles.actionBtn, styles.resolveBtn]}
                onPress={() => handleResolve(item.id)}
              >
                <Text style={[styles.actionText, styles.resolveText]}>✓</Text>
              </TouchableOpacity>
            )}
          </View>
        </View>
      </TouchableOpacity>
    );
  };

  return (
    <View style={styles.container}>
      {/* Filter Bar */}
      <View style={styles.filterBar}>
        {filterOptions.map((opt) => (
          <TouchableOpacity
            key={opt.key}
            style={[
              styles.filterBtn,
              filter === opt.key && styles.filterBtnActive,
              opt.color && filter === opt.key && { borderColor: opt.color },
            ]}
            onPress={() => setFilter(opt.key)}
          >
            <Text
              style={[
                styles.filterText,
                filter === opt.key && styles.filterTextActive,
                opt.color && filter === opt.key && { color: opt.color },
              ]}
            >
              {opt.label}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* Alert Count */}
      <Text style={styles.countText}>{alerts.length} alert</Text>

      {/* Alert List */}
      <FlatList
        data={alerts}
        renderItem={renderAlert}
        keyExtractor={(item) => item.id}
        contentContainerStyle={styles.listContent}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#FAFAFA" />
        }
        ListEmptyComponent={
          <View style={styles.emptyState}>
            <Text style={styles.emptyText}>Nessun alert trovato</Text>
          </View>
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#050505',
  },
  filterBar: {
    flexDirection: 'row',
    padding: 12,
    backgroundColor: '#0A0A0A',
    borderBottomWidth: 1,
    borderBottomColor: '#27272A',
  },
  filterBtn: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 2,
    borderWidth: 1,
    borderColor: '#27272A',
    marginRight: 8,
  },
  filterBtnActive: {
    backgroundColor: '#27272A',
    borderColor: '#FAFAFA',
  },
  filterText: {
    fontSize: 12,
    color: '#71717A',
  },
  filterTextActive: {
    color: '#FAFAFA',
  },
  countText: {
    fontSize: 12,
    color: '#71717A',
    padding: 12,
    paddingBottom: 0,
  },
  listContent: {
    padding: 12,
  },
  alertCard: {
    backgroundColor: '#0A0A0A',
    borderWidth: 1,
    borderColor: '#27272A',
    borderRadius: 2,
    padding: 12,
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
  statusText: {
    fontSize: 10,
    fontWeight: '500',
    letterSpacing: 0.5,
  },
  alertTitle: {
    fontSize: 14,
    fontWeight: '500',
    color: '#FAFAFA',
    marginBottom: 4,
  },
  alertMessage: {
    fontSize: 12,
    color: '#A1A1AA',
    marginBottom: 8,
  },
  alertMeta: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
  },
  metaText: {
    fontSize: 12,
    color: '#71717A',
  },
  metaDot: {
    marginHorizontal: 6,
    color: '#71717A',
  },
  alertFooter: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderTopWidth: 1,
    borderTopColor: '#27272A',
    paddingTop: 12,
  },
  timeText: {
    fontSize: 11,
    color: '#71717A',
    fontFamily: 'monospace',
  },
  actions: {
    flexDirection: 'row',
  },
  actionBtn: {
    backgroundColor: '#27272A',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 2,
    marginLeft: 8,
  },
  actionText: {
    fontSize: 11,
    color: '#FAFAFA',
    fontWeight: '600',
  },
  resolveBtn: {
    backgroundColor: 'transparent',
    borderWidth: 1,
    borderColor: '#4ADE80',
  },
  resolveText: {
    color: '#4ADE80',
  },
  emptyState: {
    padding: 48,
    alignItems: 'center',
  },
  emptyText: {
    color: '#71717A',
    fontSize: 14,
  },
});
