/* Deciding what actually counts as a commitment. */

/* Separators people type between a tag and a title. The middle dot in "WR ·"
   is U+00B7, which is easy to fat-finger, hence lenient matching. */
const SEP_CLASS = '·•‧∙・|/\\\\:;,~»>.\\u2013\\u2014\\u2212-';
const SEP_RE = new RegExp(`[${SEP_CLASS}\\s]+`, 'g');

function escapeRe(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function buildPrefixMatchers(prefixes, lenient) {
  return (prefixes || [])
    .filter(Boolean)
    .map((prefix) => {
      const norm = String(prefix).normalize('NFC').trim();
      if (!norm) return null;

      if (!lenient) {
        // Exact prefix, but tolerant about how much whitespace is in it.
        const src = escapeRe(norm.replace(/\s+/g, ' ')).replace(/ /g, '\\s+');
        return { source: prefix, re: new RegExp(`^${src}`, 'i') };
      }

      // Lenient: strip the decoration down to the tag itself ("WR ·" → "WR"),
      // then require a separator or whitespace after it so "WRAP" is safe.
      const core = norm.replace(SEP_RE, '');
      if (!core) return null;
      return {
        source: prefix,
        re: new RegExp(`^${escapeRe(core)}(?=$|[${SEP_CLASS}\\s])`, 'i'),
      };
    })
    .filter(Boolean);
}

/**
 * @returns {null|{reason:string, detail?:string}} null means "keep this event"
 */
export function rejectReason(item, cfg, matchers) {
  const title = (item.title || '').normalize('NFC').trim();

  for (const m of matchers) {
    if (m.re.test(title)) return { reason: 'prefix', detail: m.source };
  }
  for (const src of cfg.ignoreTitlePatterns || []) {
    try {
      if (new RegExp(src, 'i').test(title)) return { reason: 'pattern', detail: src };
    } catch {
      /* a bad regex in config shouldn't break the docket */
    }
  }
  if (cfg.skipCancelled && item.status === 'CANCELLED') {
    return { reason: 'cancelled' };
  }
  if (cfg.skipTransparent && item.transparent) {
    // All-day items are exempt by default: Google marks birthdays and
    // milestones free, and dropping them would empty the chip row.
    if (!item.allDay || cfg.skipTransparentAllDay) return { reason: 'free' };
  }
  return null;
}

/**
 * Apply the filters to a list of expanded occurrences.
 * @returns {{kept:Array, dropped:Array}}
 */
export function applyFilters(items, cfg) {
  const matchers = buildPrefixMatchers(cfg.ignoreTitlePrefixes, cfg.lenientPrefixMatch);
  const kept = [];
  const dropped = [];
  for (const item of items) {
    const reject = rejectReason(item, cfg, matchers);
    if (reject) dropped.push({ ...item, rejected: reject });
    else kept.push(item);
  }
  return { kept, dropped };
}

/**
 * Split a day into all-day chips and timed events.
 *
 * All-day items use plain overlap, so a multi-day trip chips on every day it
 * covers. Timed events belong to the day they START on — otherwise last
 * night's 11pm call would head up tomorrow's timeline. `includeRunning` adds
 * back anything already in progress when the day began, which is what you want
 * for today and not for tomorrow.
 */
export function forDay(items, dayStart, dayEnd, { includeRunning = false } = {}) {
  const from = +dayStart;
  const to = +dayEnd;

  const allDay = items.filter(
    (i) => i.allDay && +i.start < to && Math.max(+i.end, +i.start + 1) > from,
  );

  const timed = items
    .filter((i) => {
      if (i.allDay) return false;
      if (+i.start >= from && +i.start < to) return true;
      return includeRunning && +i.start < from && +i.end > from;
    })
    .sort((a, b) => a.start - b.start || a.end - b.end);

  return { allDay, timed };
}

/** Today's timed events, sliced by the current moment. */
export function splitByNow(timed, now) {
  const ahead = [];
  const done = [];
  for (const item of timed) {
    const endsAfterNow = +item.end > +now;
    const item2 = { ...item, inProgress: +item.start <= +now && endsAfterNow };
    (endsAfterNow ? ahead : done).push(item2);
  }
  return { ahead, done };
}
