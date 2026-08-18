/* Merges config sources into one frozen settings object.
   Precedence (lowest → highest):
     DEFAULTS  →  /config.js  →  /config.local.js  →  localStorage overrides
   The localStorage layer is what the in-app ⚙ panel writes, so you can point
   the docket at a calendar from your phone without editing files. */

const OVERRIDE_KEY = 'docket.overrides.v1';

const DEFAULTS = {
  ownerName: 'friend',
  calendars: [],
  icsUrl: '',
  icsProxyPath: '/ics',
  showAreaChips: true,
  showCalendarLabels: true,
  useCorsRelay: false,
  corsRelays: [],
  ignoreTitlePrefixes: ['WR ·'],
  lenientPrefixMatch: true,
  ignoreTitlePatterns: [],
  skipTransparent: true,
  skipTransparentAllDay: false,
  skipCancelled: true,
  extraDeadlineKeywords: {},
  pinMarker: '★',
  deadlineScoreThreshold: 60,
  refreshMinutes: 15,
  hour12: true,
  timeZone: null,
  locale: null,
  showDoneCollapsed: true,
  maxOccurrenceIterations: 15000,
};

async function importConfig(path) {
  try {
    const mod = await import(path);
    return mod.CONFIG || mod.default || {};
  } catch (err) {
    // config.local.js is optional, so a missing-module error is expected.
    if (!/Failed to fetch|not found|404|Cannot find/i.test(String(err))) {
      console.warn(`[docket] could not load ${path}:`, err);
    }
    return {};
  }
}

export function readOverrides() {
  try {
    return JSON.parse(localStorage.getItem(OVERRIDE_KEY) || '{}');
  } catch {
    return {};
  }
}

export function writeOverrides(patch) {
  const next = { ...readOverrides(), ...patch };
  for (const k of Object.keys(next)) {
    if (next[k] === null || next[k] === '') delete next[k];
  }
  localStorage.setItem(OVERRIDE_KEY, JSON.stringify(next));
  return next;
}

export function clearOverrides() {
  localStorage.removeItem(OVERRIDE_KEY);
}

export async function loadSettings() {
  const base = await importConfig('../config.js');
  const local = await importConfig('../config.local.js');
  const overrides = readOverrides();
  const merged = { ...DEFAULTS, ...base, ...local, ...overrides };

  // Normalise a webcal:// address, which browsers can't fetch.
  if (merged.icsUrl) {
    merged.icsUrl = String(merged.icsUrl).trim().replace(/^webcal:\/\//i, 'https://');
  }

  // Per-calendar URLs pasted into the ⚙ panel win over the ones in config.js,
  // keyed by calendar id so re-ordering the array can't misassign them.
  const pasted = overrides.calendarUrls || {};
  merged.calendars = (merged.calendars || []).map((cal) => {
    const url = pasted[cal.id];
    return url ? { ...cal, url: url.trim().replace(/^webcal:\/\//i, 'https://') } : cal;
  });

  merged.locale = merged.locale || undefined; // undefined → Intl uses the device locale
  return Object.freeze(merged);
}
