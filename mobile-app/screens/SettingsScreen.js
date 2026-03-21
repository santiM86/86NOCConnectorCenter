import React, { useState } from 'react';
import {
  View,
  Text,
  ScrollView,
  StyleSheet,
  TouchableOpacity,
  Alert,
} from 'react-native';
import { useAuth } from '../App';

export default function SettingsScreen() {
  const { user, logout } = useAuth();

  const handleLogout = () => {
    Alert.alert(
      'Logout',
      'Sei sicuro di voler uscire?',
      [
        { text: 'Annulla', style: 'cancel' },
        { text: 'Esci', onPress: logout, style: 'destructive' },
      ]
    );
  };

  return (
    <ScrollView style={styles.container}>
      {/* User Info */}
      <View style={styles.card}>
        <View style={styles.userHeader}>
          <View style={styles.avatar}>
            <Text style={styles.avatarText}>
              {user?.name?.charAt(0).toUpperCase() || '?'}
            </Text>
          </View>
          <View style={styles.userInfo}>
            <Text style={styles.userName}>{user?.name}</Text>
            <Text style={styles.userEmail}>{user?.email}</Text>
          </View>
        </View>

        <View style={styles.userMeta}>
          <View style={styles.metaItem}>
            <Text style={styles.metaLabel}>Ruolo</Text>
            <Text style={styles.metaValue}>{user?.role?.toUpperCase()}</Text>
          </View>
          <View style={styles.metaItem}>
            <Text style={styles.metaLabel}>2FA</Text>
            <Text style={[
              styles.metaValue,
              { color: user?.two_factor_enabled ? '#4ADE80' : '#71717A' }
            ]}>
              {user?.two_factor_enabled ? 'ATTIVO' : 'NON ATTIVO'}
            </Text>
          </View>
        </View>
      </View>

      {/* Security Info */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>SICUREZZA ENTERPRISE</Text>
        
        <View style={styles.securityGrid}>
          <SecurityItem label="AES-256-GCM" description="Crittografia credenziali" />
          <SecurityItem label="Argon2id" description="Hash password" />
          <SecurityItem label="Rate Limiting" description="Protezione brute force" />
          <SecurityItem label="Audit Log" description="Tracciamento completo" />
        </View>
      </View>

      {/* App Info */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>INFORMAZIONI APP</Text>
        
        <InfoRow label="Versione" value="1.0.0" />
        <InfoRow label="Build" value="2024.01.21" />
        <InfoRow label="API" value="v2.0.0" />
      </View>

      {/* Logout Button */}
      <TouchableOpacity style={styles.logoutButton} onPress={handleLogout}>
        <Text style={styles.logoutText}>LOGOUT</Text>
      </TouchableOpacity>

      <Text style={styles.footer}>NOC Command Center</Text>
    </ScrollView>
  );
}

const SecurityItem = ({ label, description }) => (
  <View style={styles.securityItem}>
    <Text style={styles.securityLabel}>{label}</Text>
    <Text style={styles.securityDesc}>{description}</Text>
  </View>
);

const InfoRow = ({ label, value }) => (
  <View style={styles.infoRow}>
    <Text style={styles.infoLabel}>{label}</Text>
    <Text style={styles.infoValue}>{value}</Text>
  </View>
);

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#050505',
  },
  card: {
    backgroundColor: '#0A0A0A',
    borderWidth: 1,
    borderColor: '#27272A',
    margin: 16,
    marginBottom: 0,
    padding: 16,
    borderRadius: 2,
  },
  cardTitle: {
    fontSize: 11,
    color: '#A1A1AA',
    letterSpacing: 1,
    marginBottom: 16,
  },
  userHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 16,
    paddingBottom: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#27272A',
  },
  avatar: {
    width: 48,
    height: 48,
    borderRadius: 2,
    backgroundColor: '#27272A',
    justifyContent: 'center',
    alignItems: 'center',
  },
  avatarText: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#FAFAFA',
  },
  userInfo: {
    marginLeft: 12,
    flex: 1,
  },
  userName: {
    fontSize: 16,
    fontWeight: '600',
    color: '#FAFAFA',
  },
  userEmail: {
    fontSize: 13,
    color: '#71717A',
    marginTop: 2,
  },
  userMeta: {
    flexDirection: 'row',
  },
  metaItem: {
    flex: 1,
  },
  metaLabel: {
    fontSize: 11,
    color: '#71717A',
    marginBottom: 4,
  },
  metaValue: {
    fontSize: 12,
    color: '#FAFAFA',
    fontWeight: '600',
    letterSpacing: 0.5,
  },
  securityGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    marginHorizontal: -4,
  },
  securityItem: {
    width: '48%',
    margin: '1%',
    backgroundColor: '#0A0A0A',
    borderWidth: 1,
    borderColor: '#27272A',
    padding: 12,
    borderRadius: 2,
  },
  securityLabel: {
    fontSize: 12,
    color: '#4ADE80',
    fontWeight: '600',
  },
  securityDesc: {
    fontSize: 10,
    color: '#71717A',
    marginTop: 4,
  },
  infoRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#1a1a1a',
  },
  infoLabel: {
    fontSize: 13,
    color: '#71717A',
  },
  infoValue: {
    fontSize: 13,
    color: '#FAFAFA',
    fontFamily: 'monospace',
  },
  logoutButton: {
    margin: 16,
    backgroundColor: 'transparent',
    borderWidth: 1,
    borderColor: '#F87171',
    paddingVertical: 14,
    borderRadius: 2,
    alignItems: 'center',
  },
  logoutText: {
    color: '#F87171',
    fontSize: 14,
    fontWeight: '600',
    letterSpacing: 1,
  },
  footer: {
    textAlign: 'center',
    color: '#3f3f46',
    fontSize: 11,
    paddingVertical: 24,
  },
});
