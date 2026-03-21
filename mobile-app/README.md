# NOC Command Center - React Native Mobile App

## Struttura
```
mobile-app/
├── App.js                 # Entry point e navigazione
├── app.json              # Configurazione Expo
├── package.json          # Dependencies
├── screens/
│   ├── LoginScreen.js    # Login e registrazione
│   ├── TwoFactorScreen.js # Verifica 2FA
│   ├── DashboardScreen.js # Dashboard con metriche live
│   ├── AlertsScreen.js   # Lista alert con filtri
│   ├── AlertDetailScreen.js # Dettaglio singolo alert
│   ├── DevicesScreen.js  # Lista dispositivi
│   └── SettingsScreen.js # Impostazioni e logout
└── assets/               # Icone e immagini
```

## Setup

### 1. Installa dependencies
```bash
cd mobile-app
yarn install
```

### 2. Configura API URL
Modifica in `App.js`:
```javascript
const API_BASE_URL = 'https://your-production-api.com/api';
```

### 3. Avvia in development
```bash
npx expo start
```

### 4. Build per produzione

#### Android
```bash
npx expo build:android
# oppure con EAS
eas build --platform android
```

#### iOS
```bash
npx expo build:ios
# oppure con EAS
eas build --platform ios
```

## Features

- ✅ Autenticazione JWT con SecureStore
- ✅ Supporto 2FA TOTP
- ✅ Dashboard real-time con WebSocket
- ✅ Gestione alert (ACK/Resolve)
- ✅ Filtri per severità
- ✅ Lista dispositivi con stato Redfish
- ✅ Dark theme NOC-style
- ✅ Pull-to-refresh
- ✅ Navigazione tab e stack

## Push Notifications (Opzionale)

Per abilitare le push notifications:

1. Configura Firebase Cloud Messaging
2. Aggiungi le credenziali in `app.json`
3. Registra il device token al backend al login

```javascript
import * as Notifications from 'expo-notifications';

async function registerForPushNotifications() {
  const { status } = await Notifications.requestPermissionsAsync();
  if (status === 'granted') {
    const token = await Notifications.getExpoPushTokenAsync();
    // Invia token al backend
    await axios.post(`${API_BASE_URL}/push/register`, { token: token.data });
  }
}
```

## Pubblicazione su Store

### Google Play Store
1. Genera AAB: `eas build --platform android`
2. Carica su Google Play Console
3. Compila listing e screenshots

### Apple App Store
1. Genera IPA: `eas build --platform ios`
2. Carica su App Store Connect tramite Transporter
3. Compila listing e screenshots
