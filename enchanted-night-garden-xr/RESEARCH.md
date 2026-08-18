# Enchanted Night Garden XR — Technical Research

**Date:** 2026-08-09
**Target hardware:** Meta Quest 3, PC with Intel Core Ultra i7-class CPU + NVIDIA RTX 4060 Ti, Wi-Fi 6/6E, Virtual Desktop
**Status:** Phase 0 research. No implementation started.

> **How to read the confidence tags in this document**
>
> | Tag | Meaning |
> |---|---|
> | **SUPPORTED** | Shipping, documented Meta API. Safe to build on. |
> | **SUPPORTED (CAVEATS)** | Shipping, but with limits that materially affect this project. |
> | **DIFFICULT** | Technically possible, no first-party path, significant custom work. |
> | **EXPERIMENTAL** | Recently shipped, changing, or dev-only. Do not build the core on it. |
> | **UNSUPPORTED** | No API exists. Would require Meta to ship something new. |
> | **UNVERIFIED** | I could not confirm this from documentation. Must be tested on your hardware. See `UNKNOWNS.md`. |

---

## 1. Executive Summary

**The vision is achievable, but not in the shape you probably imagined it.**

The core experience — sitting in your real bedroom at night, wearing the Quest 3, surrounded by a moonlit garden that grows over your real walls, floor, bed, desk and dresser, with your real room still spatially intact and safe — is **achievable today with shipping, documented APIs**. Room understanding, furniture-aware placement, persistent anchoring, passthrough color grading, and real-world occlusion are all first-party Meta features that exist right now.

Three findings reshape the project, and you should read them before anything else.

### Finding 1 — Your PC is on the wrong side of the API boundary

Every capability this concept depends on lives in Horizon OS and runs **on the headset**:

- Passthrough Color LUT (the only way to tint your real room blue/purple) — headset only
- Depth API occlusion (real objects occluding virtual plants) — headset only
- Scene API / MRUK room and furniture data — headset only
- Spatial Anchors and persistence — headset only

None of these are available to a PCVR application streamed through Virtual Desktop. **Virtual Desktop does not expose application-controlled passthrough at all** — it offers user-controlled chroma-key masking, which is a fundamentally cruder mechanism (details in §2, Architecture B). Meta's own `Passthrough over Link`, which *does* expose the real API to a PC app, is explicitly documented as a **developer-only feature requiring a wired USB-C cable** and is not shippable.

The practical consequence: **the garden must render on the Quest 3's Snapdragon XR2 Gen 2, not on your RTX 4060 Ti.** Your PC is not useless — it becomes a companion compute and data service (§2, Architecture E) — but it is not the renderer. Plan your art budget accordingly.

### Finding 2 — Passthrough cannot make your monitor readable

This is the single biggest risk to your stated requirements, and it is a hardware limit, not a software one.

The Quest 3's passthrough cameras are roughly 4MP and the headset delivers approximately **18 pixels per degree at the center of view**. Comfortable small-text reading generally wants 50+ PPD. Reports of trying to read a physical monitor through Quest 3 passthrough are consistently negative: grainy, blurry, worsened by the camera auto-exposing for the bright screen. On top of that, **passthrough image quality degrades badly in low light** — and you are explicitly designing a *nighttime* experience, which is the worst case for these cameras.

So "my real monitors remain visible and readable through passthrough" is, with high confidence, **not achievable at normal font sizes**. This does not kill the requirement — it changes how you satisfy it. The answer is a *virtual* screen showing your real desktop, positioned exactly where your physical monitor sits, framed by vines and lanterns. Three routes to that exist, ranked in §5 and §7, and testing them is Prototype Step 1.

### Finding 3 — You cannot custom-shade the passthrough feed

The passthrough image is composited by the **system compositor**, not by your app's render pipeline, because it must be reprojected at the last possible moment for latency. Your shaders never see it.

What you get is the documented styling surface: opacity, edge rendering, brightness/contrast/saturation, posterization, and **Color LUTs** (including blending between two LUTs, which gives you smooth transitions between environment presets). That is genuinely a lot — a well-authored LUT can push your real room toward deep blue/purple moonlight convincingly. But understand what it is: a **color remap of the camera image**, not relighting. You cannot cast a virtual moon's light onto your real bedspread and have it respond correctly. You can only recolor the pixels that are already there.

The Passthrough Camera API (v76+, public) *does* give you raw camera frames — but at 1280×960 or 1280×1280, 60Hz, with **20–40ms capture latency** and a field of view narrower than what you actually see. That is fine for computer vision. It is **useless as a replacement for system passthrough** — re-rendering it as your background would produce a laggy, cropped, nauseating image.

### Verdict

| Requirement | Verdict |
|---|---|
| Real bedroom preserved, spatially aligned | **Achievable** — Scene API + MRUK, shipping |
| Bed / desk / dresser stay where they are | **Achievable** — with labeling caveats (§4) |
| Vines on walls, moss on floor, moonlit ceiling | **Achievable** — MRUK plane queries + instanced geometry |
| Real room tinted to a nighttime palette | **Achievable** — Passthrough Color LUT |
| Real objects occlude virtual plants | **Achievable** — Depth API |
| Layout remembered between sessions | **Achievable** — Spatial Anchors |
| Safe navigation of the real room | **Achievable** — and should be a hard design constraint |
| Physical monitors readable through passthrough | **Not achievable** — replace with a virtual screen |
| Computer usable inside the environment | **Confirmed achievable** — Route A verified on hardware 2026-08-09 |
| PC GPU renders the garden | **Not achievable** with the room-understanding features |
| Custom real-time shading of the real room | **Not achievable** — no API |
| Music / activity / time reactivity | **Achievable** — mostly a PC-companion problem, not an XR problem |

