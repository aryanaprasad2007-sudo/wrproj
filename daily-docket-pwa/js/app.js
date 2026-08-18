/* Boot, state, and the render loop. */

import { loadSettings, readOverrides, writeOverrides, clearOverrides } from './settings.js';
import { fetchAllFeeds, parseAllFeeds, calendarSources, CalendarError } from './calendar.js';
import { applyFilters, forDay, splitByNow } from './filters.js';
import { pickSpotlight, pickFocus } from './importance.js';
import { addCountdown, clearCountdowns } from './countdown.js';
import { clearFeeds, hasAnyFeed, saveView, loadView } from './store.js';
import {
  configureFormatting, startOfDay, addDays, fmtDayLabel, fmtTime,
  greeting, motivation, relTime,
} from './util.js';
import * as R from './render.js';

const $ = (sel) => document.querySelector(sel);

const state = {
  cfg: null,
  items: [],
  dropped: [],
  feeds: [],
  problems: [],
  error: null,
  view: 'today',
  loading: false,
};

let refreshTimer = null;
let rolloverTimer = null;
let deferredInstall = null;

/* ---------- data ---------------------------------------------------------- */

async function refresh({ silent = false } = {}) {
  if (state.loading) return;
  state.loading = true;
  if (!silent) setSyncLine('Syncing…', 'busy');

  try {
    const feeds = await fetchAllFeeds(state.cfg);
    const now = new Date();
    const windowStart = startOfDay(now);
    const windowEnd = addDays(windowStart, 2);

    const { items, problems } = parseAllFeeds(feeds, windowStart, windowEnd, state.cfg);
    const { kept, dropped } = applyFilters(items, state.cfg);

    state.feeds = feeds;
    state.problems = problems;
    state.items = kept;
    state.dropped = dropped;
    state.error = null;
  } catch (err) {
    state.error = err;
    // Keep showing what we had, but stop claiming it's fresh.
    state.feeds = state.feeds.map((f) => ({ ...f, stale: true }));
    if (!(err instanceof CalendarError)) console.error('[docket]', err);
  } finally {
    state.loading = false;
    render();
  }
}

/* ---------- rendering ----------------------------------------------------- */

function setSyncLine(text, kind = '') {
  const el = $('#syncline');
  el.textContent = text;
  el.className = `syncline ${kind}`;
}

function syncSummary() {
  const live = state.feeds.filter((f) => f.text);
  if (!live.length) return ['Not synced yet', 'warn'];

  const newest = live.reduce((a, f) => (+f.fetchedAt > +a ? f.fetchedAt : a), live[0].fetchedAt);
  const stale = live.filter((f) => f.stale);
  const dead = state.feeds.filter((f) => !f.text);
  const total = state.feeds.length;

  if (stale.length === live.length) {
    return [`📴 Offline — showing the sync from ${fmtTime(newest)}`, 'warn'];
  }
  if (stale.length || dead.length) {
    const names = [...stale, ...dead].map((f) => f.source.label).join(', ');
    return [`⚠️ ${live.length - stale.length}/${total} calendars fresh · stale: ${names}`, 'warn'];
  }
  const plural = total === 1 ? 'calendar' : 'calendars';
  return [`✓ Synced ${relTime(newest)} · ${total} ${plural}`, 'ok'];
}

function render() {
  clearCountdowns();

  const now = new Date();
  const g = greeting(now, state.cfg.ownerName);
  $('#greeting').textContent = `${g.emoji} ${g.text}`;
  $('#motivation').textContent = motivation(now);

  const shell = $('#shell');

  if (state.error && !state.items.length) {
    shell.hidden = true;
    const fallback = $('#fallback');
    fallback.hidden = false;
    const configured = calendarSources(state.cfg).some((s) => s.enabled && s.url);
    if (!configured && !hasAnyFeed()) R.renderSetupNeeded(fallback);
    else R.renderError(fallback, state.error.message, state.error.attempts);
    setSyncLine('Not synced', 'warn');
    return;
  }

  $('#fallback').hidden = true;
  shell.hidden = false;

  const [syncText, syncKind] = syncSummary();
  setSyncLine(syncText, syncKind);

  const todayStart = startOfDay(now);
  const tomorrowStart = addDays(todayStart, 1);
  const dayAfter = addDays(todayStart, 2);

  renderToday(now, todayStart, tomorrowStart);
  renderTomorrow(now, tomorrowStart, dayAfter);

  showView(state.view);
}

