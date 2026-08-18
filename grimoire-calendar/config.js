/* Grimoire Calendar — configuration.

   Put SECRET calendar URLs in config.local.js instead of here (copy
   config.example.js). A Google "private address in iCal format" is a bearer
   token: anyone who has that URL can read your whole calendar forever, without
   logging in. It does not belong in a file you might screenshot or sync.

   Precedence: config.local.js overrides config.js. `calendars` replaces the
   whole array rather than merging, so copy every calendar you want. */

export const CONFIG = {
  /* --- calendars -------------------------------------------------------
     `area` tags a whole feed so events get coloured/grouped without guessing
     from the title. Leave it null to let areas.js infer from the text. */
  calendars: [
    { id: 'primary', label: 'Primary',  area: null,     enabled: true, url: '' },
    { id: 'canvas',  label: 'Canvas',   area: 'School', enabled: true, url: '' },
    { id: 'holiday', label: 'Holidays', area: null,     enabled: true,
      url: 'https://calendar.google.com/calendar/ical/en.usa%23holiday%40group.v.calendar.google.com/public/basic.ics' },
  ],

  /* --- fetching --------------------------------------------------------
     Google's iCal endpoint sends no Access-Control-Allow-Origin header, so a
     browser will not let this page read it directly. tools/serve.py runs a
     tiny local passthrough at /ics?cal=<index> to get around that; it is the
     reason you launch via Grimoire-Calendar.bat rather than double-clicking
     index.html. Set to null if you deploy this somewhere with its own proxy. */
  icsProxyPath: '/ics',
  useCorsRelay: false,
  corsRelays: [],

  /* --- month grid ------------------------------------------------------
     'dots'  one area-coloured pip per event — reads as a heat map of how full
             each day is and what kind of full. Right for a real routine.
     'chips' truncated event titles — only legible on a sparse calendar. */
  monthDetail: 'dots',

  /* --- look ------------------------------------------------------------
     Drop a wallpaper in icons/ (or anywhere under this folder) and point at it.
     Opacity is deliberately low: this sits behind small text all day.
     0.30 is about the ceiling before event titles start to fight the image. */
  wallpaper: null,          // e.g. './icons/sakura-night.jpg'
  wallpaperOpacity: 0.30,

  /* --- formatting ------------------------------------------------------ */
  timeZone: 'America/Los_Angeles',
  locale: 'en-US',
  hour12: true,
};
