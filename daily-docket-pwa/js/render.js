/* Turning event objects into DOM. Every interpolated value goes through esc(). */

import {
  esc, fmtTime, fmtRange, fmtDayLabel, humanDuration, relTime, pluralise,
} from './util.js';
import { iconFor } from './importance.js';
import { AREA_COLOR } from './areas.js';

/* ---------- small pieces -------------------------------------------------- */

/** Empty when the title already leads with its own emoji. */
function icon(item) {
  const glyph = iconFor(item);
  return glyph ? `<span class="card-ico" aria-hidden="true">${glyph}</span>` : '';
}

/** The Docket's lane tag, in The Docket's colour. */
function areaChip(item, cfg) {
  if (!cfg?.showAreaChips || !item.area) return '';
  const colour = AREA_COLOR[item.area] || '#8197c2';
  return `<span class="area" style="--a:${esc(colour)}">${esc(item.area)}</span>`;
}

function metaLine(item, cfg) {
  const bits = [];
  if (item.location) bits.push(`<span class="meta-bit">📍 ${esc(item.location)}</span>`);
  if (cfg?.showCalendarLabels && item.calendar) {
    bits.push(`<span class="meta-bit">🗂 ${esc(item.calendar)}</span>`);
  }
  if (item.recurring) bits.push('<span class="meta-bit">🔁 repeats</span>');
  if (item.status === 'TENTATIVE') bits.push('<span class="meta-bit">❓ tentative</span>');
  const area = areaChip(item, cfg);
  if (!bits.length && !area) return '';
  return `<p class="card-meta">${bits.join('')}${area}</p>`;
}

function eventCard(item, { now, dim = false, spotlightKey = null, cfg = null } = {}) {
  const classes = ['card'];
  if (dim) classes.push('is-done');
  if (item.inProgress) classes.push('is-now');
  // Same item as the gold card above — the rail ties them together so the
  // repeat reads as deliberate rather than as a duplicate.
  if (spotlightKey && item.key === spotlightKey) classes.push('is-spotlighted');

  const badge = item.inProgress
    ? '<span class="badge badge-now">happening now</span>'
    : !dim && now && +item.start > +now
      ? `<span class="badge">${esc(relTime(item.start, now))}</span>`
      : '';

  const duration = item.allDay
    ? 'all day'
    : humanDuration(+item.end - +item.start);

  return `
    <article class="${classes.join(' ')}">
      <div class="card-rail" aria-hidden="true"></div>
      <div class="card-when">
        <span class="when-start">${esc(item.allDay ? '—' : fmtTime(item.start))}</span>
        <span class="when-dur">${esc(duration)}</span>
      </div>
      <div class="card-main">
        <h3 class="card-title">${icon(item)}${esc(item.title)}</h3>
        ${metaLine(item, cfg)}
      </div>
      ${badge}
    </article>`;
}

function emptyState(emoji, text) {
  return `<p class="empty"><span aria-hidden="true">${emoji}</span> ${esc(text)}</p>`;
}

/* ---------- chips --------------------------------------------------------- */

export function renderChips(container, items, cfg) {
  if (!items.length) {
    container.innerHTML = '';
    container.hidden = true;
    return;
  }
  container.hidden = false;
  container.innerHTML = items
    .map((i) => {
      const colour = cfg?.showAreaChips && i.area ? AREA_COLOR[i.area] : null;
      const style = colour ? ` style="--a:${esc(colour)}"` : '';
      return `<span class="chip${colour ? ' is-area' : ''}"${style}>${icon(i)}${esc(i.title)}</span>`;
    })
    .join('');
}

/* ---------- spotlight / focus --------------------------------------------- */

/**
 * @param {'today'|'tomorrow'} mode
 * @returns {{digits:Element, words:Element, bar:Element, container:Element}|null}
 *          countdown hooks, or null when this card has no clock
 */
export function renderSpotlight(container, pick, { mode, now, dayLabel, cfg }) {
  if (!pick) {
    container.innerHTML = `<div class="spotlight is-quiet">${
      mode === 'today'
        ? emptyState('🌙', 'No hard deadlines today. Breathe, then build.')
        : emptyState('🍃', 'Tomorrow is wide open. Enjoy the whitespace.')
    }</div>`;
    return null;
  }

  const { item, isHardDeadline, target, pinned } = pick;
  const gold = mode === 'today' && isHardDeadline;

  const eyebrow = gold
    ? '⏰ Hard deadline'
    : mode === 'today'
      ? '✨ Next up'
      : isHardDeadline
        ? '⏰ Tomorrow’s deadline'
        : '🎯 Tomorrow’s focus';

  const when = item.allDay
    ? `${esc(dayLabel)} · all day`
    : `${esc(dayLabel)} · ${esc(fmtRange(item))}`;

  const showClock = !!target && (mode === 'today' || isHardDeadline);
  const clock = showClock
    ? `
      <div class="spot-clock">
        <span class="spot-verb">${esc(target.verb)}</span>
        <span class="spot-digits" aria-hidden="true">–:–</span>
        <span class="sr-only" role="status"></span>
      </div>
      <div class="spot-bar" aria-hidden="true"><i></i></div>`
    : `<div class="spot-soft">${esc(
        item.allDay ? 'all day tomorrow' : `${humanDuration(+item.end - +item.start)} blocked out`,
      )}</div>`;

  container.innerHTML = `
    <article class="spotlight ${gold ? 'is-gold' : 'is-violet'}${pinned ? ' is-pinned' : ''}">
      <div class="spot-eyebrow">${eyebrow}${pinned ? ' <span class="pin">★ pinned</span>' : ''}</div>
      <h2 class="spot-title">${esc(item.title)}</h2>
      <div class="spot-when">${when}</div>
      ${clock}
      <p class="spot-meta">
        ${item.location ? `<span class="meta-bit">📍 ${esc(item.location)}</span>` : ''}
        ${cfg?.showCalendarLabels && item.calendar ? `<span class="meta-bit">🗂 ${esc(item.calendar)}</span>` : ''}
        ${areaChip(item, cfg)}
      </p>
    </article>`;

  if (!showClock) return null;
  const root = container.querySelector('.spotlight');
  return {
    container: root,
    digits: root.querySelector('.spot-digits'),
    words: root.querySelector('.sr-only'),
    bar: root.querySelector('.spot-bar > i'),
  };
}

