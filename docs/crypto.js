const enc = new TextEncoder();

function b64ToBytes(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

function bytesToB64(bytes) {
  let bin = '';
  const arr = new Uint8Array(bytes);
  for (let i = 0; i < arr.byteLength; i++) bin += String.fromCharCode(arr[i]);
  return btoa(bin);
}

function b64urlToUint8(base64UrlString) {
  const padding = '='.repeat((4 - (base64UrlString.length % 4)) % 4);
  const base64 = (base64UrlString + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

let cachedKey = null;
let cachedPass = null;

async function deriveKey(pass, salt) {
  if (cachedKey && cachedPass === pass) return cachedKey;
  const base = await crypto.subtle.importKey('raw', enc.encode(pass), 'PBKDF2', false, ['deriveKey']);
  const key = await crypto.subtle.deriveKey(
    { name: 'PBKDF2', salt, iterations: 310000, hash: 'SHA-256' },
    base,
    { name: 'AES-GCM', length: 256 },
    false,
    ['decrypt', 'encrypt']
  );
  cachedKey = key;
  cachedPass = pass;
  return key;
}

async function decryptState(env, pass) {
  const salt = b64ToBytes(env.salt), iv = b64ToBytes(env.iv), ct = b64ToBytes(env.ct);
  const key = await deriveKey(pass, salt);
  const pt = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv, additionalData: enc.encode('intraday-state-v1') },
    key,
    ct
  );
  return JSON.parse(new TextDecoder().decode(pt));
}

async function encryptState(data, pass, customSalt = null, customIv = null) {
  const salt = customSalt || crypto.getRandomValues(new Uint8Array(16));
  const iv = customIv || crypto.getRandomValues(new Uint8Array(12));
  const key = await deriveKey(pass, salt);
  const pt = enc.encode(typeof data === 'string' ? data : JSON.stringify(data));
  const ctWithTag = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv, additionalData: enc.encode('intraday-state-v1') },
    key,
    pt
  );
  return {
    salt: bytesToB64(salt),
    iv: bytesToB64(iv),
    ct: bytesToB64(ctWithTag)
  };
}
