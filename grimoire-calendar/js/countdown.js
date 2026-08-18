/* The countdown ring — a live pie-timer for whatever's happening or coming up
   next, independent of which day is selected in the grid. It rebuilds from
   scratch once a second; the widget is small enough that this is cheaper than
   the bookkeeping needed to patch it in place, and it means a redraw can never
   drift out of sync with the clock. */

import { clamp, fmtCountdown } from './util.js';

const R = 52;
const CIRC = 2 * Math.PI * R;
const SVG_NS = 'http://www.w3.org/2000/svg';

/* How long before an "upcoming" event the ring starts filling. Outside this
   window the ring just sits empty — there's nothing meaningful to show for an
   event three days out, so the timer only engages once it's actually close. */
const DEFAULT_WINDOW_MS = 4 * 60 * 60 * 1000; // 4 hours

/** The one event worth showing right now: whichever is in progress, else the
 *  soonest one still ahead. All-day events have no clock time to count down
 *  to, so they're excluded.
 *
 *  `fraction` is progress toward completion — 0 right as the tracked moment
 *  opens (the event starting, or the countdown window opening), 1 right as it
 *  closes (the event ending, or the event starting). The ring fills up to a
 *  whole circle rather than draining to nothing, so "done" reads as done. */
export function computeFocus(items, now, windowMs = DEFAULT_WINDOW_MS) {
  let current = null;
  let next = null;

  for (const item of items) {
    if (item.allDay) continue;
    if (item.start <= now && item.end > now) {
      if (!current || item.start > current.start) current = item; // most recently started wins on overlap
    } else if (item.start > now && (!next || item.start < next.start)) {
      next = item;
    }
  }

  if (current) {
    const total = current.end - current.start;
    const remainingMs = Math.max(0, current.end - now);
    const elapsedMs = Math.max(0, now - current.start);
    return { item: current, mode: 'current', fraction: total > 0 ? clamp(elapsedMs / total, 0, 1) : 1, remainingMs };
  }

  if (next) {
    const remainingMs = Math.max(0, next.start - now);
    const elapsedMs = Math.max(0, windowMs - remainingMs);
    return { item: next, mode: 'upcoming', fraction: clamp(elapsedMs / windowMs, 0, 1), remainingMs };
  }

  return null;
}

function circle(cls, r) {
  const c = document.createElementNS(SVG_NS, 'circle');
  c.setAttribute('cx', '60');
  c.setAttribute('cy', '60');
  c.setAttribute('r', String(r));
  c.setAttribute('class', cls);
  return c;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

/** Draw the ring for the given focus (from computeFocus) into root. */
export function renderCountdownRing(root, focus, now) {
  root.replaceChildren();

  if (!focus) {
    root.classList.add('is-empty');
    root.append(el('div', 'countdown-empty', 'Nothing on the horizon'));
    return;
  }
  root.classList.remove('is-empty');
  root.classList.toggle('is-current', focus.mode === 'current');

  const { item, mode, fraction, remainingMs } = focus;
  const pct = Math.round(fraction * 100);

  const wrap = el('div', 'countdown-ring-wrap');
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 120 120');
  svg.setAttribute('class', 'countdown-ring');
  svg.setAttribute('aria-hidden', 'true');

  const arc = circle('ring-arc', R);
  arc.style.strokeDasharray = String(CIRC);
  arc.style.strokeDashoffset = String(CIRC * (1 - fraction));

  svg.append(circle('ring-track', R), arc);
  wrap.append(svg);

  const center = el('div', 'countdown-center');
  center.append(el('div', 'countdown-pct', `${pct}%`));
  center.append(el('div', 'countdown-clock', fmtCountdown(remainingMs)));
  wrap.append(center);

  root.append(wrap);

  const info = el('div', 'countdown-info');
  info.append(el('div', 'countdown-eyebrow', mode === 'current' ? 'In progress · ends in' : 'Up next · starts in'));
  info.append(el('div', 'countdown-title', item.title)); // textContent — feed titles are attacker-controlled
  root.append(info);

  root.setAttribute(
    'aria-label',
    `${mode === 'current' ? 'In progress' : 'Up next'}: ${item.title}, ${fmtCountdown(remainingMs)} remaining`
  );
}