**Bottom line: build it, but build it as a standalone Quest 3 application with a PC companion service. Do not build it as a PCVR application.**

---

## 2. Architecture Options

I evaluated five. Three are the serious candidates; two are documented so you can see why they were rejected.

---

### Architecture A — Native standalone Quest 3 MR app (Unity + Meta XR SDK)

**How it works.** A Unity application built for Android/Horizon OS, running entirely on the headset. Uses the Meta XR Core SDK for passthrough and Depth API, MRUK for room understanding, and Spatial Anchors for persistence. Passthrough is the base layer; the garden is rendered as additive geometry on top of it; the system compositor blends them.

| Dimension | Assessment |
|---|---|
| **Advantages** | Only architecture with access to Scene API, MRUK, Depth API, Passthrough LUT, Spatial Anchors. Fully wireless. Works with the PC off. Persists across sessions. Standard, well-documented toolchain. |
| **Disadvantages** | Mobile-class GPU. Passthrough itself consumes **20–40% of the GPU budget**. No access to your 4060 Ti for rendering. Computer integration requires a separate solution. Art must be heavily optimized. |
| **Performance** | Snapdragon XR2 Gen 2. Realistic target: **72Hz** for a calm nighttime experience (90Hz achievable if the scene stays lean). Budget after passthrough: roughly 6–8ms GPU. Demands baked lighting, GPU instancing, unlit/simple-lit shaders, tight control of transparent overdraw. |
| **Dev difficulty** | **Moderate.** Well-trodden path with extensive samples. The hard part is art optimization, not API wrangling. |
| **Passthrough quality** | **Best available.** Native system compositor, full reprojection, lowest latency, LUT styling, Depth API occlusion. |
| **Room understanding** | **Full.** Walls, floor, ceiling as planes; furniture as labeled volumes; global mesh; spatial queries; raycasting. |
| **Screen integration** | **Not solved by this architecture alone.** Needs one of the three routes in §5. This is its main weakness. |
| **Extensibility** | **Excellent.** Every long-term feature you listed maps onto shipping APIs. |

---

### Architecture B — PCVR app + Virtual Desktop chroma-key passthrough

**How it works.** You build the garden as a PCVR application rendered on the 4060 Ti and streamed wirelessly by Virtual Desktop. To let the real world show through, you render a specific key color where you want passthrough, and Virtual Desktop's **user-configured** chroma-key masking replaces that color with the camera feed on the headset side.

| Dimension | Assessment |
|---|---|
| **Advantages** | Full RTX 4060 Ti rendering budget — real-time lighting, volumetric fog, dense foliage, proper shadows. Faster art iteration. Desktop access is inherently nearby (Virtual Desktop is already the host). |
| **Disadvantages** | **Disqualifying set.** Virtual Desktop offers *user-controlled* chroma keying, not application-controlled passthrough — your app cannot turn passthrough on, style it, fade it, or vary it per preset. **No Scene API. No MRUK. No furniture data. No Depth API. No Spatial Anchors. No persistence.** You would have to hand-measure and hand-author your room's geometry and re-align it every session. Chroma key is binary per-pixel color matching: no soft edges, no partial transparency, colored key bleed onto your foliage, and shimmer artifacts. Requires the PC running, adds encode/decode latency to everything. |
| **Performance** | Excellent raw rendering. Streaming adds roughly 30–50ms of motion-to-photon latency on good Wi-Fi 6E. |
| **Dev difficulty** | **High** — not because of the engine work, but because you must reimplement room understanding and alignment from scratch, badly. |
| **Passthrough quality** | **Poor for this use case.** Chroma-key compositing, key color bleed, no depth occlusion, no styling, user-managed. |
| **Room understanding** | **None.** Manual authoring only. |
| **Screen integration** | Partially easier — but the readability problem (Finding 2) is unchanged, since it is the same cameras. |
| **Extensibility** | **Poor.** Every long-term goal you listed depends on APIs this architecture cannot reach. |

**Note on evidence:** the "chroma key only, no application-controlled passthrough" claim comes from developer discussion on the Unreal forums and is corroborated by PassthroughForge — a commercial product for DCS/MSFS — which describes its Quest 3 pipeline as Virtual Desktop chroma-key composition and lists *native* passthrough extensions (`XR_FB_passthrough`, `XR_ENVIRONMENT_BLEND_MODE_ALPHA_BLEND`) as **roadmap, not implemented**. That is two independent sources agreeing, but I did not find a definitive statement in Virtual Desktop's own documentation. Flagged as **UNVERIFIED** in `UNKNOWNS.md` — but the room-understanding gap alone is disqualifying regardless of how the chroma key works.

---

### Architecture C — PCVR app + Meta's Passthrough over Link

**How it works.** Meta exposes real `XR_FB_passthrough` to PC applications through Quest Link. A PCVR app built with the Meta XR SDK gets genuine passthrough, and "Spatial Data over Meta Quest Link" can additionally surface scene data to the PC.

