/* Wiring. State lives here; calendar.js fetches, render.js draws, local.js remembers. */

import { CONFIG as BASE } from '../config.js';
import { fetchAllFeeds, parseAllFeeds, CalendarError } from './calendar.js';
import { configureFormatting, startOfDay, addDays } from './util.js';
import { bucketByDay, renderMonth, renderRail, renderStatus } from './render.js';
import { setDay, exportAll } from './local.js';
import { computeFocus, renderCountdownRing } from './countdown.js';

/* config.local.js holds the secret iCal URLs and is git-ignored. It's optional:
   without it the app still runs on whatever is in config.js. */
let CONFIG = BASE;
try {
  const local = await import('../config.local.js');
  if (local?.CONFIG) CONFIG = { ...BASE, ...local.CONFIG };
} catch (err) {
  // serve.py returns an empty module when the file simply doesn't exist, so
  // reaching this means the file IS there and is broken. Say so loudly —
  // silently falling back to base config would look like "my calendars are
  // configured but nothing shows up", which is miserable to debug.
  console.error('[grimoire] config.local.js failed to load — check it for syntax errors:', err);
}

configureFormatting(CONFIG);

/* How far either side of today to expand recurring events. Twelve months
   forward covers the academic year; two back is enough to look at what
   happened last quarter without carrying years of expansion cost. */
const WINDOW_BACK_DAYS = 62;
const WINDOW_FWD_DAYS = 366;

const state = {
  now: new Date(),
  cursor: startOfDay(new Date()),   // which month the grid is showing
  selected: startOfDay(new Date()),
  buckets: new Map(),
  items: [],
  monthDetail: CONFIG.monthDetail || 'dots',
};

const els = {
  month: document.getElementById('month'),
  rail: document.getElementById('rail'),
  status: document.getElementById('status'),
  skyPhoto: document.querySelector('.sky-photo'),
  countdown: document.getElementById('countdown'),
};

function draw() {
  renderMonth(els.month, state);
  renderRail(els.rail, state);
}

/* The ring ticks on its own second-by-second clock. Folding it into draw()
   would either redraw the whole month/rail every second (wasteful, and it
   would steal focus out of the note textarea while you're typing) or leave it
   stale between the 60s "did the day roll over" ticks — a countdown that's a
   minute behind isn't a countdown. */
function drawCountdown() {
  const now = new Date();
  renderCountdownRing(els.countdown, computeFocus(state.items, now), now);
}

/* ---------------------------------------------------------------------------
   Sync
   -------------------------------------------------------------------------- */
async function sync() {
  renderStatus(els.status, { tone: 'warn', message: 'Reading the sky…' });

  const windowStart = addDays(startOfDay(new Date()), -WINDOW_BACK_DAYS);
  const windowEnd = addDays(startOfDay(new Date()), WINDOW_FWD_DAYS);

  try {
    const feeds = await fetchAllFeeds(CONFIG);
    const { items, problems } = parseAllFeeds(feeds, windowStart, windowEnd, CONFIG);

    state.items = items;
    state.buckets = bucketByDay(items);
    draw();
    drawCountdown();

    const cached = feeds.filter((f) => f.via === 'cache').length;

    // Only the areas this calendar actually uses, most-used first, so the key
    // reflects your life rather than areas.js's full vocabulary.
    const counts = new Map();
    for (const item of items) {
      if (item.area) counts.set(item.area, (counts.get(item.area) || 0) + 1);
    }
    const areas = [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([a]) => a);

    if (problems.length) {
      renderStatus(els.status, {
        tone: 'warn',
        message: `${items.length} events · ${problems.length} feed${problems.length === 1 ? '' : 's'} unavailable`,
        detail: problems.map((p) => p.label).join(', '),
        areas,
      });
    } else {
      renderStatus(els.status, {
        tone: 'ok',
        message: `${items.length} events synced`,
        detail: cached ? `${cached} from cache` : new Date().toLocaleTimeString(),
        areas,
      });
    }
  } catch (err) {
    // A dead feed must not blank the calendar — the moon, the grid and every
    // note you've written are all still perfectly usable offline.
    state.buckets = new Map();
    draw();
    renderStatus(els.status, {
      tone: 'err',
      message: err instanceof CalendarError ? err.message : 'Sync failed',
      detail: 'notes and moon phases still work',
    });
    console.warn('[grimoire] sync failed:', err);
  }
}

/* ---------------------------------------------------------------------------
   Events
   -------------------------------------------------------------------------- */
