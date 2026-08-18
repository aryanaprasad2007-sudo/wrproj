# Technical Unknowns — things that must be tested, not researched

Documentation cannot answer these. They depend on your specific room, lighting, hardware, and eyes. Each has a **cost to test** and a **consequence if it fails**, and they are ordered so the cheapest, most consequential ones come first.

Fill in the Result column as you go — this file is the project's lab notebook.

---

## Tier 1 — Test before writing any code

### Test #1 — Can you read your monitor through Quest 3 passthrough?

- **Cost:** 5 minutes, no code
- **Method:** Headset on at your desk, normal bedtime lighting, look at your monitor through passthrough, try to read a line of code at your usual font size. Then try at 150% zoom.
- **Expected:** Failure at normal size. Research points strongly this way (~18 PPD central, ~4MP cameras, grainy, worsened by auto-exposure on a bright screen).
- **If it fails:** Route B in `RESEARCH.md` §5 is dead; computer integration depends on Route A or C.
- **If it unexpectedly succeeds:** Route B becomes the cheapest possible solution and Phase 5 collapses to a few days.
- **Result (2026-08-09, Ari):** "Kind of hard to do." → **Route B deprioritized.** Matches the predicted failure. Not formally dead — worth one more deliberate check at a large font before Phase 5 — but it cannot be the primary way you work in this environment.

### Test #1b — How bad is passthrough at your actual night lighting?

- **Cost:** 5 minutes, same session
- **Method:** Look around your room through passthrough at the light level you would actually use this at. Judge noise, smear, and color fidelity. Then turn on one warm lamp and compare.
- **Why it matters:** You are designing for the worst-case lighting condition for these cameras. This determines how much of the final view can be raw passthrough versus virtual geometry.
- **If it fails:** raise virtual density in the design; add a dimmable warm lamp to the room (and consider making it smart-controllable so the app can dim it in sync with presets).
- **Result (2026-08-09, Ari):** **Not a problem — LED lights available at night.** Risk #2 in `RESEARCH.md` §9 drops from **HIGH → LOW**.
- **Follow-up worth 2 minutes:** saturated colored LEDs (deep purple/blue strips) look great to the eye but can read as *noisy* to the passthrough cameras, which meter poorly on narrow-spectrum light. Compare passthrough under warm-white vs. your usual color. If warm-white is visibly cleaner, the design answer is: **warm-white in the room, purple in the LUT.** The camera gets clean input; the headset does the color.
- **Opportunity this unlocks:** if those LEDs are smart-controllable, the PC companion service can drive them — the real room dims and shifts hue in sync with the garden preset. That is the single cheapest "magic" effect available in this whole project, and it works on the half of your visual field the headset can't improve.

### Test #2 — Does a Remote Display / Mixed Reality Link window survive inside a third-party immersive app?

- **Cost:** 10 minutes, no code
- **Method:** Open Mixed Reality Link, confirm sharp text, then launch any third-party immersive app from your library. Check: does the window persist? Stay readable? Stay pinned? Remain interactive? Does it survive for 20+ minutes?
- **Status in research:** Seamless Multitasking graduated from experimental around v83 with roughly three windows over immersive apps — but I could not confirm that **Remote Display specifically** works over a **third-party Unity app**.
- **If it succeeds:** this is the answer to computer integration and it costs you nothing. Phase 5 becomes ~3 days.
- **If it fails:** Route C (custom desktop streaming, ~3–5 weeks) becomes the likely path, and you should decide up front whether that is worth it.
- **Result (2026-08-09, Ari): ✅ PASS — decisively.** Mixed Reality Link works in both passthrough and Meta environments. Ran it **simultaneously with Beat Saber**: the window stayed open, stayed usable, and **text was "perfectly readable and 1 to 1."**
- **Why this is strong evidence:** Beat Saber is a Unity-built, fully immersive, third-party app — structurally the same category as the garden. This is close to a direct test of the real scenario, not an analogue.
- **Consequence:** **Route A is the computer-integration architecture.** Phase 5 drops from ~3–5 weeks to ~3 days. Route C (custom NVENC/WebRTC desktop streaming) is shelved indefinitely — do not build it. Risk #1 in `RESEARCH.md` §9 downgrades **CRITICAL → LOW**.

#### Test #2 follow-ups (small, cheap, answer during Phase 1)

Route A works. These four sub-questions only shape *how well* it works, and none of them threaten the architecture:

| # | Question | Why it matters | Answer by |
|---|---|---|---|
| 2a | Does it also work over a **sideloaded / dev-built** app, not just store-signed ones? | The garden will be sideloaded via MQDH. Almost certainly fine, but it is the one structural difference from the Beat Saber test. | Phase 1, first build on device |
| 2b | Does having the window open **cost frame time** in the immersive app? | The OS composites an extra layer. If it costs 1–2ms, that comes out of the art budget. | Phase 1 debug overlay — measure with the window open vs. closed |
| 2c | Does the window **stay pinned** across a garden app restart and a headset sleep/wake? | Determines whether "screen framing" needs re-setup nightly. | Phase 1, second-night check |
| 2d | Can the window be pinned **exactly over the real monitor's position**? | If yes, the framing vines line up with real hardware and the illusion closes. If it drifts, framing has to be looser and more forgiving. | Phase 1, alongside Test #3 |
| **Result:** | | | _______________ |

