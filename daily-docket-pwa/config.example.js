/* Copy this to config.local.js (git-ignored) to keep your secret iCal URLs out
   of the committed file. config.local.js wins over config.js, and the in-app
   ⚙ Settings panel wins over both.

   Only the fields you list here are overridden — but note `calendars` replaces
   the whole array, so copy every calendar you want, in the same order. */

export const CONFIG = {
  calendars: [
    { id: 'school',  label: 'School',        area: null,     enabled: true,
      url: 'https://calendar.google.com/calendar/ical/you%40gmail.com/private-PASTE_KEY/basic.ics' },
    { id: 'routine', label: 'Daily Routine', area: null,     enabled: true,
      url: 'https://calendar.google.com/calendar/ical/PASTE_ID/private-PASTE_KEY/basic.ics' },
    { id: 'canvas',  label: 'Canvas',        area: 'School', enabled: true,
      url: 'https://canvas.ucsc.edu/feeds/calendars/user_PASTE_TOKEN.ics' },
  ],
};