els.month.addEventListener('click', (e) => {
  const nav = e.target.closest('[data-nav]');
  if (nav) {
    const delta = Number(nav.dataset.nav);
    state.cursor = delta === 0
      ? startOfDay(new Date())
      : new Date(state.cursor.getFullYear(), state.cursor.getMonth() + delta, 1);
    if (delta === 0) state.selected = startOfDay(new Date());
    draw();
    return;
  }

  const cell = e.target.closest('.day');
  if (cell && !cell.classList.contains('pad')) {
    state.selected = new Date(cell.dataset.date);
    draw();
  }
});

els.rail.addEventListener('click', (e) => {
  const mood = e.target.closest('[data-mood]');
  if (mood) {
    // Clicking the active mood clears it, so a mis-tap is one click to undo.
    const pressed = mood.getAttribute('aria-pressed') === 'true';
    const box = document.getElementById('note-box');
    setDay(state.selected, { note: box?.value || '', mood: pressed ? null : mood.dataset.mood });
    draw();
    return;
  }

  if (e.target.closest('[data-action="save-note"]')) {
    const box = document.getElementById('note-box');
    const active = els.rail.querySelector('.mood[aria-pressed="true"]');
    setDay(state.selected, { note: box?.value || '', mood: active?.dataset.mood || null });
    draw();
  }
});

document.addEventListener('keydown', (e) => {
  if (e.target.matches('textarea, input')) return;

  const jump = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key];
  if (jump) {
    e.preventDefault();
    state.selected = addDays(state.selected, jump);
    // Follow the selection across a month boundary.
    if (state.selected.getMonth() !== state.cursor.getMonth() ||
        state.selected.getFullYear() !== state.cursor.getFullYear()) {
      state.cursor = new Date(state.selected.getFullYear(), state.selected.getMonth(), 1);
    }
    draw();
  } else if (e.key === 't' || e.key === 'T') {
    state.cursor = startOfDay(new Date());
    state.selected = startOfDay(new Date());
    draw();
  } else if (e.key === 'r' || e.key === 'R') {
    sync();
  }
});

/* --- toolbar -------------------------------------------------------------- */
document.getElementById('toolbar').addEventListener('click', (e) => {
  const btn = e.target.closest('button');
  if (!btn) return;

  if (btn.dataset.action === 'foil') {
    const next = document.body.dataset.foil === 'rose' ? 'gold' : 'rose';
    document.body.dataset.foil = next;
    localStorage.setItem('grimoire.foil', next);
    btn.setAttribute('aria-pressed', String(next === 'rose'));
  }

  if (btn.dataset.action === 'sync') sync();

  if (btn.dataset.action === 'export') {
    // Your notes are the one thing here that exists nowhere else. One click out.
    const blob = new Blob([JSON.stringify(exportAll(), null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `grimoire-notes-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  }
});

/* --- restore preferences -------------------------------------------------- */
const savedFoil = localStorage.getItem('grimoire.foil');
if (savedFoil) {
  document.body.dataset.foil = savedFoil;
  document.querySelector('[data-action="foil"]')?.setAttribute('aria-pressed', String(savedFoil === 'rose'));
}

if (CONFIG.wallpaper) {
  els.skyPhoto.style.backgroundImage = `url("${CONFIG.wallpaper}")`;
  els.skyPhoto.style.opacity = String(CONFIG.wallpaperOpacity ?? 0.30);
}

/* Another window (the installed app vs. a tab) saved a note — local.js has
   already dropped its cache by the time this runs, so a redraw is enough. */
window.addEventListener('storage', (event) => {
  if (event.key === null || String(event.key).startsWith('grimoire.local')) draw();
});

/* Keep "today" honest across midnight without a reload. */
setInterval(() => {
  const now = new Date();
  const rolled = now.toDateString() !== state.now.toDateString();
  state.now = now;
  if (rolled) draw();
}, 60_000);

/* The countdown ring, on its own clock. */
setInterval(drawCountdown, 1_000);

/* Register the offline cache only when this is served from a real host.

   Running locally, every file is already on your disk behind your own Python
   server — there is nothing to be offline from, and a cache-first worker would
   happily serve you the PREVIOUS version of dayMark() after you edit it. That
   failure is silent and maddening. The worker only earns its keep if this ever
   gets deployed to a URL you open on your phone, so that's when it turns on. */
const isLocal = ['localhost', '127.0.0.1', ''].includes(location.hostname);
if ('serviceWorker' in navigator && !isLocal) {
  navigator.serviceWorker.register('./sw.js').catch(() => { /* offline cache is optional */ });
} else if ('serviceWorker' in navigator) {
  // Clean up any worker left behind by an earlier version of this file.
  navigator.serviceWorker.getRegistrations().then((rs) => rs.forEach((r) => r.unregister()));
}

draw();
drawCountdown();
sync();
