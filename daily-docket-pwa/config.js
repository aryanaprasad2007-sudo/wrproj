/* ============================================================================
   Daily Docket — configuration
   ----------------------------------------------------------------------------
   This is the only file you need to edit. Everything else is app code.

   ⚠️  A secret iCal URL is a password. Anyone who has it can read that whole
       calendar. Read "Where do I put the URLs?" in README.md before pasting —
       on Netlify or Vercel you can leave every `url` blank and keep them out of
       the repo entirely.
   ============================================================================ */

export const CONFIG = {
  /* ---- who this docket is for ------------------------------------------- */
  ownerName: 'Ari',

  /* ---- the calendars -----------------------------------------------------
     Your schedule lives across five Google calendars, so the docket reads all
     of them and merges the result. Order matters: `cal=0` is the first entry,
     and the /ics proxy uses that index (and so does the ICS_URLS env var).

     To fill in a `url`:  Google Calendar → ⚙ Settings → click the calendar in
     the left sidebar → "Integrate calendar" → "Secret address in iCal format".

     `area` tags every event from that feed with one of The Docket's lanes
     (School · Pre-Med · Trading · Health · Personal · Admin · Interest).
     Leave it null to let the title decide.                                   */
  calendars: [
    {
      id: 'school',
      label: 'School',
      area: null,                 // mixed bag — let each title pick its lane
      enabled: true,
      // Google id: aryanaprasad2007@gmail.com   ← your primary calendar
      url: '',                    // ⬅ PASTE the secret iCal URL here
    },
    {
      id: 'routine',
      label: 'Daily Routine',
      area: null,
      enabled: true,
      // Google id: 59f6bb1ba327bbb8e2d84afeb866798d62f9fd697728963e690464425b24877d@group.calendar.google.com
      url: '',                    // ⬅ PASTE the secret iCal URL here
    },
    {
      id: 'canvas',
      label: 'Canvas',
      area: 'School',             // every assignment and exam is coursework
      enabled: true,
      // Two ways to get this one:
      //   a) Canvas → Calendar → "Calendar Feed" button (freshest), or
      //   b) Google Calendar → "Aryan Prasad Calendar (Canvas)" → secret iCal
      url: '',                    // ⬅ PASTE the Canvas feed URL here
    },
    {
      id: 'holidays',
      label: 'Holidays',
      area: 'Personal',
      enabled: false,             // 317 all-day events; flip on if you want them
      url: 'https://calendar.google.com/calendar/ical/en.usa%23holiday%40group.v.calendar.google.com/public/basic.ics',
    },
    {
      id: 'moreau',
      label: 'Moreau',
      area: 'School',
      enabled: false,             // 1.8 MB of high-school events — you've graduated
      url: 'https://calendar.google.com/calendar/ical/moreaucatholic.org_qke2v53rrqfem5c91v5p9aeo4c%40group.calendar.google.com/public/basic.ics',
    },
  ],

  /* Same-origin path that proxies the feeds, called as `/ics?cal=<index>`.
     Works automatically with:
       • tools/serve.py   (local development)
       • netlify.toml + netlify/functions/ics.mjs
       • vercel.json + api/ics.js
     Set to null to disable and always fetch each `url` directly.             */
  icsProxyPath: '/ics',

  /* Last-ditch fallback for static hosts with no proxy (GitHub Pages).
     OFF by default and for good reason: a third-party server would see your
     entire calendar. Flip to true only if you accept that.                    */
  useCorsRelay: false,
  corsRelays: [
    'https://api.allorigins.win/raw?url={url}',
    'https://corsproxy.io/?{url}',
  ],

  /* ---- filtering ---------------------------------------------------------
     Events whose title starts with any of these are overlays, not real
     commitments, so they never show up.                                      */
  ignoreTitlePrefixes: ['WR ·'],

  /* Treat "WR -", "WR •", "WR:" and "WR " as the same prefix as "WR ·", so a
     typo'd separator doesn't leak an overlay onto the docket.                 */
  lenientPrefixMatch: true,

  /* Anything else to hide, as regex source strings (matched against title).  */
  ignoreTitlePatterns: [],

  /* Skip events marked free / TRANSP:TRANSPARENT. All-day items are exempt
     because Google marks birthdays and milestones free by default — you'd
     lose every chip if this applied to them.                                 */
  skipTransparent: true,
  skipTransparentAllDay: false,
  skipCancelled: true,

  /* ---- spotlight / focus -------------------------------------------------
     Extra words that mean "this is a hard deadline", scored 0-100. Merged on
     top of the built-in list in js/importance.js.                            */
  extraDeadlineKeywords: {
    'pset': 80,
    'lab report': 75,
    'canvas': 60,
    'ihss': 70,
    'instratix': 65,
  },

  /* A title containing this always wins the spotlight. Put it in the event
     name in Google Calendar when you want to force something to the top.
     Your 🚨 convention already scores high on its own.                       */
  pinMarker: '★',

  /* Minimum score before something counts as a real deadline (and therefore
     earns a countdown on the Tomorrow view). 0-100+.                         */
  deadlineScoreThreshold: 60,

  /* ---- behaviour --------------------------------------------------------- */
  refreshMinutes: 15,      // silent re-fetch while the app is open
  hour12: true,            // false → 24-hour clock
  timeZone: null,          // null = this device's zone (recommended)
  locale: null,            // null = this device's locale
  showDoneCollapsed: true, // "already done" starts folded up
  showAreaChips: true,     // colour-coded School / Pre-Med / Trading / … tags
  showCalendarLabels: true, // show which calendar each event came from
  maxOccurrenceIterations: 15000, // safety cap when expanding repeating events
};
