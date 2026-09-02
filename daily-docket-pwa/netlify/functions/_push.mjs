/* Shared helper for the push-* functions. Filenames starting with `_` are
   never deployed as their own function (Netlify convention) — this is a
   library, not an endpoint.

   Single-user app: one subscription blob, overwritten on each (re)subscribe.
   If you ever want this for more than one device/person, key the store by
   subscription.endpoint instead of a fixed 'subscription' key. */

import webpush from 'web-push';
import { getStore } from '@netlify/blobs';

const subscriptions = () => getStore('push');

export async function saveSubscription(subscription) {
  await subscriptions().setJSON('subscription', subscription);
}

export async function dropSubscription() {
  await subscriptions().delete('subscription');
}

export async function sendPush({ title, body, url = '/' }) {
  const { VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_SUBJECT } = process.env;
  if (!VAPID_PUBLIC_KEY || !VAPID_PRIVATE_KEY) {
    throw new Error('VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY are not set — see README.md.');
  }
  webpush.setVapidDetails(VAPID_SUBJECT || 'mailto:nobody@example.com', VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY);

  const store = subscriptions();
  const subscription = await store.get('subscription', { type: 'json' });
  if (!subscription) return { sent: false, reason: 'no subscription on file' };

  try {
    await webpush.sendNotification(subscription, JSON.stringify({ title, body, url }));
    return { sent: true };
  } catch (err) {
    // The subscription is dead (uninstalled, permission revoked, expired) — stop retrying it.
    if (err.statusCode === 404 || err.statusCode === 410) await store.delete('subscription');
    throw err;
  }
}
