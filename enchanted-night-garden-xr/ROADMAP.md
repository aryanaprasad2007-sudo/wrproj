# Enchanted Night Garden XR — Development Roadmap

**Principle:** each phase has an **exit criterion**. Do not start a phase until the previous one's criterion is met. The purpose of the gates is to stop the project from becoming a large system that has never been worn at night.

Phase durations assume evenings and weekends around a pre-med course load, not full-time work. They are estimates, not commitments.

---

## Phase 0 — Research ✅ COMPLETE

**Delivered:** `RESEARCH.md`, `ARCHITECTURE.md`, `ROADMAP.md`, `PROTOTYPE.md`, `UNKNOWNS.md`.

**Key outcomes:** standalone Quest 3 app with PC companion; PCVR/Virtual Desktop ruled out; monitor readability identified as the critical risk.

---

## Phase 0.5 — Empirical reality check ✅ **ESSENTIALLY COMPLETE (2026-08-09)**

| Test | Result |
|---|---|
| #1 Monitor through passthrough | ❌ Hard to read → Route B dropped |
| #1b Night lighting | ✅ Solved — controllable LEDs available |
| #2 Panel over immersive app | ✅ **PASS** — MR Link + Beat Saber simultaneously, text 1:1 readable |
| #3 Space Setup labels | 🟡 Partial — an "office" space exists and fits the room; the **label list** is still unrecorded |

**Both project-threatening risks are now closed.** Remaining: read out what `office` actually labeled the desk, dresser, monitor and bed as. That is a Phase 1 debug-overlay task, not a blocker — Phase 1 can start now.

*Original phase description follows for reference.*

**~30–60 minutes. No code. No Unity install.**

This phase exists because two unknowns can invalidate significant design work, and both can be tested by putting the headset on tonight.

1. **Monitor readability test** — Test #1 in `UNKNOWNS.md`
2. **Seamless Multitasking coexistence test** — Test #2
3. **Space Setup labeling test** — Test #3 (run Space Setup, note what your desk, dresser, bed and monitor actually get labeled as)
4. **Night-lighting passthrough test** — Test #1b (how noisy is passthrough at your actual bedtime lighting?)

**Exit criterion:** you know which computer-integration route (`RESEARCH.md` §5) you are building toward, and whether nighttime passthrough looks acceptable in your room.

**This phase can change the plan.** If Route A works, Phase 5 becomes trivial. If nothing works, we have an honest conversation about scope before you have invested weeks.

---

## Phase 1 — Passthrough + spatial alignment prototype

**~1 week of evenings.** Full detail in `PROTOTYPE.md`.

Smallest Unity app that proves the room is understood and stays put: MRUK wireframe over real surfaces, one nighttime Color LUT, Depth API occlusion on, one anchored glowing flower, one anchored vine segment, panic fade, persistence across restart.

**Exit criterion:** you restart the app the next night and the flower is in the same physical spot, the wireframe still hugs your real walls, and the LUT makes your bedroom feel like night. Held at 72Hz.

**Stop here if it fails.** No amount of art fixes broken spatial alignment.

---

## Phase 2 — Room model and role assignment

**~1 week.**

- `RoomModel` module: MRUK ingest, surfaces/corners/free-floor queries
- Role assignment flow: point at an anchor, pick "desk" / "dresser" / "bed" / "monitor" / "chair" from a list
- Persist role map via spatial anchors + local JSON; restore on launch
- `SafetyPolicy` skeleton with keep-clear volumes and the policy you chose in `ARCHITECTURE.md` §8

**Exit criterion:** the app can state, out loud in a debug overlay, "this is your desk, this is your bed, this is your dresser, this is 1.9m² of free floor" — correctly, after a restart, without you re-teaching it.

---

## Phase 3 — Garden environment (the first pretty build)

**~2–3 weeks.** The first phase that produces something you would show someone.

