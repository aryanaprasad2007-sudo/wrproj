/* Copy this file to config.local.js and put your real feed URLs in it.

   config.local.js overrides config.js and is git-ignored, so the secret URLs
   stay out of anything you commit, screenshot, or sync.

   Where to get each URL
   ---------------------
   Google (per calendar):
     calendar.google.com → hover the calendar → ⋮ → Settings and sharing →
     "Integrate calendar" → copy "Secret address in iCal format".
     Your routine lives on your PRIMARY calendar, so that's the one to grab
     first — its settings page is the one titled with your email address.

   Canvas (all courses at once):
     canvas.ucsc.edu → Calendar → "Calendar Feed" (bottom right) → copy.

   Treat both like passwords. Anyone holding one of these URLs can read that
   calendar forever without logging in. If one leaks, use "Reset private URLs"
   on the same Google settings page — the old link dies immediately.

   `calendars` REPLACES the array in config.js rather than merging into it, so
   list every calendar you want, in the order you want them. The order is also
   how the local proxy addresses them, so don't reorder without re-syncing. */

export const CONFIG = {
  calendars: [
    { id: 'primary', label: 'Primary',  area: null,     enabled: true,
      url: 'https://calendar.google.com/calendar/ical/you%40gmail.com/private-PASTE_KEY/basic.ics' },

    { id: 'canvas',  label: 'Canvas',   area: 'School', enabled: true,
      url: 'https://canvas.ucsc.edu/feeds/calendars/user_PASTE_TOKEN.ics' },

    { id: 'holiday', label: 'Holidays', area: null,     enabled: true,
      url: 'https://calendar.google.com/calendar/ical/en.usa%23holiday%40group.v.calendar.google.com/public/basic.ics' },
  ],

  // Point at a wallpaper you've dropped in icons/ — see README.
  wallpaper: null,
  wallpaperOpacity: 0.30,
};
