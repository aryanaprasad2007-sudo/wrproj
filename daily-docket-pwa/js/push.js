/* Web Push subscribe/unsubscribe.
   iOS Safari only supports Web Push once the app is added to the Home Screen
   (Share → Add to Home Screen) and only on iOS 16.4+. In the browser tab
   itself, `pushSupported()` returns false on iOS — that's expected, not a bug. */

const SUBSCRIBE_PATH = '/push/subscribe';
const TEST_PATH = '/push/test';

function urlBase64ToUint8Array(base64) {
  const padding = '='.repeat((4 - (base64.length % 4)) % 4);
  const base = (base64 + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(base);
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

export function pushSupported() {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
}

/** @returns {'unsupported'|'denied'|'off'|'subscribed'} */
export async function pushStatus() {
  if (!pushSupported()) return 'unsupported';
  if (Notification.permission === 'denied') return 'denied';
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  return sub ? 'subscribed' : 'off';
}

export async function subscribe(vapidPublicKey) {
  if (!pushSupported()) {
    throw new Error('Push isn’t supported here. On iPhone, add this to your Home Screen first.');
  }
  if (!vapidPublicKey) {
    throw new Error('config.js is missing vapidPublicKey — see README.md.');
  }

  const permission = await Notification.requestPermission();
  if (permission !== 'granted') throw new Error('Notification permission was not granted.');

  const reg = await navigator.serviceWorker.ready;
  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(vapidPublicKey),
    });
  }

  const res = await fetch(SUBSCRIBE_PATH, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(sub),
  });
  if (!res.ok) throw new Error(`Server rejected the subscription (${res.status}).`);
  return sub;
}

export async function unsubscribe() {
  if (!pushSupported()) return;
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  if (sub) await sub.unsubscribe();
  await fetch(SUBSCRIBE_PATH, { method: 'DELETE' }).catch(() => {});
}

export async function sendTestPush() {
  const res = await fetch(TEST_PATH, { method: 'POST' });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(text || `Test push failed (${res.status}).`);
  }
}