- One preset only: **Midnight Garden**
- Vines on wall planes, moss on floor, canopy + stars on ceiling, fireflies, subtle fog
- Baked lighting, emissive glow, GPU instancing from the start
- `EnvironmentController` with the global intensity value
- Deterministic generation from a persisted seed
- Profile against the GPU budget every few days, not at the end

**Exit criterion:** you sit in your room at night, and it reads as *an enchanted garden that is still your bedroom*. Stable 72Hz. You want to stay in it for twenty minutes.

---

## Phase 4 — Furniture integration

**~1–2 weeks.**

Role-specific decoration: desk becomes an enchanted workstation, bed gets a soft glow perimeter and hanging vines, dresser gets moss and mushrooms, corners get larger plant forms. `SafetyPolicy` actively vetoing placements.

**Exit criterion:** the garden is visibly *shaped by your specific room* — someone watching a recording could tell where your furniture is without seeing it.

---

## Phase 5 — Computer integration ✅ **ROUTE DECIDED**

**~2–3 days.** Settled by hardware testing on 2026-08-09: **Route A** (Mixed Reality Link panel over the immersive app) is confirmed working with third-party Unity apps at 1:1 readable text. Routes B and C are shelved.

- Read the `SCREEN` anchor from `RoomModel`; register a keep-clear region there with `SafetyPolicy`
- Decorative framing *around* that region — vines up the monitor's flanks, a lantern above, moss along the desk edge beneath it
- Framing must be **forgiving of a few centimetres of misalignment**, since the app cannot query the OS window's actual position
- Pin the Mixed Reality Link window over the real monitor once; verify it survives sleep/wake

**Exit criterion:** you write code, or reply to an email, for thirty minutes without leaving the garden and without eye strain.

**Note:** this phase can be pulled forward and merged into Phase 4 if you want to be *working* inside the garden earlier. It is now cheap enough that it no longer needs its own slot.

---

## Phase 6 — Dynamic behavior and the PC companion

**~2 weeks.**

- Python WebSocket service: audio FFT, activity/idle state, clock and moon phase
- Quest client with graceful degradation when the PC is off
- Flowers pulse to bass; fireflies scatter on transients; garden calms after N minutes of keyboard silence; moon tracks real time
- `AudioSystem`: spatialized ambience beds

**Exit criterion:** the room noticeably responds to your music and to whether you are working — and behaves correctly with the PC powered off.

---

## Phase 7 — Presets and interaction

**~2 weeks.**

- Rain Garden, Moonflower Garden, Astral Garden, Spirit Garden as ScriptableObject data
- LUT blending for smooth transitions
- Minimal interaction: preset switch, global dim, panic fade
- "Lying down" detection → shift toward the calmest preset

**Exit criterion:** switching presets is one gesture and the transition is smooth, not a hard cut.

---

## Phase 8 — Optimization and comfort pass

**~1–2 weeks.**

- Profile with OVR Metrics; tune foveated rendering
- Overdraw audit per preset
- Global brightness control tuned for late-night eyes
- Auto-fade after prolonged stillness
- Battery/thermal check over a 90-minute session

**Exit criterion:** a 90-minute session at 72Hz with no thermal throttling, and you actually want to put it on again tomorrow.

---

## Phase 9 — Living with it

Not a development phase. Use it nightly for two weeks and keep a list. The gap between "impressive demo" and "thing you use every night" only shows up here, and the fixes it generates are usually small.

---

## Ordering rationale

Two deliberate deviations from your proposed structure:

**Computer integration moved earlier in *investigation* (Phase 0.5) but stays late in *implementation* (Phase 5).** The unknown is front-loaded because it can change the architecture; the build is back-loaded because it is cheap once the answer is known.

**Room understanding split across Phases 1 and 2.** Phase 1 proves alignment works at all with the crudest possible visualization. Phase 2 builds the real model. Proving alignment is the risky part and deserves to be isolated from the module design.