| Dimension | Assessment |
|---|---|
| **Advantages** | Real passthrough API *and* PC rendering power. On paper, the best of both. Also genuinely valuable as a **development iteration tool** — you can preview passthrough work in the Unity Editor without deploying to the headset each time. |
| **Disadvantages** | **Disqualifying.** Meta documents this as a **developer-only feature, not shippable to end users**. It requires **a wired USB-C cable** (2 Gbps+ for color passthrough) — wireless is explicitly not supported. It requires "Developer Runtime Features" toggles enabled in the Link PC app. Meta states visual appearance and performance differ from on-device. Camera data is processed on the PC, adding latency. |
| **Performance** | Good rendering; wired Link latency; passthrough path is not the optimized on-device one. |
| **Dev difficulty** | Low to set up, but you would be building your nightly-use system on a tethered developer preview feature. |
| **Passthrough quality** | Real API, but documented as visually different from on-device. |
| **Room understanding** | Available via Spatial Data over Link — but note **you cannot run Space Setup while in Link mode**; the room must be scanned on-device first. |
| **Screen integration** | Same readability problem. |
| **Extensibility** | **Poor.** Built on a feature Meta positions as a dev tool and could change or remove. And you would be tethered by cable, at night, in your bedroom. |

**Verdict: reject as the product architecture, adopt as a development tool.** This is genuinely useful for iterating on the garden in the Unity Editor. Just do not ship on it.

---

### Architecture D — Meta Spatial SDK (Kotlin, engine-free)

**How it works.** Meta's non-game-engine path for Horizon OS. Kotlin, a scene-graph runtime, Meta Spatial Editor for layout. Supports MRUK, passthrough, and the Passthrough Camera API. Strong at mixing 2D Android panels with 3D content.

| Dimension | Assessment |
|---|---|
| **Advantages** | Excellent panel/2D integration — panels can host arbitrary Android views, including a WebView. Lighter weight than a game engine. Good for spatial productivity apps. |
| **Disadvantages** | Weaker rendering and VFX authoring than Unity — and this project is fundamentally a **rendering and atmosphere** project (particles, fog, glowing foliage, animated vines). Smaller ecosystem, fewer samples, less community. Interaction SDK support is newer/beta. |
| **Performance** | Fine for panel-centric apps; not the tool for dense stylized vegetation and particle atmosphere. |
| **Dev difficulty** | **Moderate-high** for a graphics-heavy project. You would fight the tool. |
| **Passthrough quality** | Same native quality as Unity. |
| **Room understanding** | Full MRUK support. |
| **Screen integration** | **Its genuine strength** — an Android panel hosting a WebRTC desktop stream is a natural fit here. |
| **Extensibility** | Good for panels, weak for atmosphere. |

**Verdict: reject as primary, but note it proves the panel-hosting concept.** If Route C in §5 becomes necessary, Spatial SDK's approach is the reference to study.

---

### Architecture E — Hybrid: native standalone renderer + PC companion service ★

**This is the architecture you had not listed, and it is the recommendation.**

**How it works.** Architecture A for everything rendered — the garden lives on the headset, using every native MR API. The PC's role changes from *renderer* to *sensor and service provider*, over ordinary Wi-Fi:

