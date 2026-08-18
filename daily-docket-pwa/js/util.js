/* Dates, formatting, escaping, and the warm-fuzzy copy. */

let TZ = null;      // null → device zone
let LOCALE;         // undefined → device locale
let HOUR12 = true;

export function configureFormatting({ timeZone, locale, hour12 }) {
  TZ = timeZone || null;
  LOCALE = locale || undefined;
  HOUR12 = hour12 !== false;
  fmtCache.clear();
}

/* ---------- escaping ------------------------------------------------------ */

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

/** Escape text for interpolation into HTML (also safe inside "..." attributes). */
export function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ESC[c]);
}

/* ---------- time zone aware civil dates ---------------------------------- */

const fmtCache = new Map();
function fmt(opts) {
  const key = JSON.stringify(opts);
  let f = fmtCache.get(key);
  if (!f) {
    f = new Intl.DateTimeFormat(LOCALE, { timeZone: TZ || undefined, ...opts });
    fmtCache.set(key, f);
  }
  return f;
}

/** The wall-clock y/m/d/h/m/s a given instant shows in the active zone. */
export function civilParts(date) {
  if (!TZ) {
    return {
      year: date.getFullYear(), month: date.getMonth() + 1, day: date.getDate(),
      hour: date.getHours(), minute: date.getMinutes(), second: date.getSeconds(),
    };
  }
  const parts = {};
  for (const { type, value } of fmt({
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).formatToParts(date)) {
    if (type !== 'literal') parts[type] = value;
  }
  return {
    year: +parts.year, month: +parts.month, day: +parts.day,
    hour: +parts.hour % 24, minute: +parts.minute, second: +parts.second,
  };
}

/** ms to add to a "pretend this wall clock is UTC" timestamp to get the real instant. */
function zoneOffsetMs(date) {
  const p = civilParts(date);
  const asUtc = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second);
  return asUtc - Math.floor(date.getTime() / 1000) * 1000;
}

/** Midnight at the start of the calendar day that `date` falls on. */
export function startOfDay(date) {
  if (!TZ) {
    const d = new Date(date);
    d.setHours(0, 0, 0, 0);
    return d;
  }
  const p = civilParts(date);
  const wall = Date.UTC(p.year, p.month - 1, p.day, 0, 0, 0);
  // Two passes so a DST transition on this very day still resolves correctly.
  let guess = wall - zoneOffsetMs(date);
  guess = wall - zoneOffsetMs(new Date(guess));
  return new Date(guess);
}

export function addDays(date, n) {
  if (!TZ) {
    const d = new Date(date);
    d.setDate(d.getDate() + n);
    return d;
  }
  const p = civilParts(date);
  const wall = Date.UTC(p.year, p.month - 1, p.day + n, p.hour, p.minute, p.second);
  let guess = wall - zoneOffsetMs(date);
  guess = wall - zoneOffsetMs(new Date(guess));
  return new Date(guess);
}

export function startOfTomorrow(now) {
  return startOfDay(addDays(startOfDay(now), 1));
}

/* ---------- display formatting ------------------------------------------- */

/** "7:30 am" — lowercased on purpose, it reads softer than 7:30 AM. */
export function fmtTime(date) {
  const raw = fmt({ hour: 'numeric', minute: '2-digit', hour12: HOUR12 }).format(date);
  // Intl emits U+202F (narrow no-break space) before am/pm in newer engines.
  const spaced = raw.replace(/[\u00a0\u202f]/g, ' ');
  return spaced.replace(/\s?(AM|PM)$/i, (_, p) => ' ' + p.toLowerCase());
}

export function fmtDayLabel(date) {
  return fmt({ weekday: 'long', month: 'long', day: 'numeric' }).format(date);
}

export function fmtWeekdayShort(date) {
  return fmt({ weekday: 'short' }).format(date);
}

export function fmtMonthDay(date) {
  return fmt({ month: 'short', day: 'numeric' }).format(date);
}

/** "7:30 – 9:00 am", "all day", or "7:30 am" for a zero-length event. */
export function fmtRange(item) {
  if (item.allDay) return 'all day';
  const start = fmtTime(item.start);
  if (item.end - item.start < 60000) return start;
  const end = fmtTime(item.end);
  const sameMeridiem = start.slice(-2) === end.slice(-2);
  return `${sameMeridiem && HOUR12 ? start.replace(/\s?[ap]m$/, '') : start} – ${end}`;
}

