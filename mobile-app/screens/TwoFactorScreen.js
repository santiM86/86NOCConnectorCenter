import React, { useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  Alert,
} from 'react-native';
import { useAuth } from '../App';

export default function TwoFactorScreen() {
  const [code, setCode] = useState('');
  const [loading, setLoading] = useState(false);
  const { verify2FA, logout } = useAuth();

  const handleVerify = async () => {
    if (code.length !== 6) {
      Alert.alert('Errore', 'Inserisci un codice a 6 cifre');
      return;
    }

    setLoading(true);
    try {
      await verify2FA(code);
    } catch (error) {
      Alert.alert('Errore', error.response?.data?.detail || 'Codice non valido');
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = () => {
    logout();
  };

  return (
    <View style={styles.container}>
      <View style={styles.content}>
        {/* Header */}
        <View style={styles.header}>
          <Text style={styles.title}>Verifica 2FA</Text>
          <Text style={styles.subtitle}>
            Inserisci il codice dalla tua app di autenticazione
          </Text>
        </View>

        {/* Code Input */}
        <View style={styles.inputContainer}>
          <TextInput
            style={styles.codeInput}
            value={code}
            onChangeText={(text) => setCode(text.replace(/\D/g, '').slice(0, 6))}
            placeholder="000000"
            placeholderTextColor="#71717A"
            keyboardType="number-pad"
            maxLength={6}
            autoFocus
          />
          <Text style={styles.hint}>
            Apri Google Authenticator o Authy
          </Text>
        </View>

        {/* Buttons */}
        <TouchableOpacity
          style={[styles.button, (loading || code.length !== 6) && styles.buttonDisabled]}
          onPress={handleVerify}
          disabled={loading || code.length !== 6}
        >
          <Text style={styles.buttonText}>
            {loading ? 'VERIFICA...' : 'VERIFICA CODICE'}
          </Text>
        </TouchableOpacity>

        <TouchableOpacity style={styles.cancelButton} onPress={handleCancel}>
          <Text style={styles.cancelText}>Annulla e torna al login</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#050505',
    justifyContent: 'center',
    padding: 24,
  },
  content: {
    width: '100%',
  },
  header: {
    marginBottom: 32,
    alignItems: 'center',
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#FAFAFA',
    marginBottom: 8,
  },
  subtitle: {
    fontSize: 14,
    color: '#A1A1AA',
    textAlign: 'center',
  },
  inputContainer: {
    marginBottom: 24,
  },
  codeInput: {
    backgroundColor: '#0A0A0A',
    borderWidth: 1,
    borderColor: '#27272A',
    borderRadius: 2,
    padding: 20,
    color: '#FAFAFA',
    fontSize: 32,
    textAlign: 'center',
    letterSpacing: 16,
    fontFamily: 'monospace',
  },
  hint: {
    fontSize: 12,
    color: '#71717A',
    textAlign: 'center',
    marginTop: 12,
  },
  button: {
    backgroundColor: '#FAFAFA',
    paddingVertical: 14,
    borderRadius: 2,
    alignItems: 'center',
  },
  buttonDisabled: {
    opacity: 0.5,
  },
  buttonText: {
    color: '#050505',
    fontSize: 14,
    fontWeight: '600',
    letterSpacing: 1,
  },
  cancelButton: {
    marginTop: 20,
    alignItems: 'center',
  },
  cancelText: {
    color: '#71717A',
    fontSize: 14,
  },
});