### Test #3 — What does Space Setup actually label your furniture as?

- **Cost:** 10 minutes, no code
- **Method:** Run Space Setup in your bedroom. Record the label assigned to your desk, dresser, bed, monitor, chair, and anything else significant.
- **Where it lives:** `Settings → Physical space → Spaces → Set up`, or `Settings → Environment setup`. It also offers itself automatically the first time you launch an app that needs room data.
- **What it does:** a guided walk-around scan. **Assisted Space Setup auto-detects and labels furniture** — walls, tables, couches, doors, windows — so most of it happens without you placing boxes by hand. Manual add/adjust is available as a fallback and for anything it misses.
- **Known constraint:** even when detection works perfectly, the label *vocabulary* has no `DESK`, `DRESSER`, `CHAIR` or `MONITOR`. Expect `TABLE`, `STORAGE`, `OTHER`, `SCREEN`. That is why the role-assignment layer in `ARCHITECTURE.md` §3.1 exists.
- **Why it matters:** shows how many same-label anchors you will need to disambiguate (e.g. two `TABLE`s = desk + nightstand).
- **Result:** _______________

---

## Tier 2 — Answered by the Phase 1 prototype

### Test #4 — Anchor drift over a real session

- **Cost:** built into the prototype's debug overlay
- **Method:** Note the anchored flower's position at session start; check after 30 minutes, after 2 hours, and after a headset sleep/wake cycle.
- **Why it matters:** determines whether foliage can sit flush against real surfaces or must be designed with organic tolerance for a few centimetres of slip.
- **Result:** _______________

### Test #5 — Does a nighttime Color LUT read as "moonlit" or as "dark noisy room"?

- **Cost:** part of the prototype; a few hours of LUT authoring
- **Method:** Toggle the LUT on and off with a controller button and judge honestly. Try two or three LUTs with different approaches (cool desaturate, blue-purple push, contrast lift).
- **Why it matters:** this is the core visual conceit. Everything else is decoration on top of it.
- **If it fails:** redesign toward higher virtual density before Phase 3.
- **Result:** _______________

### Test #6 — Depth API occlusion quality on thin geometry

- **Cost:** part of the prototype
- **Method:** Place a thin vine against a real wall and a thicker one; compare edge stability. Test hard vs soft occlusion mode and note the GPU cost difference.
- **Why it matters:** determines the minimum thickness of every plant asset you author. Cheap to know now, expensive to discover after authoring a foliage library.
- **Result:** _______________

### Test #7 — Real GPU budget with passthrough + depth on

- **Cost:** part of the prototype's overlay
- **Method:** Measure GPU frame time with passthrough + Depth API + LUT active and near-zero content. Subtract from the 13.9ms (72Hz) budget.
- **Why it matters:** this number is your actual art budget, and every later phase is scored against it.
- **Result:** _______________

---

## Tier 3 — Later phases

### Test #8 — Instanced foliage density before frame drops

- **When:** Phase 3
- **Method:** Ramp instanced vine/moss count until GPU time exceeds budget. Record the number.
- **Result:** _______________

### Test #9 — Particle/fog overdraw ceiling

- **When:** Phase 3
- **Method:** Same ramp method for fireflies and fog. Overdraw, not particle count, is the real limit.
- **Result:** _______________

### Test #10 — WebSocket reliability and latency from the PC companion

- **When:** Phase 6
- **Method:** Run for 90 minutes; measure dropped connections and message latency. Confirm the app behaves correctly with the PC powered off mid-session.
- **Result:** _______________

### Test #11 — Thermal and battery over a 90-minute night session

- **When:** Phase 8
- **Method:** Full session with the finished environment; watch for throttling and note battery drain.
- **Why it matters:** determines whether this is a nightly-use system or a demo.
- **Result:** _______________

---

## Unverified research claims

Things I could not confirm from primary documentation. None block the recommended architecture, but they are recorded honestly.

| Claim | Source quality | Impact if wrong |
|---|---|---|
| Virtual Desktop offers only *user-controlled* chroma-key masking, with no application-controlled passthrough | Developer statement on Unreal forums, corroborated by PassthroughForge describing its Quest 3 pipeline as VD chroma-key composition and listing native passthrough extensions as roadmap. **No statement found in Virtual Desktop's own documentation.** | Low. Even if VD gained app-controlled passthrough tomorrow, Architecture B still has no Scene API, MRUK, Depth API or anchors — the disqualifying gap is room understanding, not passthrough. |
| Seamless Multitasking supports ~3 windows over third-party immersive apps as of ~v83 | Meta release notes summary + UploadVR coverage; the primary UploadVR article I read described the older v69 experimental version | Medium. Directly determines Phase 5 cost. **This is exactly what Test #2 exists to settle.** |
| High-Fidelity Scene is archived | Stated directly on Meta's own documentation page | Low. MRUK is the documented replacement either way. |
| Passthrough degrades significantly in low light | Widely reported hardware characteristic, not a documented spec | Medium. Test #1b settles it for your room specifically. |
