/* Fetching and parsing the iCal feeds. Everything here is client-side; the only
   server involvement is an optional same-origin passthrough for the URLs,
   because Google's iCal endpoint sends no Access-Control-Allow-Origin header.

   Ari's schedule is spread over several calendars (School, Daily Routine,
   Canvas, …), so this reads a list of sources, not one feed, and tags every
   event with which calendar it came from. */

import ICAL from '../vendor/ical.js';
import { saveFeed, loadFeed } from './store.js';
import { areaFor } from './areas.js';

export class CalendarError extends Error {
  constructor(message, attempts) {
    super(message);
    this.name = 'CalendarError';
    this.attempts = attempts || [];
  }
}

/* ---------- config → a normalised list of sources ------------------------ */

/**
 * Accepts either the `calendars: [...]` array or a bare legacy `icsUrl`.
 * @returns {Array<{id, index, label, area, url, enabled}>}
 */
export function calendarSources(cfg) {
  const list = Array.isArray(cfg.calendars) && cfg.calendars.length
    ? cfg.calendars
    : [{ id: 'default', label: 'Calendar', url: cfg.icsUrl }];

  return list.map((cal, index) => ({
    index,
    id: cal.id || `cal${index}`,
    label: cal.label || `Calendar ${index + 1}`,
    area: cal.area || null,
    url: (cal.url || '').trim().replace(/^webcal:\/\//i, 'https://'),
    enabled: cal.enabled !== false,
  }));
}

/* ---------- fetching ------------------------------------------------------ */

function endpointsFor(source, cfg) {
  const out = [];

  if (cfg.icsProxyPath) {
    // ?cal=<index> tells the proxy which configured feed to pass through.
    const proxy = new URL(cfg.icsProxyPath, location.href);
    proxy.searchParams.set('cal', String(source.index));
    out.push({ via: 'proxy', url: proxy.href });
  }
  if (source.url) {
    out.push({ via: 'direct', url: source.url });
    if (cfg.useCorsRelay) {
      for (const tpl of cfg.corsRelays || []) {
        out.push({
          via: 'relay',
          url: tpl.includes('{url}')
            ? tpl.replace('{url}', encodeURIComponent(source.url))
            : tpl + encodeURIComponent(source.url),
        });
      }
    }
  }
  return out;
}

const looksLikeCalendar = (text) =>
  typeof text === 'string' && /BEGIN:VCALENDAR/i.test(text.slice(0, 2048));

function bust(url) {
  const u = new URL(url, location.href);
  u.searchParams.set('_', String(Math.floor(Date.now() / 30000))); // 30s buckets
  return u.href;
}

/** Try each endpoint for one calendar, then fall back to its last good sync. */
async function fetchOne(source, cfg) {
  const attempts = [];

  for (const endpoint of endpointsFor(source, cfg)) {
    try {
      const res = await fetch(bust(endpoint.url), {
        cache: 'no-store',
        redirect: 'follow',
        headers: { Accept: 'text/calendar, text/plain, */*' },
      });
      if (!res.ok) {
        attempts.push({ ...endpoint, ok: false, reason: `HTTP ${res.status}` });
        continue;
      }
      const text = await res.text();
      if (!looksLikeCalendar(text)) {
        attempts.push({ ...endpoint, ok: false, reason: 'response was not an iCal feed' });
        continue;
      }
      attempts.push({ ...endpoint, ok: true, bytes: text.length });
      saveFeed(source.id, text, { via: endpoint.via });
      return { source, text, via: endpoint.via, fetchedAt: new Date(), stale: false, attempts };
    } catch (err) {
      // A CORS rejection surfaces here as an opaque TypeError.
      attempts.push({ ...endpoint, ok: false, reason: err?.message || String(err) });
    }
  }

  const cached = loadFeed(source.id);
  if (cached) return { source, ...cached, stale: true, attempts };
  return { source, text: null, stale: true, attempts, failed: true };
}

/**
 * Fetch every enabled calendar, in parallel. One dead feed must not take the
 * others down with it, so failures come back as entries rather than throws.
 */
export async function fetchAllFeeds(cfg) {
  const sources = calendarSources(cfg).filter((s) => s.enabled);
  if (!sources.length) throw new CalendarError('No calendars are configured yet.', []);

  const results = await Promise.all(sources.map((s) => fetchOne(s, cfg)));
  const usable = results.filter((r) => r.text);

  if (!usable.length) {
    throw new CalendarError(
      'Could not reach any calendar, and there is no cached copy.',
      results.flatMap((r) => r.attempts.map((a) => ({ ...a, label: r.source.label }))),
    );
  }
  return results;
}

/* ---------- parsing ------------------------------------------------------- */

function registerTimezones(vcalendar) {
  for (const vtz of vcalendar.getAllSubcomponents('vtimezone')) {
    try {
      const tzid = vtz.getFirstPropertyValue('tzid');
      if (!tzid || ICAL.TimezoneService.has(tzid)) continue;
      ICAL.TimezoneService.register(tzid, new ICAL.Timezone({ tzid, component: vtz }));
    } catch (err) {
      console.warn('[docket] skipped a VTIMEZONE block:', err);
    }
  }
}

function textOf(component, name) {
  const v = component.getFirstPropertyValue(name);
  if (v == null) return '';
  return typeof v === 'string' ? v : String(v);
}

function toItem(details, event, ownerEvent, source) {
  const component = (ownerEvent || event).component;
  const startDate = details.startDate;
  const allDay = !!(startDate && startDate.isDate);
  const start = details.startDate.toJSDate();
  let end = details.endDate ? details.endDate.toJSDate() : new Date(start);
  if (end < start) end = new Date(start);

  const item = {
    uid: event.uid || '',
    key: `${source ? source.id : ''}|${event.uid}|${start.toISOString()}`,
    title: (details.item?.summary ?? event.summary ?? '').trim() || '(untitled)',
    description: (details.item?.description ?? event.description ?? '').trim(),
    location: (details.item?.location ?? event.location ?? '').trim(),
    url: textOf(component, 'url'),
    start,
    end,
    allDay,
    transparent: textOf(component, 'transp').toUpperCase() === 'TRANSPARENT',
    status: textOf(component, 'status').toUpperCase(),
    recurring: event.isRecurring(),
    calendar: source ? source.label : null,
    calendarId: source ? source.id : null,
  };
  item.area = areaFor(item, source ? source.area : null);
  return item;
}

/**
 * Parse one feed and expand every occurrence overlapping [windowStart, windowEnd).
 * Handles VTIMEZONE, RRULE, EXDATE and RECURRENCE-ID overrides.
 */
export function parseEvents(icsText, windowStart, windowEnd, cfg = {}, source = null) {
  const vcalendar = new ICAL.Component(ICAL.parse(icsText));
  registerTimezones(vcalendar);

  const vevents = vcalendar.getAllSubcomponents('vevent');
  const masters = [];
  const exceptions = [];

  for (const ve of vevents) {
    let event;
    try {
      event = new ICAL.Event(ve);
    } catch (err) {
      console.warn('[docket] skipped an unparseable VEVENT:', err);
      continue;
    }
    if (event.isRecurrenceException()) exceptions.push(event);
    else masters.push(event);
  }

  const byUid = new Map();
  for (const m of masters) if (m.uid) byUid.set(m.uid, m);

  const orphans = [];
  for (const ex of exceptions) {
    const master = byUid.get(ex.uid);
    if (master) {
      try {
        master.relateException(ex);
        continue;
      } catch (err) {
        console.warn('[docket] could not attach a recurrence override:', err);
      }
    }
    // A moved occurrence whose master lives outside this feed still matters.
    orphans.push(ex);
  }

  const items = [];
  const cap = cfg.maxOccurrenceIterations || 15000;
  // Unary + on every side: Date + 1 would concatenate into a string.
  const overlaps = (start, end) =>
    +start < +windowEnd && Math.max(+end, +start + 1) > +windowStart;

  const pushSingle = (event) => {
    const details = {
      startDate: event.startDate,
      endDate: event.endDate,
      item: event,
      recurrenceId: event.recurrenceId,
    };
    const item = toItem(details, event, null, source);
    if (overlaps(item.start, item.end)) items.push(item);
  };

  for (const event of masters) {
    if (!event.isRecurring()) {
      pushSingle(event);
      continue;
    }

    let iterator;
    try {
      iterator = event.iterator();
    } catch (err) {
      console.warn('[docket] could not expand a repeating event:', event.summary, err);
      pushSingle(event);
      continue;
    }

    let next;
    let steps = 0;
    while ((next = iterator.next())) {
      if (++steps > cap) {
        console.warn(`[docket] stopped expanding "${event.summary}" after ${cap} occurrences`);
        break;
      }
      let details;
      try {
        details = event.getOccurrenceDetails(next);
      } catch (err) {
        console.warn('[docket] bad occurrence skipped:', err);
        continue;
      }
      const occStart = details.startDate.toJSDate();
      if (occStart >= windowEnd) break;              // iterator is chronological
      const occEnd = details.endDate ? details.endDate.toJSDate() : occStart;
      if (!overlaps(occStart, occEnd)) continue;      // still catching up to the window
      items.push(toItem(details, event, details.item, source));
    }
  }

  for (const ex of orphans) pushSingle(ex);

  const deduped = new Map();
  for (const item of items) deduped.set(item.key, item);
  return [...deduped.values()];
}

/** Parse every fetched feed and merge into one sorted list. */
export function parseAllFeeds(feeds, windowStart, windowEnd, cfg) {
  const all = [];
  const problems = [];

  for (const feed of feeds) {
    if (!feed.text) {
      problems.push({ label: feed.source.label, reason: 'unreachable, no cached copy' });
      continue;
    }
    try {
      all.push(...parseEvents(feed.text, windowStart, windowEnd, cfg, feed.source));
    } catch (err) {
      console.warn(`[docket] could not parse "${feed.source.label}":`, err);
      problems.push({ label: feed.source.label, reason: 'feed did not parse' });
    }
  }

  // The same event subscribed on two calendars shouldn't render twice.
  const seen = new Map();
  for (const item of all) {
    const dupKey = `${item.title}|${+item.start}|${+item.end}`;
    if (!seen.has(dupKey)) seen.set(dupKey, item);
  }

  const items = [...seen.values()].sort((a, b) => {
    if (a.allDay !== b.allDay) return a.allDay ? -1 : 1;
    return a.start - b.start || a.end - b.end || a.title.localeCompare(b.title);
  });

  return { items, problems };
}
