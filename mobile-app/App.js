import React, { useState, useEffect, createContext, useContext } from 'react';
import { NavigationContainer, DefaultTheme } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { StatusBar } from 'expo-status-bar';
import * as SecureStore from 'expo-secure-store';
import axios from 'axios';

// Screens
import LoginScreen from './screens/LoginScreen';
import TwoFactorScreen from './screens/TwoFactorScreen';
import DashboardScreen from './screens/DashboardScreen';
import AlertsScreen from './screens/AlertsScreen';
import AlertDetailScreen from './screens/AlertDetailScreen';
import DevicesScreen from './screens/DevicesScreen';
import SettingsScreen from './screens/SettingsScreen';

// API Configuration - Change this to your production URL
const API_BASE_URL = 'https://your-api-url.com/api';

// Auth Context
const AuthContext = createContext(null);

export const useAuth = () => useContext(AuthContext);

// Dark Theme
const DarkTheme = {
  ...DefaultTheme,
  colors: {
    ...DefaultTheme.colors,
    primary: '#FAFAFA',
    background: '#050505',
    card: '#0A0A0A',
    text: '#FAFAFA',
    border: '#27272A',
    notification: '#F87171',
  },
};

const Stack = createNativeStackNavigator();
const Tab = createBottomTabNavigator();

// Tab Navigator for authenticated users
function MainTabs() {
  return (
    <Tab.Navigator
      screenOptions={{
        tabBarStyle: {
          backgroundColor: '#0A0A0A',
          borderTopColor: '#27272A',
          paddingBottom: 8,
          paddingTop: 8,
          height: 60,
        },
        tabBarActiveTintColor: '#FAFAFA',
        tabBarInactiveTintColor: '#71717A',
        headerStyle: {
          backgroundColor: '#050505',
        },
        headerTintColor: '#FAFAFA',
        headerTitleStyle: {
          fontWeight: 'bold',
        },
      }}
    >
      <Tab.Screen 
        name="Dashboard" 
        component={DashboardScreen}
        options={{
          tabBarLabel: 'Dashboard',
          // tabBarIcon will be added with icons library
        }}
      />
      <Tab.Screen 
        name="Alerts" 
        component={AlertsStack}
        options={{
          headerShown: false,
          tabBarLabel: 'Alert',
        }}
      />
      <Tab.Screen 
        name="Devices" 
        component={DevicesScreen}
        options={{
          tabBarLabel: 'Dispositivi',
        }}
      />
      <Tab.Screen 
        name="Settings" 
        component={SettingsScreen}
        options={{
          tabBarLabel: 'Impostazioni',
        }}
      />
    </Tab.Navigator>
  );
}

// Alerts Stack Navigator
function AlertsStack() {
  return (
    <Stack.Navigator
      screenOptions={{
        headerStyle: {
          backgroundColor: '#050505',
        },
        headerTintColor: '#FAFAFA',
      }}
    >
      <Stack.Screen name="AlertsList" component={AlertsScreen} options={{ title: 'Alert' }} />
      <Stack.Screen name="AlertDetail" component={AlertDetailScreen} options={{ title: 'Dettaglio Alert' }} />
    </Stack.Navigator>
  );
}

// Auth Provider
function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(null);
  const [loading, setLoading] = useState(true);
  const [requires2FA, setRequires2FA] = useState(false);

  useEffect(() => {
    loadToken();
  }, []);

  const loadToken = async () => {
    try {
      const storedToken = await SecureStore.getItemAsync('noc_token');
      if (storedToken) {
        setToken(storedToken);
        axios.defaults.headers.common['Authorization'] = `Bearer ${storedToken}`;
        await fetchUser();
      }
    } catch (error) {
      console.error('Error loading token:', error);
    } finally {
      setLoading(false);
    }
  };

  const fetchUser = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/auth/me`);
      setUser(response.data);
    } catch (error) {
      console.error('Error fetching user:', error);
      await logout();
    }
  };

  const login = async (email, password) => {
    const response = await axios.post(`${API_BASE_URL}/auth/login`, { email, password });
    const { token: newToken, user: userData, requires_2fa } = response.data;
    
    await SecureStore.setItemAsync('noc_token', newToken);
    setToken(newToken);
    axios.defaults.headers.common['Authorization'] = `Bearer ${newToken}`;
    
    if (requires_2fa) {
      setRequires2FA(true);
      return { requires_2fa: true };
    }
    
    setUser(userData);
    return userData;
  };

  const verify2FA = async (code) => {
    const response = await axios.post(`${API_BASE_URL}/auth/verify-2fa`, { code });
    const { token: newToken } = response.data;
    
    await SecureStore.setItemAsync('noc_token', newToken);
    setToken(newToken);
    axios.defaults.headers.common['Authorization'] = `Bearer ${newToken}`;
    setRequires2FA(false);
    
    await fetchUser();
    return response.data;
  };

  const register = async (email, password, name) => {
    const response = await axios.post(`${API_BASE_URL}/auth/register`, { email, password, name });
    const { token: newToken, user: userData } = response.data;
    
    await SecureStore.setItemAsync('noc_token', newToken);
    setToken(newToken);
    setUser(userData);
    axios.defaults.headers.common['Authorization'] = `Bearer ${newToken}`;
    
    return userData;
  };

  const logout = async () => {
    await SecureStore.deleteItemAsync('noc_token');
    setToken(null);
    setUser(null);
    setRequires2FA(false);
    delete axios.defaults.headers.common['Authorization'];
  };

  return (
    <AuthContext.Provider value={{ 
      user, 
      token, 
      loading, 
      requires2FA,
      login, 
      verify2FA,
      register, 
      logout,
      API_BASE_URL 
    }}>
      {children}
    </AuthContext.Provider>
  );
}

// Main App
export default function App() {
  return (
    <AuthProvider>
      <NavigationContainer theme={DarkTheme}>
        <AppNavigator />
        <StatusBar style="light" />
      </NavigationContainer>
    </AuthProvider>
  );
}

function AppNavigator() {
  const { user, loading, requires2FA } = useAuth();

  if (loading) {
    // Could show a splash screen here
    return null;
  }

  return (
    <Stack.Navigator screenOptions={{ headerShown: false }}>
      {user ? (
        <Stack.Screen name="Main" component={MainTabs} />
      ) : requires2FA ? (
        <Stack.Screen name="TwoFactor" component={TwoFactorScreen} />
      ) : (
        <Stack.Screen name="Login" component={LoginScreen} />
      )}
    </Stack.Navigator>
  );
}
