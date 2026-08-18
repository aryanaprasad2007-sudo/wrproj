/* Which single thing deserves the gold card. */

import { clamp } from './util.js';

/* Words that mean "this has a hard due time", weighted 0-100.
   Tuned against Ari's actual calendar vocabulary: he leads urgent items with
   🚨, marks unavoidable ones "(mandatory)", and writes "(blocks X)" when
   something gates another thing. Those conventions score like keywords. */
const DEADLINE_RULES = [
  [/\bdue\b/, 100],
  [/\bdeadlines?\b/, 100],
  [/🚨|‼️|❗/u, 94],
  [/\bblocks?\b|\bblocking\b|\bblocker\b|\bgates?\b/, 90],
  [/\bmandatory\b|\brequired\b|\bnon-?negotiable\b/, 86],
  [/⏰|⌛|⏳/u, 84],
  [/\borientation\b/, 70],
  [/\bends?\b(?!\s*(?:up|with|the day))/, 68],
  [/\bfinal exam\b|\bmidterm\b|\bfinals?\b(?!\s*(?:fantasy|four))/, 98],
  [/\bexams?\b/, 95],
  [/\bsubmit(?:s|ted|ting|ssion)?\b|\bturn in\b|\bhand in\b/, 92],
  [/\binterviews?\b/, 90],
  [/\bflight\b|\bboarding\b|\bdepart(?:s|ure)?\b|\bcheck[- ]?in\b/, 88],
  [/\bpay(?:ment|able)?\b|\bbill\b|\binvoice\b|\bdeposit\b|\btuition\b|\brent\b/, 86],
  [/\bclos(?:es|ing)\b|\bexpires?\b|\blast day\b|\bcut ?off\b|\bends today\b/, 85],
  [/\bapply\b|\bapplications?\b/, 82],
  [/\bregist(?:er|ration)\b|\benroll(?:ment)?\b|\bsign ?up\b/, 78],
  [/\bquiz(?:zes)?\b/, 76],
  [/\bappointments?\b|\bappt\b|\bdoctor\b|\bdentist\b|\bclinic\b|\bdr\.\s/, 74],
  [/\bpresent(?:ation)?\b|\bdefen[cs]e\b|\bdemo\b|\bpitch\b/, 72],
  [/\bessays?\b|\bpapers?\b|\bproblem set\b|\bhomework\b|\bassignments?\b/, 68],
  [/\bshift\b|\bwork\b(?!out)/, 62],
  [/\btests?\b/, 60],
  [/📌|🔴|⚠️/u, 58],
];

const URGENT_WORDS = /\burgent\b|\basap\b|\bfinal notice\b|\bdon'?t forget\b|\blast chance\b/i;

export function scoreItem(item, cfg = {}) {
  const title = String(item.title || '');
  const hay = `${title} ${item.description || ''}`.toLowerCase();

  const rules = [...DEADLINE_RULES];
  for (const [word, weight] of Object.entries(cfg.extraDeadlineKeywords || {})) {
    rules.push([new RegExp(`\\b${word.toLowerCase().replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`), weight]);
  }

  let best = 0;
  const hits = [];
  for (const [re, weight] of rules) {
    if (re.test(hay)) {
      hits.push(weight);
      if (weight > best) best = weight;
    }
  }

  // Stacked signals nudge it up, but one strong word already carries most of it.
  let score = best + clamp((hits.length - 1) * 5, 0, 15);

  if (URGENT_WORDS.test(hay)) score += 20;
  if (/!!|！！/.test(title)) score += 12;
  if (title.length > 3 && title === title.toUpperCase() && /[A-Z]/.test(title)) score += 10;
  if (item.allDay) score -= 10;                       // no precise clock time

  const pin = cfg.pinMarker && title.includes(cfg.pinMarker);
  if (pin) score += 1000;

  const threshold = cfg.deadlineScoreThreshold ?? 60;
  return {
    score,
    pinned: !!pin,
    isHardDeadline: score >= threshold,
    matched: hits.length,
  };
}

/** When the clock should actually count down to, and how to label it. */
export function deadlineTarget(item, now, hard) {
  if (item.allDay) {
    return { at: new Date(item.end), verb: hard ? 'due by end of day' : 'all day', endOfDay: true };
  }
  if (+item.start > +now) {
    // "due in" only fits a moment you have to hit. A twelve-hour meeting is
    // something you turn up to, so it starts — it isn't due.
    const isMoment = +item.end - +item.start <= 15 * 60000;
    return {
      at: new Date(item.start),
      verb: hard && isMoment ? 'due in' : 'starts in',
      endOfDay: false,
    };
  }
  return { at: new Date(item.end), verb: 'ends in', endOfDay: false };
}

function urgencyBonus(item, now, hard) {
  const target = deadlineTarget(item, now, hard).at;
  const hours = (+target - +now) / 3600000;
  return clamp(48 - hours * 2, 0, 48);
}

