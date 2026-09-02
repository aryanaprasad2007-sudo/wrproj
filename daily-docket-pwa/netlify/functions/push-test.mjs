/* Netlify Function — sends one push notification to whatever subscription is
   on file, right now. Wired to the "Send test" button in ⚙ Settings so you
   can confirm the whole chain (VAPID keys → subscription → iPhone) without
   waiting for the scheduled digest. */

import { sendPush } from './_push.mjs';

export default async (req) => {
  if (req.method !== 'POST') return new Response('Method not allowed', { status: 405 });

  try {
    const result = await sendPush({
      title: 'Daily Docket',
      body: 'Test notification — if you see this, push works. 🎉',
    });
    if (!result.sent) return new Response(result.reason, { status: 404 });
    return new Response(null, { status: 204 });
  } catch (err) {
    return new Response(String(err.message || err), { status: 500 });
  }
};

export const config = { path: '/push/test' };
