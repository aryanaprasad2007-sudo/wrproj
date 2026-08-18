# Recommended Prototype Plan

**Scope discipline:** everything in this document should take about a week of evenings. If it is taking three weeks, something out of scope has crept in — check it against §4.

---

## 1. What the prototype is actually for

You framed the prototype question as:

> *"Can I sit in my real bedroom wearing the Quest 3 and see a convincing magical garden surrounding my real environment while retaining access to my computer?"*

That is the right question for the **project**. It is the wrong question for the **prototype**, because it bundles four independent risks, three of which are already resolved:

| Sub-question | Status after research |
|---|---|
| Can the Quest 3 show a garden around my room? | **Answered.** Documented APIs, Meta's own samples do this. |
| Can it know where my walls and furniture are? | **Answered.** Scene API / MRUK, shipping. |
| Will it stay aligned to my real room and persist? | **Unproven in your room.** ← prototype target |
| Can I use my computer inside it? | **Unproven, and hardware-limited.** ← test *before* the prototype |

So the prototype answers one question — **"does my real bedroom stay convincingly and safely aligned under a virtual layer, across sessions?"** — and the computer question is answered first, without code, in Phase 0.5.

---

## 2. Step 0 — the no-code test (do this tonight)

Before installing Unity. Roughly thirty minutes.

1. Sit at your desk at your normal bedtime lighting. Put the Quest 3 on. Look at your monitor through passthrough. **Try to read a line of code at your normal font size.** Note what happens to the rest of the room's exposure while you do.
2. Open Meta's Remote Display / Mixed Reality Link. Confirm text is sharp in that window.
3. With that window open, launch *any* third-party immersive app (a game, anything from your library). See whether the window survives, stays readable, stays put, and remains interactive.
4. Run Space Setup. Write down exactly what label your desk, dresser, bed, monitor and chair each receive.

Record results in `UNKNOWNS.md`. These four observations determine Phase 5's scope, which ranges from three days to five weeks.

---

## 3. Step 1 — the build

**One Unity 6 project. Roughly six scripts. No art beyond two placeholder objects.**

### Setup
- Unity 6 LTS + Meta XR Core SDK v83+ + MRUK v83+ + Unity OpenXR Plugin + URP
- Pin the versions in a `VERSIONS.md`. Do not update mid-prototype.
- Android build target, developer mode on headset, MQDH connected

### The six things it does

1. **Passthrough on, room loaded.** MRUK ingest at startup. Handle "no room scanned" with a clear message rather than a crash.
2. **Wireframe the room.** Draw a thin glowing outline over every detected plane and volume, with its semantic label rendered next to it in world space. Ugly is fine — this is a measuring instrument, not a view.
3. **One nighttime Color LUT.** A single 32³ LUT pushing the room toward deep blue/purple. Bind it to a controller button so you can toggle it on and off and judge the difference honestly.
4. **Depth API occlusion on.** Hard mode initially. Verify a real hand passes correctly in front of virtual geometry.
5. **Two anchored objects.** One glowing flower on the floor, one vine segment on a wall. Both created as spatial anchors, both persisted to local JSON by UUID, both restored on launch.
6. **Panic fade.** One button drops all virtual content to near-zero opacity. Build it now, before there is anything worth fading, so it is never retrofitted.

### The debug overlay

Small, head-locked, always on: current FPS, GPU frame time, anchor count, and drift estimate (distance between the flower's current position and its position at session start). You will learn more from this overlay than from any screenshot.

---

## 4. Explicitly out of scope

Building any of these in the prototype is the failure mode your own development philosophy warns about:

- ❌ Procedural generation of any kind
- ❌ More than one preset
- ❌ Audio, audio reactivity, or the PC companion service
- ❌ Particles beyond a token handful of fireflies
- ❌ Hand tracking or gesture interaction
- ❌ The role-assignment UI (Phase 2)
- ❌ Any authored art asset — placeholder primitives with emissive materials only
- ❌ Route C desktop streaming
- ❌ Multiple rooms, settings menus, or save systems beyond one JSON file

---

## 5. Success criteria

The prototype succeeds if, on the **second** night — a fresh launch, after the headset has slept:

| # | Criterion | Why it matters |
|---|---|---|
| 1 | The wireframe sits on your real walls within a few centimetres | Alignment is the foundation; nothing survives its failure |
| 2 | The flower is in the same physical spot as last night | Proves anchor persistence end to end |
| 3 | Drift over 30 minutes stays small enough that the vine still looks attached to the wall | Determines art constraints for every later phase |
| 4 | The LUT makes your bedroom feel like nighttime rather than like a dimmed camera feed | Determines whether the core visual conceit works at all |
| 5 | Depth occlusion reads correctly on your hand and on the vine's edges | Determines how thin foliage can be |
| 6 | You can stand up and walk to your bed without hesitating | The safety floor — non-negotiable |
| 7 | Held 72Hz throughout | Establishes the real budget before art exists |

**Criterion 4 is the sleeper.** If a color-remapped passthrough feed at night reads as "noisy dark room" rather than "moonlit garden," the entire visual approach needs rethinking — probably toward a denser virtual layer where less raw camera feed is visible. Better to learn that with two placeholder objects than after three weeks of foliage authoring.

---

## 6. What to do with the result

**If criteria 1–3 and 6–7 pass:** proceed to Phase 2. The foundation is sound.

**If criterion 4 fails:** stop and redesign the visual approach before Phase 3. Options include raising virtual density, adding warm physical ambient light to the room, or accepting a brighter-than-realistic "moonlight" that photographs badly but looks good live.

**If criterion 1, 2 or 3 fails:** debug before building anything else. Persistent misalignment usually traces to Space Setup quality, and re-scanning the room carefully fixes most of it.

**If criterion 6 fails:** that is a `SafetyPolicy` design failure, and it is the one failure mode worth being genuinely strict about. Fix it before adding a single decoration.
