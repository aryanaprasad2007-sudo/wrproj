/* Rendering. Pure functions of (state) → DOM; no fetching, no storage.

   Everything is built with textContent rather than innerHTML wherever a value
   comes from a calendar feed. Event titles are attacker-controllable in the
   sense that anyone who can put an event on a subscribed calendar controls that
   string, and this app runs with the same origin as your stored notes. */

import { fmtTime, startOfDay, addDays } from './util.js';
import { moonPhase, illumination } from './moon.js';
import { getDay, dayMark, MOODS } from './local.js';
import { AREA_COLOR } from './areas.js';

const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

/* How a day cell summarises its events.

   'dots' — one area-coloured pip per event. This is the default because a real
            routine runs 8-12 events a day, and at seven columns a title chip is
            ~90px wide: "9:45 pm 🌙 Wind Down" truncates to "9:45 pm …" and every
            cell becomes an identical grey wall. Dots show the SHAPE of a week —
            how full, and of what — which is the job of a month view. The rail
            carries the detail for whichever day you click.

   'chips' — the titles, truncated. Only readable on a sparse calendar.

   Set CONFIG.monthDetail to switch. */
const CHIPS_PER_DAY = 3;
const DOTS_PER_DAY = 8;

const sameDay = (a, b) =>
  a.getFullYear() === b.getFullYear() &&
  a.getMonth() === b.getMonth() &&
  a.getDate() === b.getDate();

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

/* ---------------------------------------------------------------------------
   Bucketing events by day.

   An event that spans midnight (or several days) has to appear on every day it
   touches, not just its start date — otherwise a Friday-to-Sunday trip vanishes
   from Saturday. All-day events in iCal use an EXCLUSIVE end date, so a
   one-day all-day event ends at midnight the next morning; walking to `end`
   inclusive would paint an extra day.
   -------------------------------------------------------------------------- */
export function bucketByDay(items) {
  const buckets = new Map();

  for (const item of items) {
    let cursor = startOfDay(item.start);
    const last = startOfDay(new Date(item.end.getTime() - 1));

    // A guard against a malformed feed with an absurd end date locking the UI.
    for (let i = 0; cursor <= last && i < 400; i += 1) {
      const key = cursor.toDateString();
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key).push(item);
      cursor = addDays(cursor, 1);
    }
  }
  return buckets;
}

/* ---------------------------------------------------------------------------
   Month grid
   -------------------------------------------------------------------------- */
