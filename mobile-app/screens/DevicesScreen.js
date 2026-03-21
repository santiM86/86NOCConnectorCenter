import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  FlatList,
  StyleSheet,
  RefreshControl,
} from 'react-native';
import axios from 'axios';
import { useAuth } from '../App';

export default function DevicesScreen() {
  const { API_BASE_URL } = useAuth();
  const [devices, setDevices] = useState([]);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    fetchDevices();
  }, []);

  const fetchDevices = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/devices`);
      setDevices(response.data);
    } catch (error) {
      console.error('Error fetching devices:', error);
    }
  };

  const onRefresh = async () => {
    setRefreshing(true);
    await fetchDevices();
    setRefreshing(false);
  };

  const deviceTypeLabels = {
    backup: 'Backup',
    firewall: 'Firewall',
    switch: 'Switch',
    ilo: 'ILO/iDRAC',
  };

  const renderDevice = ({ item }) => (
    <View style={styles.deviceCard}>
      <View style={styles.deviceHeader}>
        <View style={styles.deviceIcon}>
          <Text style={styles.iconText}>
            {item.device_type === 'backup' ? '💾' :
             item.device_type === 'firewall' ? '🛡️' :
             item.device_type === 'switch' ? '🔄' :
             item.device_type === 'ilo' ? '🖥️' : '📟'}
          </Text>
        </View>
        <View style={styles.deviceInfo}>
          <Text style={styles.deviceName}>{item.name}</Text>
          <Text style={styles.deviceType}>
            {deviceTypeLabels[item.device_type] || item.device_type}
          </Text>
        </View>
        {item.redfish_enabled && (
          <View style={styles.redfishBadge}>
            <Text style={styles.redfishText}>RF</Text>
          </View>
        )}
      </View>

      <View style={styles.deviceDetails}>
        <DetailRow label="IP" value={item.ip_address} mono />
        {item.hostname && <DetailRow label="Host" value={item.hostname} mono />}
        <DetailRow label="Cliente" value={item.client_name} />
        {item.health_status && (
          <DetailRow 
            label="Health" 
            value={item.health_status}
            valueColor={item.health_status === 'OK' ? '#4ADE80' : '#F87171'}
          />
        )}
      </View>

      <View style={styles.deviceFooter}>
        <View style={[
          styles.statusDot, 
          { backgroundColor: item.status === 'active' ? '#4ADE80' : '#71717A' }
        ]} />
        <Text style={styles.statusText}>{item.status}</Text>
        {item.has_credentials && (
          <Text style={styles.credBadge}>🔐</Text>
        )}
      </View>
    </View>
  );

  return (
    <View style={styles.container}>
      <Text style={styles.countText}>{devices.length} dispositivi</Text>
      
      <FlatList
        data={devices}
        renderItem={renderDevice}
        keyExtractor={(item) => item.id}
        contentContainerStyle={styles.listContent}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#FAFAFA" />
        }
        ListEmptyComponent={
          <View style={styles.emptyState}>
            <Text style={styles.emptyText}>Nessun dispositivo configurato</Text>
          </View>
        }
      />
    </View>
  );
}

const DetailRow = ({ label, value, mono, valueColor }) => (
  <View style={styles.detailRow}>
    <Text style={styles.detailLabel}>{label}</Text>
    <Text style={[
      styles.detailValue, 
      mono && styles.monoText,
      valueColor && { color: valueColor }
    ]}>
      {value}
    </Text>
  </View>
);

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#050505',
  },
  countText: {
    fontSize: 12,
    color: '#71717A',
    padding: 16,
    paddingBottom: 8,
  },
  listContent: {
    padding: 12,
  },
  deviceCard: {
    backgroundColor: '#0A0A0A',
    borderWidth: 1,
    borderColor: '#27272A',
    borderRadius: 2,
    padding: 12,
    marginBottom: 8,
  },
  deviceHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
  },
  deviceIcon: {
    width: 40,
    height: 40,
    backgroundColor: '#27272A',
    borderRadius: 2,
    justifyContent: 'center',
    alignItems: 'center',
  },
  iconText: {
    fontSize: 18,
  },
  deviceInfo: {
    flex: 1,
    marginLeft: 12,
  },
  deviceName: {
    fontSize: 14,
    fontWeight: '600',
    color: '#FAFAFA',
    fontFamily: 'monospace',
  },
  deviceType: {
    fontSize: 11,
    color: '#71717A',
    marginTop: 2,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  redfishBadge: {
    backgroundColor: '#60A5FA20',
    borderWidth: 1,
    borderColor: '#60A5FA40',
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 2,
  },
  redfishText: {
    fontSize: 10,
    color: '#60A5FA',
    fontWeight: '600',
  },
  deviceDetails: {
    borderTopWidth: 1,
    borderTopColor: '#27272A',
    paddingTop: 12,
  },
  detailRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 6,
  },
  detailLabel: {
    fontSize: 12,
    color: '#71717A',
  },
  detailValue: {
    fontSize: 12,
    color: '#A1A1AA',
  },
  monoText: {
    fontFamily: 'monospace',
    color: '#60A5FA',
  },
  deviceFooter: {
    flexDirection: 'row',
    alignItems: 'center',
    borderTopWidth: 1,
    borderTopColor: '#27272A',
    paddingTop: 12,
    marginTop: 8,
  },
  statusDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    marginRight: 6,
  },
  statusText: {
    fontSize: 11,
    color: '#71717A',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    flex: 1,
  },
  credBadge: {
    fontSize: 12,
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