- A lightweight PC daemon (Python or C#) exposes a local WebSocket/HTTP endpoint on your LAN.
- It publishes **music analysis** (FFT bands, beat detection, current track), **computer activity state** (active/idle/typing/keyboard-untouched-for-N-minutes), **real time of day and moon phase**, and **environment preset commands**.
- The Quest app subscribes and drives the garden from that stream: flowers pulse to bass, fireflies scatter on transients, the garden calms when you stop typing, the moon tracks real time.
- Optionally, the same daemon serves the desktop video stream for the virtual monitor (§5, Route C).

| Dimension | Assessment |
|---|---|
| **Advantages** | All of Architecture A's API access, plus a clean path to the entire "Dynamic Behavior" section of your vision. The heavy signal processing (audio FFT, activity monitoring, weather lookups) runs on the CPU that is *already running your music and your work*, not on the headset's power budget. **Degrades gracefully** — with the PC off, the garden runs standalone in a static preset. Clean module boundary. |
| **Disadvantages** | Two codebases. Network reliability handling. Latency on the data channel (irrelevant — tens of ms is imperceptible for ambient reactivity). |
| **Performance** | Identical to A for rendering; the companion service is nearly free (a few % of one CPU core). |
| **Dev difficulty** | **Moderate.** The PC daemon is genuinely easy — a small WebSocket server. The XR side is Architecture A. |
| **Passthrough quality** | Best available (native). |
| **Room understanding** | Full. |
| **Screen integration** | Best positioned — the daemon can also become the desktop stream source if Routes A and B in §5 fail. |
| **Extensibility** | **Excellent.** New reactive inputs are PC-side additions requiring no headset rebuild. Presets, weather modes, and time-of-day logic all slot in cleanly. |

---

### Rejected without full evaluation

- **Custom Horizon Home environment.** Home environments are VR skyboxes/scenes, not mixed reality, and there is no developer path to a passthrough-based custom home. **UNSUPPORTED** for this concept.
- **WebXR / Quest Browser.** No access to Scene API, MRUK, Depth API, or passthrough LUT at parity with native. **UNSUPPORTED** for this concept.
- **Unreal Engine standalone.** Viable in principle — UE5.7 has solid Quest support, mobile Vulkan, foveated rendering, and MRUK. But note the Depth API caveat: the **Epic-distributed** UE + Meta XR Plugin supports only legacy hard occlusion; soft occlusion and depth-texture material access require the **Oculus-VR fork** of Unreal. For a solo nighttime side project, Unity's larger MR sample ecosystem and lighter iteration loop win. Not wrong, just not the best fit here.

---

## 3. Recommended Architecture

**Architecture E — native standalone Unity MR application on Quest 3, with a PC companion service — using Architecture C (Passthrough over Link) purely as a development iteration tool.**

### Why, in terms of your long-term vision rather than short-term ease

You asked me not to simply pick the easiest option. Architecture B (PCVR + Virtual Desktop) is arguably the *easiest to get something pretty on screen quickly*, because you get the 4060 Ti and can throw real-time lights and volumetric fog at the problem. I am rejecting it anyway, and the reason is your own stated long-term vision.

Read back what you asked for: the system should *know* your room. Vines should grow on walls **because they are walls**. A corner should get a tree **because it is a corner**. The desk should become an enchanted workstation **because the system knows where the desk is**. The layout should be **remembered**.

Every one of those sentences is a Scene API / MRUK / Spatial Anchors sentence. Architecture B cannot reach any of them. Choosing B means hand-authoring your bedroom as a 3D model, hand-aligning it every session, and rebuilding it from scratch every time you move a chair. You would get a prettier *first demo* and then hit a wall you cannot climb.

Architecture E gives up real-time lighting and volumetric fog. Those are recoverable losses — baked lighting, emissive materials, and clever billboard/particle work produce a *stylized anime-inspired* look that is arguably better suited to your reference aesthetic than physically-based volumetrics anyway. Your target look is cozy and illustrative, not photoreal. Mobile-class rendering is a good match for that.

### The one thing this architecture does not give you for free

Computer integration. Architecture E has no built-in answer for "my monitor is visible and usable." That is precisely why the prototype (§7) tests it **first**, before a single vine is authored.

### Does the proposed module decomposition make sense?

Your proposed modules — Room Understanding, Spatial Anchoring, Garden Generation, Environment Controller, Computer Integration, Audio, Interaction, Persistence — are a **sound decomposition**, with two corrections:

1. **Room Understanding and Spatial Anchoring are one module, not two.** MRUK already unifies them: scene anchors *are* the room understanding, and they *are* the anchoring primitive. Splitting them creates a seam with nothing on either side of it. Merge into `RoomModel`.
2. **Add a Safety module, and give it authority.** Nothing in your list owns the "you can always tell where real objects are" guarantee. It needs to be an explicit module with veto power over what Garden Generation is allowed to place, not a design intention that erodes as the garden gets prettier.

Full corrected decomposition in `ARCHITECTURE.md`. And per your own instruction: **do not build all eight modules now.** The prototype needs two of them.

---

## 4. Technical Constraints

### 4.1 Rendering and performance

| Constraint | Detail |
|---|---|
| Passthrough GPU tax | **20–40% of GPU budget consumed** by passthrough + MR APIs before you draw anything. |
| Frame budget | 72Hz → 13.9ms; 90Hz → 11.1ms. After passthrough tax, realistically **6–8ms of usable GPU**. Target 72Hz. |
| Transparent overdraw | The dominant risk for this art style. Fog, glow, particles, and layered foliage cards are all transparent. Overdraw is what will kill your framerate, not polygon count. |
| Draw calls | Every vine cluster placed individually is a draw call. **GPU instancing is mandatory**, not an optimization. |
| Trail renderers | Each is its own draw call, rebuilt on the CPU main thread every frame. Firefly trails must be shader-based, not `TrailRenderer`. |
| Real-time lighting | Effectively unaffordable. Bake everything; use emissive materials and light probes for the glow. |
| Post-processing | Extremely limited on mobile XR and it cannot touch passthrough anyway. |

### 4.2 Passthrough

| Constraint | Detail |
|---|---|
| No custom shading | **UNSUPPORTED.** System-composited. Your shaders never see the passthrough image. |
| Styling surface | Opacity, edge rendering, brightness/contrast/saturation, posterize, **Color LUT** (16/32/64 per dimension, power-of-two), LUT blending for smooth preset transitions. |
| Low-light quality | Passthrough is **noisy and smeary in dim rooms** — the exact condition you are designing for. Mitigation: keep modest warm ambient light physically on in the room. This is a real design constraint, not a nitpick. |
| Auto-exposure | A bright monitor in a dark room will drag exposure down, darkening everything else. |
| Resolution | ~18 PPD central. Fine for spatial awareness, insufficient for text. |

### 4.3 Room understanding

| Constraint | Detail |
|---|---|
| **The label set does not match your furniture list** | Supported labels: `FLOOR`, `CEILING`, `WALL_FACE`, `INVISIBLE_WALL_FACE`, `DOOR_FRAME`, `WINDOW_FRAME`, `WALL_ART`, `COUCH`, `TABLE`, `BED`, `LAMP`, `PLANT`, `SCREEN`, `STORAGE`, `OTHER`, `GLOBAL_MESH`. **There is no `DESK`** (use `TABLE`), **no `DRESSER`** (use `STORAGE`), **no `CHAIR`** (falls to `OTHER`), and **no `MONITOR`** (use `SCREEN`). Your garden logic must map onto *these* labels. |
| Labeling is Space-Setup-driven, but mostly automatic | **Corrected 2026-08-09.** The developer docs say room contents are "defined by users during Space Setup," which reads as manual — but **assisted Space Setup auto-detects and labels furniture** (walls, tables, couches, doors, windows) from a guided 3D scan, with manual correction as a fallback. Either way the labeling happens in the **OS**, not in your app: you consume the result, you cannot influence it. |
| Space Setup is OS-owned | You cannot trigger a room scan from your app, and **cannot run Space Setup at all while in Link mode**. |
| High-Fidelity Scene is gone | **Archived and no longer supported** as of the current documentation, despite being a v83-era feature. Do not build on it. Use MRUK. |
| Room limit | The OS maintains up to 15 rooms and locates them based on where you are. |
| Anchor drift | Real but generally modest. **UNVERIFIED** for multi-hour nightly sessions and across sleep/wake cycles — see `UNKNOWNS.md`. |
| Spatial data permission | Requires user permission at runtime. |

### 4.4 Depth / occlusion

| Constraint | Detail |
|---|---|
| Availability | **SUPPORTED** on Quest 3 / 3S. Requires **Unity 6+ and Meta XR Core SDK v74+**. |
| Modes | Hard occlusion (cheaper, jagged edges, temporal instability) and soft occlusion (better looking, more GPU). |
| Quality on thin geometry | Depth maps are low-resolution and noisy at edges. Thin vines against a real wall are a **hard case**. **UNVERIFIED** — must be tested. |

### 4.5 Passthrough Camera API

| Constraint | Detail |
|---|---|
| Availability | **SUPPORTED** publicly since v76 (Unity, Unreal/Native, Spatial SDK). Requires Quest 3/3S, Horizon OS v74+. |
| Specs | 1280×960, or 1280×1280 in v83+ (wider vertical FOV). 60Hz. **20–40ms capture latency.** ~1–2% GPU and ~45MB memory per stream. |
| FOV | **Captures less than you see** even at the higher resolution. |
| Permissions | `android.permission.CAMERA` or `horizonos.permission.HEADSET_CAMERA`. Camera imagery is Device User Data under Meta's data policy. |
| **Not a passthrough replacement** | Latency, crop, and lack of reprojection make it unusable as a rendered background. It is a **computer vision input**, nothing more. |
| Not in XR Simulator | Requires a real device to test. |

### 4.6 Computer integration

| Constraint | Detail |
|---|---|
| Monitor readability via passthrough | **Effectively unachievable at normal font sizes.** The primary constraint of the whole project. |
| Seamless Multitasking | Horizon OS lets users keep windows open while inside immersive apps; graduated from experimental around **v83**, with roughly three floating windows. Whether **Meta Remote Display / Mixed Reality Link** specifically works over a **third-party Unity immersive app**, at usable text quality, is **UNVERIFIED** and is Test #2. |
| OS windows composite on top | If Route A works, those windows are drawn by the OS *above* your app. You can place vines *around* where the window will be, but you cannot occlude it or have your foliage overlap in front of it. Acceptable for the aesthetic, but a real limit. |
| Mixed Reality Link | Windows 11 ↔ Quest 3, GA since late October 2025. Up to three virtual monitors, curved ultrawide mode, passthrough blending. Excellent as a standalone workspace; **the open question is coexistence with a custom immersive app.** |
| Virtual Desktop coexistence | Virtual Desktop is itself an immersive app. It **cannot run simultaneously** with your garden app. Choosing Architecture E means Virtual Desktop is not part of the runtime picture. |

### 4.7 Comfort and safety

| Constraint | Detail |
|---|---|
| Nighttime use | Quest 3 uses LCD panels with backlight glow. Extended late-night use has real melatonin/eye-fatigue implications. Design dim, low-contrast, and warm; give yourself a global brightness control. |
| Headset weight | The stock strap is not comfortable for multi-hour passive use. A counterweighted head strap materially changes whether this system actually gets used. |
| Guardian/boundary | In MR mode the boundary behaves differently than in VR. Never let the garden obscure a real obstacle. |
| **Safety must beat immersion** | Floor paths, the bed edge, the desk edge, and the door must remain unambiguous. This is an explicit design constraint, enforced by a module with veto power (§3). |

---

## 5. Computer Integration — the three routes, ranked

This deserves its own section because it is the highest-risk requirement.

### Route A — Horizon OS Seamless Multitasking window over the immersive app ★ test first

Run your garden as the immersive app; keep a **Meta Remote Display / Mixed Reality Link** window floating over it, pinned in space where your real monitor is.

- **Effort:** Near zero. It is an OS feature.
- **Quality:** Native OS rendering of the desktop stream — sharp, no passthrough camera involved.
- **Status: ✅ VERIFIED ON HARDWARE, 2026-08-09.** Confirmed working simultaneously with Beat Saber — a third-party Unity immersive app. Text reported as "perfectly readable and 1 to 1." Also confirmed working in both passthrough and Meta environments.
- **Limits (unchanged, and now the design constraints to work within):**
  - The window composites **above** your app. Vines can frame it; they can never overlap in front of it.
  - The window is **OS-owned**. Your app cannot query its position, size, or whether it is even open. Framing must be placed from the `SCREEN` scene anchor and *assume* the window is pinned there.
  - Screen dimming tied to activity is **not possible** — the OS owns those pixels.
- **Verdict: adopted.** This is the computer-integration architecture. **Route C is shelved — do not build it.**

### Route B — Passthrough cutout over the real monitor

Render the garden everywhere except a hole where the real monitor sits, so you see the physical screen through passthrough.

- **Effort:** Low. Anchor a quad to the `SCREEN` volume, punch through.
- **Quality:** **Likely unacceptable** (Finding 2). Reserve judgement until you test it at your real desk with your real font sizes.
- **Verdict:** Test it because it is cheap to test and because the answer determines everything else. Expect it to fail.

### Route C — Custom desktop stream into the app

Your PC companion daemon captures the desktop (Windows Desktop Duplication API), encodes with **NVENC on the 4060 Ti**, streams over WebRTC to the Quest app, which decodes via Android MediaCodec onto a quad anchored to your real monitor's position.

- **Effort:** **High.** This is a meaningful subsystem — it is what Virtual Desktop and ALVR do for a living.
- **Quality:** Potentially excellent and fully under your control. Text sharpness limited only by encoder settings and headset PPD (~18 PPD still applies to *rendered* content, but a rendered virtual screen can be scaled up and moved closer, unlike a physical one).
- **Advantage over A:** The screen becomes **your geometry**. Vines can grow *in front of* it, lanterns can hang over its corners, it can dim when you stop typing. It is fully inside the fantasy.
- **Verdict:** The best long-term answer, and the most expensive. **Do not build it in the prototype.** Build it in Phase 5, only if Route A fails or proves too limiting.

---

## 6. Required Software

### Core (required)

| Item | Notes |
|---|---|
| **Unity 6** (LTS) | Required for Depth API. Watch compatibility — there are reports of Meta XR Core SDK 83.0 package errors on Unity 6.3 specifically. Pin a known-good pair. |
| **Meta XR Core SDK** (v83+) | Passthrough, Depth API, anchors, camera API. |
| **Meta MR Utility Kit (MRUK)** (v83+) | Room queries, anchor prefab spawning, EffectMesh, trackables. |
| **Unity OpenXR Plugin** | Recommended over the deprecated Oculus XR Plugin. |
| **URP** | Better Depth API occlusion shader control than Built-in. |
| **Android Build Support** + SDK/NDK/JDK | Standard Unity module. |
| **Meta Quest Developer Hub (MQDH)** | Deployment, logging, performance capture, device management. |
| **Meta Horizon Link PC app** | For Passthrough over Link + Spatial Data over Link development iteration. |
| Developer mode on headset | Plus a developer account. |

### PC companion service

| Item | Notes |
|---|---|
| **Python 3** or **.NET** | Your machine has `py -3` available and no Node/npm — Python is the natural choice here. |
| WebSocket server | `websockets` or `aiohttp`. Pure-Python, vendorable. |
| Audio capture + FFT | WASAPI loopback (`soundcard` / `pyaudiowpatch`) + `numpy` (already present). |
| Activity monitoring | Win32 idle time / foreground window via `ctypes` — no dependencies needed. |

### Optional / later

| Item | Purpose |
|---|---|
| **Blender** | Authoring stylized foliage, lanterns, vine meshes. |
| **Meta XR Simulator** | Fast iteration — but **note the Passthrough Camera API does not work in it**. |
| **RenderDoc / OVR Metrics Tool** | GPU profiling on device. |
| **PassthroughForge** | Only relevant if you ever revisit Architecture B. |
| **ffmpeg / NVENC** | Only if you build Route C (§5). Already present on your machine. |

---

## 7. Required Hardware

### Your existing hardware — verdict

| Item | Verdict |
|---|---|
| **Meta Quest 3** | **Sufficient and required.** Quest 3 (not 3S) is the right device — better passthrough cameras and lenses. Depth API and Passthrough Camera API both require Quest 3/3S. |
| **RTX 4060 Ti + Core Ultra i7** | **Massively sufficient for its actual role.** Under the recommended architecture it runs a Python daemon, Unity builds, and possibly NVENC encoding. It is overqualified. |
| **Wi-Fi (high-quality wireless PCVR capable)** | **Sufficient and now much less critical.** The companion data channel needs kilobits, not gigabits. Only Route C (§5) would need real bandwidth — and your setup already handles it. |
| **Virtual Desktop** | **Not part of the recommended runtime architecture.** Still useful for working on the PC in VR outside the garden app, and for testing Architecture B if you want to see the chroma-key approach with your own eyes. |

**You do not need to buy anything to build this.**

### Things that would meaningfully improve the experience

| Item | Why | Priority |
|---|---|---|
| **Counterweighted head strap** (BOBOVR-style with rear battery) | The single highest-value purchase. Stock strap comfort is the practical limit on multi-hour nighttime use, and the rear battery doubles session length and improves balance. | **High** |
| **Modest warm ambient room light** (smart bulb, dimmable) | Directly improves passthrough image quality, which is your weakest visual link. Being smart-controllable also lets the companion service dim your *real* room in sync with garden presets — a genuinely magical touch. | **High** |
| **USB-C 3.0 Link cable (2 Gbps+)** | Required for Passthrough over Link development iteration. | **Medium** |
| Wi-Fi 6E dedicated AP | Only if you pursue Route C. | **Low** |
| Light-blocking facial interface | Improves black levels and immersion at night. | **Low** |

---

## 8. Prototype Strategy

Full detail in `PROTOTYPE.md`. Summary:

**The prototype's job is to answer one question, and it is not the question you asked.**

You framed it as: *"Can I sit in my real bedroom wearing the Quest 3 and see a convincing magical garden surrounding my real environment while retaining access to my computer?"*

The garden half of that question is **already answered by research** — Scene API, MRUK, LUT and Depth API are documented, shipping, and demonstrated in Meta's own samples. Building a garden to prove a garden can be built is wasted effort.

The half that is genuinely unknown is **"while retaining access to my computer."** So:

**Prototype Step 0 (no code, ~30 minutes):** Put the headset on at your desk, at night, with your normal lighting. Try to read your monitor through passthrough. Then open a Remote Display / Mixed Reality Link window, launch any third-party immersive app, and see whether the window survives and stays readable. **These two observations determine the architecture of your computer integration, and neither requires a line of code.**

**Prototype Step 1 (the actual build, ~1 week of evenings):** The smallest Unity app that proves spatial alignment: run Space Setup, load MRUK, draw a wireframe over every detected plane and volume, apply one nighttime Color LUT, enable Depth API occlusion, place **one** glowing flower on the floor and **one** vine segment on a wall — both anchored and persisted across a restart.

Success criteria: the wireframe sits on your real walls; the LUT makes your room feel like night; the flower is still in the same physical spot tomorrow; you can walk to your bed without hesitating.

**What the prototype must NOT contain:** procedural generation, multiple presets, audio reactivity, particles beyond a token few, hand interaction, the PC companion, or any authored art beyond two placeholder objects.

---

## 9. Risk Assessment

| # | Risk | Level | Mitigation |
|---|---|---|---|
| 1 | ~~**Computer stays unusable inside the app.**~~ **RESOLVED 2026-08-09.** Mixed Reality Link confirmed running simultaneously with Beat Saber (a third-party Unity immersive app), text "perfectly readable and 1 to 1." | ~~CRITICAL~~ → **LOW** | Route A adopted. Route C shelved. Residual risk is only that Meta changes Seamless Multitasking behavior in a future update — mitigated by the fact that nothing else in the architecture depends on it. |
| 2 | ~~**Nighttime passthrough is too noisy to look magical.**~~ **RESOLVED 2026-08-09.** Ari has controllable LED lighting available at night. | ~~HIGH~~ → **LOW** | Compare passthrough under warm-white vs. saturated color; prefer warm-white in the room and do the purple in the LUT. Optionally drive the LEDs from the PC companion service to sync real room lighting with garden presets. |
| 3 | **Performance collapse from transparent overdraw.** Fog + glow + particles + layered foliage is precisely the workload mobile GPUs handle worst, on top of a 20–40% passthrough tax. | **HIGH** | Establish a GPU budget in Phase 1 and profile every phase against it with OVR Metrics. Target 72Hz. Instancing mandatory. Treat "one more particle system" as a budget decision. |
| 4 | **Anchor drift over long sessions** makes vines slide off walls after two hours. | **MEDIUM** | Test explicitly (Test #4). Mitigate by re-localizing on room re-entry and by designing the art so small drift reads as organic rather than broken — avoid hard-edged geometry flush against real surfaces. |
| 5 | **Scene labels don't map to your furniture.** No DESK/DRESSER/CHAIR/MONITOR. Your desk may not label cleanly as TABLE. | **MEDIUM** | Run Space Setup early and inspect what you actually get. Build a small user-facing "assign role to anchor" step so *you* tell the app which TABLE is the desk — turning a limitation into a one-time setup ritual. |
| 6 | **Depth occlusion looks bad on thin vines.** Low-res noisy depth at edges. | **MEDIUM** | Test with real vine geometry early. Mitigate by keeping foliage thick/clustered rather than thin/wiry, and by using soft occlusion where the GPU allows. |
| 7 | **Seamless Multitasking behavior changes.** It only recently left experimental status; Meta could alter it. | **MEDIUM** | Do not make it the *only* path. Keep Route C viable as an escape hatch. |
| 8 | **Comfort failure — the system is beautiful and you never use it.** Headset weight, heat, and late-night eye strain. | **MEDIUM** | Counterweighted strap. Global dimming control. Design for 30–90 minute sessions, not all night. Ship an auto-fade after N minutes of stillness. |
| 9 | **Scope explosion.** Eight modules, five presets, and audio reactivity before the first vine is anchored. | **MEDIUM** | The phase gates in `ROADMAP.md` exist for this. Each phase has an exit criterion; do not start the next until it is met. |
| 10 | Unity/Meta SDK version incompatibility burning a weekend. | **LOW** | Pin a known-good Unity 6 + Meta XR SDK pair at project start. Do not chase updates mid-phase. |
| 11 | Art production capacity — stylized foliage is a lot of asset work for one person. | **LOW** | Buy or adapt a stylized foliage pack; spend your effort on lighting, color, and motion, which is where the atmosphere actually comes from. |

---

## 10. References

### Meta official documentation

- [Scene Overview (Unity)](https://developers.meta.com/horizon/documentation/unity/unity-scene-overview/)
- [Supported Semantic Labels](https://developers.meta.com/horizon/documentation/unreal/unreal-scene-supported-semantic-labels/)
- [Mixed Reality Utility Kit — Overview](https://developers.meta.com/horizon/documentation/unity/unity-mr-utility-kit-overview/)
- [MRUK — Manage and query scene data](https://latest.developers.meta.com/horizon/documentation/unity/unity-mr-utility-kit-manage-scene-data/)
- [MRUK — Getting started](https://developers.meta.com/horizon/documentation/unity/unity-mr-utility-kit-gs/)
- [Virtual Home sample (MRUK / AnchorPrefabSpawner)](https://developers.meta.com/horizon/documentation/unity/unity-sample-mruk-virtual-home/)
- [Depth API Overview (Unity)](https://developers.meta.com/horizon/documentation/unity/unity-depthapi-overview/)
- [Passthrough Occlusions in Unity](https://developers.meta.com/horizon/documentation/unity/unity-customize-passthrough-passthrough-occlusions/)
- [Passthrough Color Mapping Techniques](https://developers.meta.com/horizon/documentation/unity/unity-customize-passthrough-color-mapping/)
- [Passthrough Color LUT Tutorial](https://developers.meta.com/horizon/documentation/unity/unity-passthrough-tutorial-passthrough-color-lut/)
- [Creating Passthrough Color LUTs](https://developers.meta.com/horizon/documentation/unity/unity-passthrough-creating-color-luts/)
- [Passthrough Camera API Overview (Unity)](https://developers.meta.com/horizon/documentation/unity/unity-pca-overview/)
- [Passthrough Camera API Samples](https://developers.meta.com/horizon/documentation/android-apps/passthrough-camera-samples/)
- [Passthrough over Link](https://developers.meta.com/horizon/documentation/native/android/mobile-passthrough-over-link/)
- [Spatial Anchors Overview](https://developers.meta.com/horizon/documentation/unity/unity-spatial-anchors-overview/)
- [Spatial Data Permission](https://developers.meta.com/horizon/documentation/unity/unity-spatial-data-perm/)
- [High-Fidelity Room — ARCHIVED](https://developers.meta.com/horizon/documentation/unity/unity-scene-roommesh/)
- [Testing and performance analysis](https://developers.meta.com/horizon/documentation/unity/unity-perf/)
- [Draw Call Cost Analysis for Meta Quest](https://developers.meta.com/horizon/documentation/unity/po-draw-call-analysis/)
- [Meta XR SDKs for Unity](https://developers.meta.com/horizon/documentation/unity/unity-sdks-overview/)
- [Unreal — Depth API Overview](https://developers.meta.com/horizon/documentation/unreal/unreal-depthapi-overview/)
- [Unreal compatibility matrix](https://developers.meta.com/horizon/documentation/unreal/unreal-compatibility-matrix/)
- [Meta Spatial SDK — MRUK](https://developers.meta.com/horizon/documentation/spatial-sdk/spatial-sdk-mruk/)
- [Scene understanding — design guidance](https://developers.meta.com/horizon/design/mr-design-scene/)
- [Horizon OS features overview](https://developers.meta.com/horizon/documentation/android-apps/features-overview/)
- [Meta Horizon OS v81 update blog (Mixed Reality Link)](https://www.meta.com/blog/horizon-os-v81-update-mixed-reality-link-store-discoverability/)
- [Meta Quest release notes](https://www.meta.com/en-gb/help/quest/172903867975450/)

### Virtual Desktop / PCVR passthrough

- [Passthrough in Virtual Desktop — Unreal forums (no application-controlled passthrough)](https://forums.unrealengine.com/t/passthrough-in-virtual-desktop/2710753)
- [PassthroughForge (chroma-key pipeline; native extensions on roadmap)](https://www.passthroughforge.com/)
- [VirtualDesktop-OpenXR (VDXR) wiki](https://github.com/mbucchia/VirtualDesktop-OpenXR/wiki)
- [Virtual Desktop v1.30.1 release notes](https://github.com/guygodin/VirtualDesktop/releases/tag/v1.30.1)
- [VDXR bypasses SteamVR — UploadVR](https://www.uploadvr.com/virtual-desktops-vdxr-runtime/)
- [ue-openxr-passthrough (XR_FB_passthrough over Link, UE5)](https://github.com/AgileLens/ue-openxr-passthrough)

### Multitasking / desktop integration

- [Seamless Multitasking on Quest — UploadVR](https://www.uploadvr.com/seamless-multitasking-experimental-quest/)
- [Navigator UI rollout — UploadVR](https://www.uploadvr.com/meta-horizon-os-navigator-ui-finally-rolled-out-to-all-quest-headsets/)
- [Mixed Reality Link GA — TechSpot](https://www.techspot.com/news/110087-windows-remote-desktop-goes-immersive-meta-quest-3.html)

### Perceptual / performance sources

- [The perceptual gap between video see-through displays and natural human vision (arXiv, 2026) — Quest 3 ~18 PPD central](https://arxiv.org/pdf/2601.02805)
- [Unity DepthAPI samples (GitHub)](https://github.com/oculus-samples/Unity-DepthAPI)
- [Unity PassthroughCameraApiSamples (GitHub)](https://github.com/oculus-samples/Unity-PassthroughCameraApiSamples)
- [Quest Passthrough Camera API out now — UploadVR](https://www.uploadvr.com/quest-passthrough-camera-api-experimental-out-now/)
- [Meta releases Quest camera access — Road to VR](https://roadtovr.com/meta-releases-quest-camera-access-for-developers-promising-even-more-immersive-mixed-reality-games/)