export function renderMonth(root, state) {
  const { cursor, buckets, selected, now } = state;
  root.replaceChildren();

  const year = cursor.getFullYear();
  const month = cursor.getMonth();

  const head = el('div', 'month-head');
  const titleWrap = el('div');
  titleWrap.append(el('h2', 'month-title', `${MONTHS[month]} ${year}`));

  const monthItems = [...buckets.entries()]
    .filter(([key]) => {
      const d = new Date(key);
      return d.getFullYear() === year && d.getMonth() === month;
    })
    .reduce((sum, [, list]) => sum + list.length, 0);
  titleWrap.append(el('div', 'month-meta', `${monthItems} events this month`));
  head.append(titleWrap);

  const nav = el('div', 'month-nav');
  for (const [label, delta, aria] of [['‹', -1, 'Previous month'], ['Today', 0, 'Jump to today'], ['›', 1, 'Next month']]) {
    const btn = el('button', delta === 0 ? 'btn' : 'btn icon', label);
    btn.type = 'button';
    btn.setAttribute('aria-label', aria);
    btn.dataset.nav = String(delta);
    nav.append(btn);
  }
  head.append(nav);
  root.append(head);

  const dowRow = el('div', 'dow-row');
  for (const d of DOW) dowRow.append(el('span', null, d.slice(0, 1)));
  root.append(dowRow);

  const grid = el('div', 'day-grid');

  const first = new Date(year, month, 1);
  const gridStart = addDays(startOfDay(first), -first.getDay());

  // Six rows always. A fixed grid height stops the whole layout jumping when
  // you page from a 5-row month into a 6-row one.
  for (let i = 0; i < 42; i += 1) {
    const date = addDays(gridStart, i);
    const inMonth = date.getMonth() === month;
    const dayEvents = buckets.get(date.toDateString()) || [];

    const cell = el('button', 'day');
    cell.type = 'button';
    cell.dataset.date = date.toISOString();
    if (!inMonth) cell.classList.add('pad');
    if (sameDay(date, now)) cell.classList.add('today');
    if (selected && sameDay(date, selected)) cell.classList.add('selected');

    const phase = moonPhase(date);
    const top = el('div', 'day-top');
    top.append(el('span', 'day-num', String(date.getDate())));
    const moon = el('span', 'moon', phase.glyph);
    moon.title = phase.name;
    top.append(moon);
    cell.append(top);

    const label = `${DOW[date.getDay()]} ${MONTHS[date.getMonth()]} ${date.getDate()}, ` +
      `${dayEvents.length} event${dayEvents.length === 1 ? '' : 's'}, ${phase.name}`;
    cell.setAttribute('aria-label', label);

    if (dayEvents.length) {
      cell.append(state.monthDetail === 'chips'
        ? chipsFor(dayEvents)
        : dotsFor(dayEvents));
    }

    // dayMark may return a bare glyph string or {glyph, color, title}. Both are
    // supported so the function stays trivial to rewrite — a one-line `return
    // '★'` must keep working.
    const mark = dayMark(getDay(date), dayEvents, date);
    const { glyph, color, title } = typeof mark === 'string' ? { glyph: mark } : (mark || {});
    if (glyph) {
      const node = el('span', 'day-mark', glyph);
      if (color) node.style.color = color;
      if (title) node.title = title;
      cell.append(node);
    }

    grid.append(cell);
  }

  root.append(grid);
}

/** Truncated titles. Fine on a sparse calendar, mush on a busy one. */
function chipsFor(dayEvents) {
  const list = el('div', 'day-events');
  for (const item of dayEvents.slice(0, CHIPS_PER_DAY)) {
    // No time prefix here — "9:45 pm " eats most of a 90px cell and the rail
    // shows the time anyway the moment you click the day.
    const chip = el('span', 'ev', item.title);
    chip.title = item.title;
    list.append(chip);
  }
  if (dayEvents.length > CHIPS_PER_DAY) {
    list.append(el('span', 'ev more', `+${dayEvents.length - CHIPS_PER_DAY} more`));
  }
  return list;
}

/** One area-coloured pip per event, so a month reads as a heat map of your life. */
function dotsFor(dayEvents) {
  const row = el('div', 'day-dots');

  for (const item of dayEvents.slice(0, DOTS_PER_DAY)) {
    const dot = el('span', 'dot-ev');
    dot.style.background = AREA_COLOR[item.area] || 'var(--violet)';
    dot.title = item.allDay ? item.title : `${fmtTime(item.start)} — ${item.title}`;
    row.append(dot);
  }

  if (dayEvents.length > DOTS_PER_DAY) {
    row.append(el('span', 'dot-more', `+${dayEvents.length - DOTS_PER_DAY}`));
  }
  return row;
}

/* ---------------------------------------------------------------------------
   Agenda rail — the selected day, in detail
   -------------------------------------------------------------------------- */
