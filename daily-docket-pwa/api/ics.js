/* Vercel Serverless Function — same-origin passthrough for the calendar feeds.
   Called as /ics?cal=<index>, matching the order of `calendars` in config.js.
   vercel.json rewrites /ics to here.

   Set these in Project Settings → Environment Variables, so the secret URLs
   never have to live in the repo:

     ICS_URLS   newline- or comma-separated, one per calendar, in config order.
                Blank entries are allowed for calendars you haven't set up:
                    School|https://calendar.google.com/.../basic.ics
                    Daily Routine|https://calendar.google.com/.../basic.ics
                    Canvas|https://canvas.ucsc.edu/feeds/calendars/....ics
                The "Label|" part is optional and only used in error messages.

     ICS_URL    single-calendar shorthand, used when ICS_URLS is absent.        */

const EMPTY = 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Daily Docket//empty//EN\r\nEND:VCALENDAR\r\n';

function calendarList() {
  const many = (process.env.ICS_URLS || '').trim();
  if (many) {
    return many.split(/[\n,]+/).map((raw, i) => {
      const entry = raw.trim();
      const cut = entry.lastIndexOf('|');
      const label = cut > -1 ? entry.slice(0, cut).trim() : `Calendar ${i + 1}`;
      const url = (cut > -1 ? entry.slice(cut + 1) : entry).trim();
      return { label, url };
    });
  }
  const one = (process.env.ICS_URL || '').trim();
  return one ? [{ label: 'Calendar', url: one }] : [];
}

export default async function handler(req, res) {
  const calendars = calendarList();
  if (!calendars.length) {
    res.status(500).send('Neither ICS_URLS nor ICS_URL is set.');
    return;
  }

  const index = Number.parseInt(req.query?.cal ?? '0', 10) || 0;

  res.setHeader('Content-Type', 'text/calendar; charset=utf-8');
  res.setHeader('Cache-Control', 'public, max-age=0, s-maxage=300, stale-while-revalidate=600');
  res.setHeader('Access-Control-Allow-Origin', '*');

  // An index past the end, or a calendar with no URL yet, returns an empty but
  // valid calendar — one unconfigured feed shouldn't fail the whole sync.
  const cal = calendars[index];
  if (!cal || !cal.url) {
    res.setHeader('X-Docket-Source', 'unconfigured');
    res.status(200).send(EMPTY);
    return;
  }

  try {
    const upstream = await fetch(cal.url.replace(/^webcal:\/\//i, 'https://'), {
      headers: { 'User-Agent': 'DailyDocket/1.0' },
      redirect: 'follow',
    });
    if (!upstream.ok) {
      res.status(502).send(`${cal.label} responded ${upstream.status}`);
      return;
    }
    res.setHeader('X-Docket-Source', `upstream:${index}`);
    res.status(200).send(await upstream.text());
  } catch (err) {
    res.status(502).send(`Could not reach ${cal.label}: ${err.message}`);
  }
}
