# Bay One Construction & Remodeling — website

Static site. No build step, no dependencies. Open `index.html` in a browser and it works.

```
index.html      Home
services.html   Five service sections (#interior #kitchen-bath #additions #adu #new-construction)
projects.html   Photo gallery
about.html      Simon / how we work
contact.html    Estimate form + direct contact
thanks.html     Form success page (noindex)
assets/         site.css, site.js, favicon.svg
netlify.toml    Headers + publish config
robots.txt, sitemap.xml
```

## Deploy

Netlify (recommended — the contact form depends on it):

1. Push this folder to a repo, or drag it onto https://app.netlify.com/drop
2. Set the publish directory to `bayone-site`
3. Netlify auto-detects the `data-netlify="true"` form. In **Forms → Notifications**,
   add an email notification to `bayone1@yahoo.com`.
4. Add the custom domain and let Netlify issue the SSL cert.

Cloudflare Pages works too, but the form will need a different backend
(Formspree, Web3Forms) — swap the `<form>` attributes in `contact.html`.

---

## BEFORE LAUNCH — required

These are placeholders. The site should not go live with them as-is.

| Item | Where | Why |
|---|---|---|
| **CSLB license number** | footer of every page (`000000`) | California law requires the license number on contractor advertising. This is the one true blocker. |
| **Real domain** | `SITE=` in the generator, `canonical`/`og:url` in each `<head>`, `robots.txt`, `sitemap.xml`, schema JSON-LD | Currently `bayoneconstruction.com` as a guess. Find-and-replace once the domain is bought. |
| **Project photos** | every `<div class="ph">` block | 15–20 real job photos. Delete any gallery card you don't have a photo for — don't ship the striped placeholder. |
| **Photo of Simon** | `index.html`, `about.html` | Owner-run is the whole pitch; a face sells it. |
| **Service-area cities** | `index.html` chips + schema `areaServed` | Currently my best guess from the 510 area code. Confirm with Simon. |
| **Business hours** | `contact.html`, footer, schema | Currently Mon–Sat 8–6. Confirm. |
| **`assets/og.jpg`** | referenced by `og:image` | 1200×630 social share image. Doesn't exist yet — a good finished-kitchen shot with the logo works. |
| **Facebook URL** | footer, contact page, schema `sameAs` | Verify the profile ID resolves to the right page. |

Every one of these is also marked with a `<!-- TODO -->` comment in the HTML:

```
grep -rn "TODO" .
```

## Deliberately not included

- **Testimonials.** The Facebook page shows 0 reviews. There is no honest way to
  write these yet. Get 5 real Google reviews first, then add a testimonials
  section to `about.html` and link the Google Business Profile.
- **Analytics.** Add Plausible or GA4 before launch if he wants lead tracking.

## Highest-leverage thing after launch

A Google Business Profile with real reviews will bring in more calls than this
website will. The site's job is to make people trust him once they find him;
the profile is how they find him.

## Editing notes

- Colors live in `:root` at the top of `assets/site.css`.
- The header and footer are duplicated across pages (deliberate — no build step).
  If you change one, change all six. `bayone-site/../scratchpad` had a generator,
  but hand-editing six files is honestly fine at this size.
- The mobile sticky call bar is `.callbar`, shown under 860px only.
