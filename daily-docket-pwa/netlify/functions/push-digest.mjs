/* Netlify scheduled function — a daily "your docket is ready" nudge.
   Schedules run in UTC. The default below (14:00 UTC) is 7am Pacific Daylight
   Time — adjust the cron for your own timezone/offset, or delete this file
   if you'd rather only ever trigger pushes with push-test.mjs / your own
   calling code.

   This is intentionally a generic ping rather than a re-implementation of
   js/importance.js's deadline scoring — that logic lives in the browser and
   reads from localStorage-cached feeds, so duplicating it server-side would
   mean fetching and parsing every calendar again here. If you want real
   "your spotlight deadline is in 15 minutes" pushes, that logic belongs in
   this file, fetching the same ICS feeds as netlify/functions/ics.mjs. */

import { sendPush } from './_push.mjs';

export default async () => {
  try {
    await sendPush({
      title: 'Daily Docket',
      body: "Good morning — today's docket is ready.",
    });
  } catch (err) {
    console.error('[push-digest]', err);
  }
};

export const config = { schedule: '0 14 * * *' };
