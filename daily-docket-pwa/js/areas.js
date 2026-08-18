/* The same area vocabulary The Docket routine uses (Daily-Docket/build_docket.py),
   so both boards label the same event the same way. Colours are lifted verbatim
   from AREA_COLOR / PRIO_COLOR over there. */

export const AREA_COLOR = {
  School: '#7fa8d9',
  'Pre-Med': '#b57edc',
  Trading: '#4fb787',
  Health: '#e8829f',
  Personal: '#d97a4a',
  Admin: '#a98a95',
  Interest: '#f0c869',
};

export const PRIO_COLOR = {
  High: '#ff5470',
  Medium: '#e0a458',
  Low: '#8a6a72',
};

/* Checked in order — first match wins, so put the specific before the general.
   Pre-Med needs an actual science/medicine signal; campus logistics are School;
   money, forms and business are Admin. That matches how the routine files them. */
const AREA_RULES = [
  // Unambiguous proper nouns first: "IHSS provider enrollment — book
  // orientation" is Admin, even though "orientation" is a School word.
  ['Admin', /\b(ihss|dmv|soc ?426|live ?scan|instratix)\b/],
  ['Trading', /\b(market|trading|trade|swing|iape|pine ?script|watchlist|earnings|ticker|premarket|open(ing)? bell)\b/],
  ['Pre-Med', /\b(chem|chemistry|orgo|organic|bio(logy|logical)?|physics|mcat|pre-?med|clinical|shadow(ing)?|anatomy|physio)\b/],
  ['Health', /\b(doctor|dentist|clinic|kaiser|therapy|therapist|gym|workout|lift|cardio|immuni[sz]ation|vaccine|uc ?ship|physical)\b/],
  ['School', /\b(ucsc|canvas|class|lecture|lab|exam|midterm|final|quiz|assignment|homework|pset|problem set|essay|course|session|registrar|tuition|financial aid|slug|anth|summer edge|professor|discussion|orientation)\b/],
  ['Admin', /\b(ihss|dmv|insurance|paperwork|form|soc ?426|live ?scan|bank|budget(ing)?|savings|taxes|tax|invoice|bill|rent|business|client|instratix|commission)\b/],
  ['Interest', /\b(fragrance|cologne|fashion|outfit|brand|pinterest|inspo|model(ing)?|beat ?saber|draw(ing)?|language)\b/],
  ['Personal', /\b(birthday|bday|dance|rehearsal|dinner|lunch|breakfast|friends?|family|wind ?down|creative|hangout|party|movie|read(ing)?)\b/],
];

function matchRules(text) {
  for (const [area, re] of AREA_RULES) if (re.test(text)) return area;
  return null;
}

/**
 * Work out which lane an event belongs to.
 *
 * An area set on the calendar source always wins — you know what a feed is for
 * better than a regex does. After that the TITLE gets the first vote on its
 * own, and the description is only consulted if the title says nothing.
 * Descriptions name other things all the time: "Session 1 ENDS" mentions next
 * week's CHEM 3A in its notes, and matching on that filed a School event under
 * Pre-Med.
 */
export function areaFor(item, calendarArea) {
  if (calendarArea) return calendarArea;
  const title = String(item.title || '').toLowerCase();
  return matchRules(title) || matchRules(String(item.description || '').toLowerCase());
}

/** The routine's three priority bands, derived from the importance score. */
export function priorityFor(score, threshold = 60) {
  if (score >= threshold + 25) return 'High';
  if (score >= threshold) return 'Medium';
  return 'Low';
}
