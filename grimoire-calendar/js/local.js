/* The local layer — the "hybrid" half of this calendar.

   Google Calendar stays the single source of truth for EVENTS. Nothing in here
   ever writes back to Google. What lives here is the stuff you'd never put on a
   shared calendar: a line about how the day actually went, a mood, a private
   marker. Google supplies the skeleton; this supplies the diary.

   Storage is localStorage keyed by civil date (YYYY-MM-DD), so a record is tied
   to the day you meant, not to a timestamp that shifts under a timezone change.

   Deliberately NOT stored here: tasks. Those belong in Notion's Command Center,
   and a second competing task list is exactly the failure mode to avoid. */

const KEY = 'grimoire.local.v1';

/** @typedef {{ note: string, mood: string|null, updated: number }} DayRecord */

let cache = null;

function readAll() {
  if (cache) return cache;
  try {
    cache = JSON.parse(localStorage.getItem(KEY) || '{}');
  } catch {
    // A corrupt blob shouldn't take the calendar down with it — the events are
    // the important part and they come from Google, not from here.
    console.warn('[grimoire] local layer unreadable; starting fresh');
    cache = {};
  }
  return cache;
}

function writeAll(all) {
  cache = all;
  try {
    localStorage.setItem(KEY, JSON.stringify(all));
    return true;
  } catch (err) {
    console.warn('[grimoire] could not save local layer:', err.message);
    return false;
  }
}

/* Reads are served from `cache`, which means this module would never notice a
   write made by ANOTHER window. That's a real case: the installed app and a
   browser tab are two windows over the same storage, and a note saved in one
   would stay invisible in the other until reload. The storage event fires only
   in the windows that DIDN'T make the change, which is exactly the set that
   needs to forget what it cached. app.js listens for the same event to redraw. */
window.addEventListener('storage', (event) => {
  if (event.key === KEY || event.key === null) cache = null;
});

/** Civil date key for a Date, in LOCAL time (not UTC — that would shift days). */
export function dayKey(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

/** @returns {DayRecord|null} */
export function getDay(date) {
  return readAll()[dayKey(date)] || null;
}

/** Save a day's note/mood. Passing an empty note and no mood deletes the record. */
export function setDay(date, { note = '', mood = null } = {}) {
  const all = { ...readAll() };
  const key = dayKey(date);
  const trimmed = note.trim();

  if (!trimmed && !mood) delete all[key];
  else all[key] = { note: trimmed, mood, updated: Date.now() };

  return writeAll(all);
}

/** Every stored record, for export/backup. */
export function exportAll() {
  return JSON.parse(JSON.stringify(readAll()));
}

/* The moods offered in the rail. Order is the order they render in.

   The colours matter as much as the glyphs: on the month grid these become the
   mood mirror, and a row of identically-coloured marks tells you THAT you
   logged, not WHAT you logged. Warm and bright for good days, cool and dim for
   hard ones, so a month's emotional shape is legible at a glance without
   reading a single glyph. */
export const MOODS = [
  { id: 'great', glyph: '✦', label: 'Great day',          color: '#f0c869' },
  { id: 'good',  glyph: '✧', label: 'Good day',           color: '#ff9ad5' },
  { id: 'flat',  glyph: '·', label: 'Flat',               color: '#8676ab' },
  { id: 'hard',  glyph: '☁', label: 'Hard day',           color: '#7fa8d9' },
  { id: 'note',  glyph: '❋', label: 'Worth remembering',  color: '#a77bff' },
];

/* ============================================================================
   dayMark — MOOD MIRROR (Ari's choice, 2026-08-10)

   The single small mark in the bottom-right of each day cell. This is the only
   place your private layer shows up on the month grid, so it decides what the
   calendar is for at a glance. Since the grid itself now shows event density as
   area-coloured dots, this deliberately does NOT repeat that: dots are what the
   day demanded of you, the mark is what it was actually like.

   How it reads: a marked day shows its mood glyph in that mood's colour, and an
   unmarked day shows nothing at all. The blanks are the point — moods only form
   a legible shape across a month if they aren't competing with a mark on every
   single day.

   A note saved WITHOUT a mood still gets a faint neutral pip. Without it, you'd
   write something on a Tuesday, not pick a mood, and later find no trace that
   the day held anything — the note would be invisible until you happened to
   click that exact date.

   Returning a plain string still works if you ever rewrite this; the colour is
   optional. The other two directions, if you want to switch later:

     STREAK KEEPER  mark only when a note exists, so gaps read as missed days
     LOAD GAUGE     mark by events.length — redundant now that dots exist

   @param {DayRecord|null} record  the saved note/mood for this day, if any
   @param {Array} events           this day's events, already merged and sorted
   @param {Date}  date             the day itself
   @returns {string | {glyph: string, color?: string, title?: string}}
            a glyph (optionally with a colour), or '' for no mark
   ========================================================================== */
export function dayMark(record, events, date) {
  if (!record) return '';

  const mood = MOODS.find((m) => m.id === record.mood);
  if (mood) {
    return { glyph: mood.glyph, color: mood.color, title: mood.label };
  }

  // Written on, but no mood chosen.
  return record.note ? { glyph: '·', color: 'var(--ink-faint)', title: 'Note' } : '';
}
