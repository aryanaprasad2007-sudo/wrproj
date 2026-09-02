/* Netlify Function — POST to save this device's Web Push subscription,
   DELETE to remove it. Called from js/push.js. */

import { saveSubscription, dropSubscription } from './_push.mjs';

export default async (req) => {
  if (req.method === 'DELETE') {
    await dropSubscription();
    return new Response(null, { status: 204 });
  }

  if (req.method !== 'POST') {
    return new Response('Method not allowed', { status: 405 });
  }

  let subscription;
  try {
    subscription = await req.json();
  } catch {
    return new Response('Bad JSON body', { status: 400 });
  }
  if (!subscription?.endpoint) {
    return new Response('Missing subscription.endpoint', { status: 400 });
  }

  await saveSubscription(subscription);
  return new Response(null, { status: 204 });
};

export const config = { path: '/push/subscribe' };