function rank(items, now, cfg, { durationWeight = 0 } = {}) {
  return items
    .map((item) => {
      const s = scoreItem(item, cfg);
      const durMins = (+item.end - +item.start) / 60000;
      const priority =
        s.score +
        urgencyBonus(item, now, s.isHardDeadline) +
        (durationWeight ? clamp(durMins / 6, 0, 40) * durationWeight : 0);
      return { item, ...s, priority };
    })
    .sort((a, b) => b.priority - a.priority || a.item.start - b.item.start);
}

/**
 * Today's gold card: the most important hard deadline still ahead. If nothing
 * qualifies we still spotlight the next thing up, just with softer wording.
 */
export function pickSpotlight(timed, allDay, now, cfg) {
  const pool = [
    ...timed.filter((i) => +i.end > +now),
    // An all-day item only competes if it reads like a real due date.
    ...allDay.filter((i) => +i.end > +now && scoreItem(i, cfg).isHardDeadline),
  ];
  if (!pool.length) return null;

  const ranked = rank(pool, now, cfg);
  const hard = ranked.filter((r) => r.isHardDeadline);
  const winner = (hard.length ? hard : ranked)[0];

  return {
    item: winner.item,
    score: winner.score,
    pinned: winner.pinned,
    isHardDeadline: winner.isHardDeadline,
    target: deadlineTarget(winner.item, now, winner.isHardDeadline),
  };
}

/**
 * Tomorrow's focus card: the biggest thing on the day. Weighs length as well as
 * urgency, because "the big one" is often the long one.
 */
export function pickFocus(timed, allDay, dayStart, cfg) {
  const pool = timed.length
    ? [...timed, ...allDay.filter((i) => scoreItem(i, cfg).isHardDeadline)]
    : allDay;
  if (!pool.length) return null;

  const ranked = rank(pool, dayStart, cfg, { durationWeight: 1 });
  const winner = ranked[0];

  return {
    item: winner.item,
    score: winner.score,
    pinned: winner.pinned,
    isHardDeadline: winner.isHardDeadline,
    // Only a genuine deadline earns a ticking clock on the Tomorrow view.
    target: winner.isHardDeadline ? deadlineTarget(winner.item, new Date(), true) : null,
  };
}

/* ---------- a little visual shorthand ------------------------------------ */

const ICONS = [
  [/\bgym\b|\blift\b|\bworkout\b|\btrain(?:ing)?\b|\bcardio\b|\brun\b/, '🏋️'],
  [/\bdance|\bchoreo|\bballet|\bhip ?hop|\brehearsal\b/, '💃'],
  [/\blab\b|\bchem\b|\bbio(?:logy)?\b|\bexperiment\b/, '🧪'],
  [/\bexam\b|\bmidterm\b|\bfinal\b|\bquiz\b|\btest\b/, '📝'],
  [/\blecture\b|\bclass\b|\bcourse\b|\bseminar\b|\bdiscussion\b/, '📚'],
  [/\bstudy\b|\breview\b|\bread(?:ing)?\b|\bflashcards?\b|\banki\b/, '📖'],
  [/\bmarket\b|\btrade\b|\btrading\b|\bopen(?:ing)? bell\b|\bearnings\b|\bswing\b/, '📈'],
  [/\bdoctor\b|\bdentist\b|\bclinic\b|\bappointment\b|\bappt\b|\btherapy\b/, '🩺'],
  [/\bflight\b|\bairport\b|\bdepart\b|\bboarding\b/, '✈️'],
  [/\bbirthday\b|\bbday\b|🎂/u, '🎂'],
  [/\bcall\b|\bzoom\b|\bmeet(?:ing)?\b|\bsync\b|\b1:1\b|\bstandup\b/, '🤝'],
  [/\binterview\b/, '🎤'],
  [/\blunch\b|\bdinner\b|\bbreakfast\b|\bcoffee\b|\bmeal\b|\beat\b/, '🍽️'],
  [/\bsleep\b|\bbed\b|\bwind ?down\b|\brest\b/, '😴'],
  [/\bpay\b|\bbill\b|\brent\b|\btuition\b|\binvoice\b|\bdeposit\b/, '💳'],
  [/\bdue\b|\bdeadline\b|\bsubmit\b/, '⏰'],
  [/\bshift\b|\bwork\b|\bihss\b/, '💼'],
  [/\bdrive\b|\bcommute\b|\bbus\b|\btrain\b/, '🚗'],
];

/** True when the title already opens with an emoji — don't stack another one. */
export function hasLeadingEmoji(title) {
  return /^\s*\p{Extended_Pictographic}/u.test(String(title || ''));
}

export function iconFor(item) {
  if (hasLeadingEmoji(item.title)) return '';
  const hay = String(item.title || '').toLowerCase();
  for (const [re, emoji] of ICONS) if (re.test(hay)) return emoji;
  return item.allDay ? '🗓️' : '•';
}