function renderToday(now, dayStart, dayEnd) {
  const { allDay, timed } = forDay(state.items, dayStart, dayEnd, { includeRunning: true });
  const { ahead, done } = splitByNow(timed, now);

  R.renderDayHeading($('#today-heading'), dayStart, true);
  R.renderChips($('#today-chips'), allDay, state.cfg);

  const pick = pickSpotlight(ahead, allDay, now, state.cfg);
  const hooks = R.renderSpotlight($('#today-spotlight'), pick, {
    mode: 'today',
    now,
    dayLabel: 'today',
    cfg: state.cfg,
  });
  if (hooks && pick?.target) {
    addCountdown('today-spotlight', {
      ...hooks,
      target: pick.target.at,
      from: dayStart,
      onExpire: () => setTimeout(() => refresh({ silent: true }), 1500),
    });
  }

  R.renderAhead($('#today-ahead'), ahead, now, pick?.item?.key, state.cfg, timed.length);
  $('#today-ahead-count').textContent = ahead.length ? `(${ahead.length})` : '';
  R.renderDone($('#today-done'), done, { collapsed: state.cfg.showDoneCollapsed, cfg: state.cfg });
  R.renderProgress($('#today-progress'), { done: done.length, total: timed.length });
}

function renderTomorrow(now, dayStart, dayEnd) {
  const { allDay, timed } = forDay(state.items, dayStart, dayEnd);

  R.renderDayHeading($('#tomorrow-heading'), dayStart, false);
  R.renderChips($('#tomorrow-chips'), allDay, state.cfg);

  const pick = pickFocus(timed, allDay, dayStart, state.cfg);
  const hooks = R.renderSpotlight($('#tomorrow-focus'), pick, {
    mode: 'tomorrow',
    now,
    dayLabel: fmtDayLabel(dayStart),
    cfg: state.cfg,
  });
  if (hooks && pick?.target) {
    addCountdown('tomorrow-focus', { ...hooks, target: pick.target.at, from: now });
  }

  R.renderTimeline($('#tomorrow-timeline'), timed, state.cfg);
  $('#tomorrow-count').textContent = timed.length ? `(${timed.length})` : '';
}

function showView(view) {
  state.view = view;
  saveView(view);
  for (const tab of document.querySelectorAll('[role="tab"]')) {
    const active = tab.dataset.view === view;
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
  }
  $('#view-today').hidden = view !== 'today';
  $('#view-tomorrow').hidden = view !== 'tomorrow';
  $('#tabs').dataset.active = view;
}

/* ---------- timers -------------------------------------------------------- */

function scheduleRefresh() {
  clearInterval(refreshTimer);
  const mins = Math.max(1, state.cfg.refreshMinutes || 15);
  refreshTimer = setInterval(() => refresh({ silent: true }), mins * 60000);
}

/** Re-render the instant the calendar day flips, so "today" stays honest. */
function scheduleRollover() {
  clearTimeout(rolloverTimer);
  const now = new Date();
  const next = addDays(startOfDay(now), 1);
  rolloverTimer = setTimeout(() => {
    refresh({ silent: true });
    scheduleRollover();
  }, Math.max(1000, +next - +now + 2000));
}

/* ---------- settings panel ------------------------------------------------ */

