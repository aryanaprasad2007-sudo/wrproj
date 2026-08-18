/* Moon phase.

   The grimoire conceit needs a real moon, not a decorative one — a wrong glyph
   on a calendar you look at every day is worse than no glyph at all.

   This is the standard mean-synodic approximation: count days since a known new
   moon and take the remainder over one lunation. It ignores the moon's orbital
   eccentricity, so it drifts by up to about half a day across a month. That is
   well inside the ~3.7-day width of a single phase bucket, so the glyph is
   right; only someone timing an exact new moon to the hour would care.

   Reference new moon: 2000-01-06 18:14 UTC. */

const LUNATION_MS = 29.530588853 * 86400000;
const REFERENCE_NEW_MOON = Date.UTC(2000, 0, 6, 18, 14, 0);

/** The eight named phases, in order, with the glyph shown on each day cell. */
export const PHASES = [
  { name: 'New moon',        glyph: '●' },
  { name: 'Waxing crescent', glyph: '☽' },
  { name: 'First quarter',   glyph: '◐' },
  { name: 'Waxing gibbous',  glyph: '◑' },
  { name: 'Full moon',       glyph: '○' },
  { name: 'Waning gibbous',  glyph: '◒' },
  { name: 'Last quarter',    glyph: '◓' },
  { name: 'Waning crescent', glyph: '☾' },
];

/**
 * Age of the moon as a fraction of one lunation.
 * @param {Date} date
 * @returns {number} 0 at new moon, 0.5 at full, approaching 1 back at new.
 */
export function moonFraction(date) {
  const elapsed = date.getTime() - REFERENCE_NEW_MOON;
  // JS % keeps the sign of the dividend, so dates before 2000 would go negative.
  const wrapped = ((elapsed % LUNATION_MS) + LUNATION_MS) % LUNATION_MS;
  return wrapped / LUNATION_MS;
}

/**
 * The phase bucket for a date.
 *
 * Buckets are centred on their landmark rather than starting at it: without the
 * half-bucket offset, "new moon" would mean "the 3.7 days AFTER the new moon",
 * and the full moon glyph would show up a day and a half late.
 *
 * @param {Date} date
 * @returns {{name: string, glyph: string, fraction: number, index: number}}
 */
export function moonPhase(date) {
  const fraction = moonFraction(date);
  const index = Math.floor(fraction * 8 + 0.5) % 8;
  return { ...PHASES[index], fraction, index };
}

/** Illuminated fraction of the disc, 0 (new) → 1 (full). For the rail readout. */
export function illumination(date) {
  return (1 - Math.cos(2 * Math.PI * moonFraction(date))) / 2;
}
