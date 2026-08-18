/* One interval drives every live clock on the page. */

import { fmtCountdown, fmtCountdownWords } from './util.js';

const tickers = new Map();
let timer = null;
let lastWordsMinute = -1;

function tick() {
  const now = Date.now();
  const minute = Math.floor(now / 60000);
  const wordsDue = minute !== lastWordsMinute;
  if (wordsDue) lastWordsMinute = minute;

  for (const [id, t] of tickers) {
    const remaining = +t.target - now;

    if (t.digits) t.digits.textContent = fmtCountdown(remaining);
    if (t.words && wordsDue) t.words.textContent = fmtCountdownWords(remaining);

    if (t.bar && t.from) {
      const span = +t.target - +t.from;
      const pct = span > 0 ? Math.min(100, Math.max(0, ((now - +t.from) / span) * 100)) : 100;
      t.bar.style.width = `${pct.toFixed(2)}%`;
    }

    if (remaining <= 0) {
      if (t.container) t.container.classList.add('is-expired');
      if (!t.fired) {
        t.fired = true;
        t.onExpire?.(id);
      }
    } else if (t.container) {
      // Under an hour, the card starts glowing.
      t.container.classList.toggle('is-imminent', remaining < 3600000);
    }
  }

  if (!tickers.size) stop();
}

function start() {
  if (timer) return;
  tick();
  timer = setInterval(tick, 1000);
}

function stop() {
  if (!timer) return;
  clearInterval(timer);
  timer = null;
}

/**
 * @param {string} id
 * @param {{target:Date, from?:Date, digits?:Element, words?:Element, bar?:Element,
 *          container?:Element, onExpire?:Function}} opts
 */
export function addCountdown(id, opts) {
  tickers.set(id, { ...opts, fired: false });
  lastWordsMinute = -1;
  start();
}

export function clearCountdowns() {
  tickers.clear();
  stop();
}

/* A backgrounded tab throttles timers, so resync the moment we're visible. */
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && tickers.size) {
    lastWordsMinute = -1;
    tick();
  }
});