/* ---------- lists --------------------------------------------------------- */

export function renderAhead(container, items, now, spotlightKey, cfg, dayTotal = 0) {
  if (items.length) {
    container.innerHTML = items.map((i) => eventCard(i, { now, spotlightKey, cfg })).join('');
    return;
  }
  // An empty day and a finished day deserve different sentences. The first
  // line is The Docket's own copy for an unscheduled day.
  container.innerHTML = dayTotal
    ? emptyState('🌙', 'That’s everything for today. Close the laptop.')
    : emptyState('🌤️', 'Open day — anchor it: gym → deep work → wind down.');
}

export function renderDone(section, items, { collapsed, cfg }) {
  if (!items.length) {
    section.hidden = true;
    section.innerHTML = '';
    return;
  }
  section.hidden = false;
  section.innerHTML = `
    <details class="done-fold"${collapsed ? '' : ' open'}>
      <summary>
        <span class="done-check" aria-hidden="true">✅</span>
        ${esc(pluralise(items.length, 'thing'))} already done
        <span class="fold-hint" aria-hidden="true">tap to ${collapsed ? 'show' : 'hide'}</span>
      </summary>
      <div class="done-list">${items.map((i) => eventCard(i, { dim: true, cfg })).join('')}</div>
    </details>`;
}

export function renderTimeline(container, items, cfg) {
  if (!items.length) {
    container.innerHTML = emptyState('🍃', 'No timed events tomorrow — a rare gift.');
    return;
  }
  container.innerHTML = `
    <ol class="timeline">
      ${items
        .map(
          (i) => `
        <li class="tl-row">
          <div class="tl-time">${esc(fmtTime(i.start))}</div>
          <div class="tl-dot" aria-hidden="true"></div>
          <div class="tl-card">
            <h3 class="card-title">${icon(i)}${esc(i.title)}</h3>
            <p class="card-meta">
              <span class="meta-bit">${esc(fmtRange(i))}</span>
              <span class="meta-bit">${esc(humanDuration(+i.end - +i.start))}</span>
              ${i.location ? `<span class="meta-bit">📍 ${esc(i.location)}</span>` : ''}
              ${cfg?.showCalendarLabels && i.calendar ? `<span class="meta-bit">🗂 ${esc(i.calendar)}</span>` : ''}
              ${areaChip(i, cfg)}
            </p>
          </div>
        </li>`,
        )
        .join('')}
    </ol>`;
}

/* ---------- day progress -------------------------------------------------- */

export function renderProgress(container, { done, total }) {
  if (!total) {
    container.hidden = true;
    return;
  }
  container.hidden = false;
  const pct = Math.round((done / total) * 100);
  const word =
    pct === 100 ? 'Day complete — beautiful work 🎉'
      : pct >= 60 ? 'Downhill from here 🌟'
        : pct >= 25 ? 'Rolling along 🌱'
          : 'Fresh start 🌅';
  container.innerHTML = `
    <div class="prog-top"><span>${esc(word)}</span><span>${done}/${total}</span></div>
    <div class="prog-track"><i style="width:${pct}%"></i></div>`;
}

/* ---------- shell states -------------------------------------------------- */

export function renderSetupNeeded(container, detail) {
  container.innerHTML = `
    <div class="setup">
      <h2>👋 Let’s hook up your calendars</h2>
      <p>The docket has nothing to read yet. Two ways to fix that:</p>
      <ol>
        <li>Open <code>config.js</code> and paste each <strong>secret iCal address</strong>
            into the matching <code>url</code> in the <code>calendars</code> list, or</li>
        <li>Tap <strong>⚙ Settings</strong> and paste them there — they stay on this device.</li>
      </ol>
      <p class="setup-path">Google Calendar → ⚙ Settings → click a calendar in the sidebar →
         Integrate calendar → “Secret address in iCal format”. Repeat per calendar —
         one URL covers one calendar, not the whole account.</p>
      ${detail ? `<pre class="setup-detail">${esc(detail)}</pre>` : ''}
    </div>`;
}

export function renderError(container, message, attempts) {
  const rows = (attempts || [])
    .map((a) => `<li>${a.label ? `<strong>${esc(a.label)}</strong> · ` : ''}` +
      `<code>${esc(a.via)}</code> — ${esc(a.reason || 'ok')}</li>`)
    .join('');
  container.innerHTML = `
    <div class="setup is-error">
      <h2>😖 Couldn’t load the calendar</h2>
      <p>${esc(message)}</p>
      ${rows ? `<ul class="attempts">${rows}</ul>` : ''}
      <p class="setup-path">If every attempt says <em>Failed to fetch</em>, that’s CORS —
         see “Where do I put the URL?” in the README.</p>
    </div>`;
}

export function renderDayHeading(el, date, isToday) {
  el.textContent = `${isToday ? 'Today' : 'Tomorrow'} · ${fmtDayLabel(date)}`;
}