export function renderRail(root, state) {
  const { selected, buckets, now } = state;
  root.replaceChildren();

  const date = selected || now;
  const dayEvents = buckets.get(date.toDateString()) || [];
  const phase = moonPhase(date);

  /* --- events --------------------------------------------------------- */
  const card = el('section', 'panel rail-card');
  const head = el('div', 'rail-head');
  const titleWrap = el('div');
  titleWrap.append(el('h2', 'rail-title', sameDay(date, now)
    ? 'Today'
    : `${DOW[date.getDay()]} ${date.getDate()} ${MONTHS[date.getMonth()].slice(0, 3)}`));
  titleWrap.append(el('div', 'rail-sub',
    `${phase.name} · ${Math.round(illumination(date) * 100)}% lit`));
  head.append(titleWrap);
  head.append(el('div', 'rail-sub', `${dayEvents.length} ev`));
  card.append(head);

  if (!dayEvents.length) {
    card.append(el('p', 'empty', 'Nothing written for this day.'));
  } else {
    const agenda = el('div', 'agenda');
    for (const item of dayEvents) {
      const slot = el('div', 'slot');
      if (item.end < now) slot.classList.add('past');
      if (item.start <= now && item.end > now) slot.classList.add('now');

      slot.append(el('div', 'slot-time', item.allDay ? 'all day' : fmtTime(item.start)));

      const body = el('div');
      body.append(el('div', 'slot-title', item.title));
      const meta = [item.calendar, item.location].filter(Boolean).join(' · ');
      if (meta) body.append(el('div', 'slot-meta', meta));
      slot.append(body);

      agenda.append(slot);
    }
    card.append(agenda);
  }
  root.append(card);

  /* --- the local layer ------------------------------------------------- */
  root.append(renderNoteCard(date));
}

function renderNoteCard(date) {
  const record = getDay(date);

  const card = el('section', 'panel rail-card');
  const head = el('div', 'rail-head');
  head.append(el('h2', 'rail-title', 'Your margin'));
  head.append(el('div', 'rail-sub', record ? 'saved' : 'empty'));
  card.append(head);

  const label = el('label', 'note-label', 'How the day actually went');
  label.htmlFor = 'note-box';
  card.append(label);

  const box = el('textarea', 'note-box');
  box.id = 'note-box';
  box.placeholder = 'Never leaves this machine.';
  box.value = record?.note || '';
  card.append(box);

  const moodRow = el('div', 'mood-row');
  for (const mood of MOODS) {
    const btn = el('button', 'mood', mood.glyph);
    btn.type = 'button';
    btn.dataset.mood = mood.id;
    btn.title = mood.label;
    // Same colour the mark will be on the grid, so the picker doubles as the
    // legend for the mood mirror — no separate key needed.
    btn.style.color = mood.color;
    btn.setAttribute('aria-label', mood.label);
    btn.setAttribute('aria-pressed', String(record?.mood === mood.id));
    moodRow.append(btn);
  }
  card.append(moodRow);

  const saveRow = el('div', 'save-row');
  saveRow.append(el('span', 'save-hint', record
    ? `saved ${new Date(record.updated).toLocaleDateString()}`
    : 'unsaved'));
  const save = el('button', 'btn', 'Save');
  save.type = 'button';
  save.dataset.action = 'save-note';
  saveRow.append(save);
  card.append(saveRow);

  return card;
}

/* ---------------------------------------------------------------------------
   Status line
   -------------------------------------------------------------------------- */
export function renderStatus(root, { tone, message, detail, areas }) {
  root.className = `statusline ${tone || ''}`.trim();
  root.replaceChildren();
  root.append(el('span', 'pip'));
  root.append(el('span', null, message));

  // Key for the dot colours. Only the areas actually present get a swatch —
  // listing all seven when your calendar only uses three is noise, and an
  // unexplained colour code is just decoration.
  if (areas?.length) {
    const key = el('span', 'legend');
    for (const area of areas) {
      const item = el('span', 'legend-item');
      const swatch = el('span', 'legend-dot');
      swatch.style.background = AREA_COLOR[area] || 'var(--violet)';
      item.append(swatch, el('span', null, area));
      key.append(item);
    }
    root.append(key);
  }

  if (detail) {
    const right = el('span', 'spacer');
    right.textContent = detail;
    root.append(right);
  }
}
