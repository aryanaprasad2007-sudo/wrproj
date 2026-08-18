/* Offline cache. The service worker keeps the app shell; this keeps the data.
   We stash raw .ics text per calendar rather than parsed events, so a future
   version of the parser can reinterpret an old sync. */

const PREFIX = 'grimoire.feed.v1:';
const LEGACY_KEY = 'grimoire.feed.legacy';
const VIEW_KEY = 'grimoire.view.v1';

const keyFor = (id) => PREFIX + id;

export function saveFeed(id, text, { via } = {}) {
  try {
    localStorage.setItem(keyFor(id), JSON.stringify({
      text,
      via: via || 'unknown',
      fetchedAt: new Date().toISOString(),
    }));
    return true;
  } catch (err) {
    // Quota exceeded on a very large calendar — not fatal, just no offline copy.
    console.warn(`[grimoire] could not cache "${id}":`, err);
    return false;
  }
}

export function loadFeed(id) {
  try {
    const raw = localStorage.getItem(keyFor(id));
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed?.text) return null;
    return { ...parsed, fetchedAt: new Date(parsed.fetchedAt) };
  } catch {
    return null;
  }
}

/** True if any calendar at all has a cached copy — drives the setup screen. */
export function hasAnyFeed() {
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && (k.startsWith(PREFIX) || k === LEGACY_KEY)) return true;
    }
  } catch { /* private mode */ }
  return false;
}

export function clearFeeds() {
  try {
    const doomed = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && (k.startsWith(PREFIX) || k === LEGACY_KEY)) doomed.push(k);
    }
    doomed.forEach((k) => localStorage.removeItem(k));
  } catch { /* private mode */ }
}

export function saveView(view) {
  try { localStorage.setItem(VIEW_KEY, view); } catch { /* private mode */ }
}

export function loadView() {
  try { return localStorage.getItem(VIEW_KEY); } catch { return null; }
}
