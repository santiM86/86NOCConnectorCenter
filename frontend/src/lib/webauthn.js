import axios from "axios";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const b64uToBuf = (s) => {
  const pad = "=".repeat((4 - (s.length % 4)) % 4);
  const b = atob((s + pad).replace(/-/g, "+").replace(/_/g, "/"));
  const arr = new Uint8Array(b.length);
  for (let i = 0; i < b.length; i++) arr[i] = b.charCodeAt(i);
  return arr.buffer;
};
const bufToB64u = (buf) => {
  const bytes = new Uint8Array(buf);
  let str = "";
  for (const b of bytes) str += String.fromCharCode(b);
  return btoa(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
};

export const passkeySupported = () =>
  typeof window !== "undefined" && !!window.PublicKeyCredential;

// Registrazione passkey (richiede sessione JWT valida negli header axios)
export async function registerPasskey(label) {
  const { data } = await axios.post(`${API}/auth/webauthn/register/begin`, {});
  const pk = data.publicKey;
  pk.challenge = b64uToBuf(pk.challenge);
  pk.user.id = b64uToBuf(pk.user.id);
  if (pk.excludeCredentials) pk.excludeCredentials = pk.excludeCredentials.map((c) => ({ ...c, id: b64uToBuf(c.id) }));
  const cred = await navigator.credentials.create({ publicKey: pk });
  const r = cred.response;
  const payload = {
    id: cred.id, rawId: bufToB64u(cred.rawId), type: cred.type,
    response: {
      clientDataJSON: bufToB64u(r.clientDataJSON),
      attestationObject: bufToB64u(r.attestationObject),
      transports: r.getTransports ? r.getTransports() : [],
    },
  };
  await axios.post(`${API}/auth/webauthn/register/complete`, {
    ceremony_token: data.ceremony_token, credential: payload, label: label || "Passkey",
  });
}

// Login passwordless con passkey. Ritorna { token, refresh_token, user }
export async function loginWithPasskey() {
  const { data } = await axios.post(`${API}/auth/webauthn/authenticate/begin`, {});
  const pk = data.publicKey;
  pk.challenge = b64uToBuf(pk.challenge);
  if (pk.allowCredentials) pk.allowCredentials = pk.allowCredentials.map((c) => ({ ...c, id: b64uToBuf(c.id) }));
  const cred = await navigator.credentials.get({ publicKey: pk });
  const r = cred.response;
  const payload = {
    id: cred.id, rawId: bufToB64u(cred.rawId), type: cred.type,
    response: {
      clientDataJSON: bufToB64u(r.clientDataJSON),
      authenticatorData: bufToB64u(r.authenticatorData),
      signature: bufToB64u(r.signature),
      userHandle: r.userHandle ? bufToB64u(r.userHandle) : null,
    },
  };
  const res = await axios.post(`${API}/auth/webauthn/authenticate/complete`, {
    ceremony_token: data.ceremony_token, credential: payload,
  });
  return res.data;
}

export const listPasskeys = () => axios.get(`${API}/auth/webauthn/credentials`).then((r) => r.data.credentials);
export const deletePasskey = (id) => axios.delete(`${API}/auth/webauthn/credentials/${encodeURIComponent(id)}`);
export const adminListPasskeyUsers = () => axios.get(`${API}/auth/webauthn/admin/users`).then((r) => r.data.users);
export const adminResetPasskeys = (userId) => axios.post(`${API}/auth/webauthn/admin/reset/${encodeURIComponent(userId)}`);