function openSettings() {
  const dlg = $('#settings');
  const ov = readOverrides();
  $('#set-name').value = ov.ownerName ?? '';
  $('#set-relay').checked = !!(ov.useCorsRelay ?? state.cfg.useCorsRelay);
  $('#set-24h').checked = (ov.hour12 ?? state.cfg.hour12) === false;

  /* A feed with no URL still fetches fine — the proxy hands back an empty
     calendar so the others keep working — so "reached it" is not the same as
     "set up". Don't show green for a calendar that has nothing behind it. */
  const dotFor = (s, feed) => {
    if (!s.enabled) return 'off';
    if (!feed?.text) return 'dead';
    if (!s.url && !/BEGIN:VEVENT/.test(feed.text)) return 'unset';
    return feed.stale ? 'stale' : 'ok';
  };

  const urls = ov.calendarUrls || {};
  $('#set-calendars').innerHTML = calendarSources(state.cfg)
    .map((s) => {
      const feed = state.feeds.find((f) => f.source.id === s.id);
      const dot = dotFor(s, feed);
      const label = s.label.replace(/[&<>"]/g, '');
      return `
        <label class="cal-row">
          <span class="cal-name"><i class="cal-dot is-${dot}"></i>${label}</span>
          <input type="url" data-cal="${s.id}" inputmode="url" spellcheck="false"
                 autocomplete="off" placeholder="${s.url ? 'configured in config.js' : 'paste secret iCal URL'}"
                 value="${(urls[s.id] || '').replace(/"/g, '&quot;')}" />
        </label>`;
    })
    .join('');

  dlg.showModal();
}

async function saveSettings(event) {
  event.preventDefault();

  const calendarUrls = {};
  for (const input of document.querySelectorAll('#set-calendars input[data-cal]')) {
    const v = input.value.trim();
    if (v) calendarUrls[input.dataset.cal] = v;
  }

  writeOverrides({
    calendarUrls: Object.keys(calendarUrls).length ? calendarUrls : null,
    ownerName: $('#set-name').value.trim() || null,
    useCorsRelay: $('#set-relay').checked || null,
    hour12: $('#set-24h').checked ? false : null,
  });

  $('#settings').close();
  state.cfg = await loadSettings();
  configureFormatting(state.cfg);
  await refresh();
}

/* ---------- wiring -------------------------------------------------------- */

function wire() {
  $('#tabs').addEventListener('click', (e) => {
    const tab = e.target.closest('[role="tab"]');
    if (tab) showView(tab.dataset.view);
  });

  $('#tabs').addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    showView(state.view === 'today' ? 'tomorrow' : 'today');
    document.querySelector(`[data-view="${state.view}"]`).focus();
  });

  $('#refresh').addEventListener('click', () => refresh());
  $('#open-settings').addEventListener('click', openSettings);
  $('#settings-form').addEventListener('submit', saveSettings);
  $('#set-close').addEventListener('click', () => $('#settings').close());

  $('#set-reset').addEventListener('click', async () => {
    clearOverrides();
    clearFeeds();
    $('#settings').close();
    state.cfg = await loadSettings();
    configureFormatting(state.cfg);
    await refresh();
  });

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible' || !state.feeds.length) return;
    const newest = state.feeds
      .filter((f) => f.fetchedAt)
      .reduce((a, f) => Math.max(a, +f.fetchedAt), 0);
    if (Date.now() - newest > 60000) refresh({ silent: true });
    else render();
  });

  window.addEventListener('online', () => refresh({ silent: true }));
  window.addEventListener('offline', () => setSyncLine('📴 Offline', 'warn'));

  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredInstall = e;
    $('#install').hidden = false;
  });

  $('#install').addEventListener('click', async () => {
    if (!deferredInstall) return;
    deferredInstall.prompt();
    await deferredInstall.userChoice;
    deferredInstall = null;
    $('#install').hidden = true;
  });

  window.addEventListener('appinstalled', () => {
    $('#install').hidden = true;
  });
}

async function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return;
  try {
    // sw.js sits at the app root, one level up from /js — that also makes the
    // scope the whole app, which is what we want for a subpath deploy.
    const swUrl = new URL('../sw.js', import.meta.url);
    await navigator.serviceWorker.register(swUrl, { scope: new URL('./', swUrl).pathname });
  } catch (err) {
    console.warn('[docket] service worker not registered:', err);
  }
}

async function main() {
  state.cfg = await loadSettings();
  configureFormatting(state.cfg);

  // ?view=tomorrow powers the manifest shortcut; otherwise resume last choice.
  const requested = new URLSearchParams(location.search).get('view');
  const remembered = requested || loadView();
  state.view = remembered === 'tomorrow' ? 'tomorrow' : 'today';

  wire();
  showView(state.view);
  await refresh();
  scheduleRefresh();
  scheduleRollover();
  registerServiceWorker();

  // Handy when tuning the filters: docket.dropped shows what got hidden.
  window.docket = {
    state,
    refresh,
    get dropped() { return state.dropped.map((d) => `${d.rejected.reason}: ${d.title}`); },
    get feeds() {
      return state.feeds.map((f) =>
        `${f.source.label}: ${f.text ? `${f.text.length}b via ${f.via}${f.stale ? ' (stale)' : ''}` : 'FAILED'}`);
    },
  };
}

main();
