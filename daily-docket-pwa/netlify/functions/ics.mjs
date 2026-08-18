/* Netlify Function — same-origin passthrough for the calendar feeds.
   Called as /ics?cal=<index>, matching the order of `calendars` in config.js.

   Set these in Site configuration → Environment variables, so the secret URLs
   never have to live in the repo:

     ICS_URLS   newline- or comma-separated, one per calendar, in config order.
                Blank entries are allowed for calendars you haven't set up:
                    School|https://calendar.google.com/.../basic.ics
                    Daily Routine|https://calendar.google.com/.../basic.ics
                    Canvas|https://canvas.ucsc.edu/feeds/calendars/....ics
                The "Label|" part is optional and only used in error messages.

     ICS_URL    single-calendar shorthand, used when ICS_URLS is absent.

   Netlify Functions v2 routes this itself via the `config.path` export below;
   no redirect rule needed. */

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

const calendar = (body, source) =>
  new Response(body, {
    status: 200,
    headers: {
      'Content-Type': 'text/calendar; charset=utf-8',
      'Cache-Control': 'public, max-age=0, s-maxage=300, stale-while-revalidate=600',
      'Access-Control-Allow-Origin': '*',
      'X-Docket-Source': source,
    },
  });

export default async (req) => {
  const calendars = calendarList();
  if (!calendars.length) {
    return new Response('Neither ICS_URLS nor ICS_URL is set.', {
      status: 500,
      headers: { 'Content-Type': 'text/plain' },
    });
  }

  const index = Number.parseInt(new URL(req.url).searchParams.get('cal') || '0', 10) || 0;

  // An index past the end, or a calendar with no URL yet, returns an empty but
  // valid calendar — one unconfigured feed shouldn't fail the whole sync.
  const cal = calendars[index];
  if (!cal || !cal.url) return calendar(EMPTY, 'unconfigured');

  try {
    const upstream = await fetch(cal.url.replace(/^webcal:\/\//i, 'https://'), {
      headers: { 'User-Agent': 'DailyDocket/1.0' },
      redirect: 'follow',
    });
    if (!upstream.ok) {
      return new Response(`${cal.label} responded ${upstream.status}`, { status: 502 });
    }
    return calendar(await upstream.text(), `upstream:${index}`);
  } catch (err) {
    return new Response(`Could not reach ${cal.label}: ${err.message}`, { status: 502 });
  }
};

export const config = { path: '/ics' };