export function humanDuration(ms) {
  const mins = Math.max(0, Math.round(ms / 60000));
  if (mins < 60) return `${mins} min`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  if (h >= 24) {
    const d = Math.floor(h / 24);
    return `${d} day${d === 1 ? '' : 's'}`;
  }
  return m ? `${h}h ${m}m` : `${h}h`;
}

/** "in 3h 20m" / "5 min ago" / "now" */
export function relTime(target, now = new Date()) {
  const diff = target - now;
  const abs = Math.abs(diff);
  if (abs < 60000) return 'now';
  const label = humanDuration(abs);
  return diff > 0 ? `in ${label}` : `${label} ago`;
}

/** Big ticking clock: "2d 04:31:07", "4:31:07", "31:07". */
export function fmtCountdown(ms) {
  if (ms <= 0) return '00:00';
  const total = Math.floor(ms / 1000);
  const d = Math.floor(total / 86400);
  const h = Math.floor((total % 86400) / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const p = (n) => String(n).padStart(2, '0');
  if (d > 0) return `${d}d ${p(h)}:${p(m)}:${p(s)}`;
  if (h > 0) return `${h}:${p(m)}:${p(s)}`;
  return `${p(m)}:${p(s)}`;
}

/** Screen-reader friendly, updated once a minute instead of every second. */
export function fmtCountdownWords(ms) {
  if (ms <= 0) return 'time is up';
  const total = Math.floor(ms / 60000);
  const d = Math.floor(total / 1440);
  const h = Math.floor((total % 1440) / 60);
  const m = total % 60;
  const bits = [];
  if (d) bits.push(`${d} day${d === 1 ? '' : 's'}`);
  if (h) bits.push(`${h} hour${h === 1 ? '' : 's'}`);
  if (m || !bits.length) bits.push(`${m} minute${m === 1 ? '' : 's'}`);
  return bits.join(' ') + ' left';
}

/* ---------- warmth ------------------------------------------------------- */

export function greeting(date, name) {
  const h = civilParts(date).hour;
  const who = name ? `, ${name}` : '';
  if (h < 5) return { text: `Still up${who}?`, emoji: '🌙' };
  if (h < 12) return { text: `Good morning${who}`, emoji: '☀️' };
  if (h < 17) return { text: `Good afternoon${who}`, emoji: '🌤️' };
  if (h < 21) return { text: `Good evening${who}`, emoji: '🌆' };
  return { text: `Winding down${who}`, emoji: '🌙' };
}

const MOTIVATION = [
  'One thing at a time. That’s the whole trick. 💜',
  'You don’t have to do it all today — just the next thing. ✨',
  'Small, boring consistency beats brilliant bursts. Keep going. 🌱',
  'Future you is going to be so glad you showed up. 🌟',
  'Progress counts even when it’s quiet. 🕯️',
  'You’ve done harder days than this one. 💪',
  'Protect the deep work. The rest can wait. 🎧',
  'Drink some water, stretch your back, then carry on. 💧',
  'Done is kinder than perfect. 🫶',
  'The plan is not the boss of you — it’s a tool. Use it gently. 🧸',
  'Momentum is built, not found. Start tiny. 🐢',
  'You’re allowed to be proud of an ordinary good day. 🌸',
  'Deadlines are just dates. You’re the one with the plan. 📌',
  'Half a task done today is a head start tomorrow. 🌗',
  'Breathe. Then pick the first line on the list. 🌬️',
  'Consistency is a love letter to future you. 💌',
  'Rest is part of the work, not a break from it. 🛏️',
  'Nothing on this list is bigger than you are. 🏔️',
];

/** Stable for a whole day, so it doesn't flicker on every re-render. */
export function motivation(date) {
  const p = civilParts(date);
  const seed = p.year * 10000 + p.month * 100 + p.day;
  return MOTIVATION[seed % MOTIVATION.length];
}

/* ---------- misc --------------------------------------------------------- */

export function clamp(n, lo, hi) {
  return Math.min(hi, Math.max(lo, n));
}

export function pluralise(n, one, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`;
}
