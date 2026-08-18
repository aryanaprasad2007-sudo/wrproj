# Enchanted Night Garden XR — Architecture

**Status:** Design document. Nothing here is implemented. Phases 0–1 require only two of these modules.

Read `RESEARCH.md` first — this document assumes the conclusions reached there, in particular that the garden renders **on the Quest 3**, not on the PC.

---

## 1. The one-paragraph version

A standalone Unity application runs on the Quest 3 with passthrough as its base layer. On launch it reads the room from MRUK, maps Meta's generic semantic labels (`TABLE`, `STORAGE`, `SCREEN`…) onto *your* specific furniture through a small user-authored role assignment that persists via spatial anchors. A generator decorates the room from those roles — vines on wall planes, moss on the floor, a canopy on the ceiling, a lantern cluster over the desk — subject to veto by a safety module that owns the guarantee that you can always see where real objects are. An environment controller drives time, palette, weather and intensity, applying a passthrough Color LUT to tint the real room and adjusting particle and audio systems to match. A small Python service on the PC feeds it music analysis, computer-activity state, and time signals over your LAN; when the PC is off, the garden runs standalone in a static preset.

---

## 2. Module map

Your proposed decomposition was sound. Two corrections, explained in `RESEARCH.md` §3: **Room Understanding and Spatial Anchoring merge**, and **Safety becomes a real module with authority**.

```
┌────────────────────────────────────────────────────────────────────┐
│                         HORIZON OS (Quest 3)                       │
│   Passthrough compositor · Scene API · Depth API · Anchor store    │
└───────────────────────────────┬────────────────────────────────────┘
                                │
┌───────────────────────────────▼────────────────────────────────────┐
│  RoomModel                                          [Phase 1–2]    │
│  MRUK ingest · planes & volumes · anchors · persistence            │
│  Role assignment: TABLE#2 → "desk", STORAGE#1 → "dresser"          │
│  Exposes: surfaces, corners, roles, free-floor regions             │
└───────────────┬───────────────────────────────┬────────────────────┘
                │                               │
┌───────────────▼───────────────┐   ┌───────────▼────────────────────┐
│  SafetyPolicy      [Phase 1]  │   │  GardenGenerator    [Phase 3–4]│
│  ── HAS VETO ──               │◄──┤  Per-role decoration rules     │
│  Keep-clear volumes           │   │  Deterministic from a seed     │
│  Floor path protection        │   │  Emits placement requests      │
│  Max occlusion density        │   │  Owns the instancing budget    │
└───────────────────────────────┘   └───────────┬────────────────────┘
                                                │
┌───────────────────────────────────────────────▼────────────────────┐
│  EnvironmentController                              [Phase 3, 6]   │
│  Preset state · time of day · passthrough LUT + blend              │
│  Particle density · fog · palette · intensity                      │
└───────┬─────────────────┬────────────────────┬─────────────────────┘
        │                 │                    │
┌───────▼──────┐  ┌───────▼──────┐  ┌──────────▼─────────┐
│ AudioSystem  │  │ ScreenFrame  │  │ InteractionSystem  │
│  [Phase 6]   │  │  [Phase 5]   │  │     [Phase 7]      │
│ Spatial amb. │  │ Monitor zone │  │ Gaze/hands/ctrl    │
└──────────────┘  └──────────────┘  └────────────────────┘
        ▲
        │  WebSocket (LAN)
┌───────┴────────────────────────────────────────────────────────────┐
│  PC COMPANION SERVICE (Python, RTX 4060 Ti box)     [Phase 6]      │
│  Audio FFT · activity/idle state · clock & moon phase · presets    │
│  Optional (Phase 5c): desktop capture → NVENC → WebRTC             │
└────────────────────────────────────────────────────────────────────┘
```

---

## 3. Module contracts

### 3.1 `RoomModel` — knows the physical room

**Owns:** everything spatial. This is the only module that talks to MRUK or the anchor store.

**Responsibilities**
- Load the MRUK room at startup; handle the "no room scanned yet" case by directing you to Space Setup (your app cannot trigger it).
- Expose the room as usable primitives: `WallSurface[]`, `FloorRegion`, `CeilingPlane`, `FurnitureVolume[]`, `Corner[]`, and a free-floor query for walkable space.
- **Role assignment.** Meta's labels are generic and do not include DESK, DRESSER, CHAIR or MONITOR. `RoomModel` holds a persisted map from anchor UUID to *your* semantic role.
- Persist and restore that map via Spatial Anchors so setup happens once.
- Re-localize on session start and detect drift.

**The role assignment layer is the most important design decision in this document.** Without it, the generator has to guess which `TABLE` is your desk versus your nightstand, and it will guess wrong. With it, you spend ninety seconds once, pointing at things and picking a role from a list, and the system understands your bedroom forever. It converts an API limitation into a pleasant one-time ritual.

**Deliberately excluded:** any knowledge of plants, presets, or aesthetics. `RoomModel` describes a bedroom, not a garden.

### 3.2 `SafetyPolicy` — the module with veto power

**Owns:** the guarantee that you can always tell where real objects are.

Every placement request from `GardenGenerator` passes through here and can be rejected or attenuated. It is not advisory.

**Responsibilities**
- Maintain **keep-clear volumes**: the walking path between bed / desk / door, the bed edge, the desk edge, the doorway, and a configurable radius around anything labeled `OTHER` (unknown obstacles).
- Enforce a **maximum occlusion density** — a ceiling on how much of the passthrough view virtual geometry may cover, especially at floor level.
- Enforce **floor legibility**: moss and stones may tint the floor but must never obscure where it actually is, and must never create false depth cues near a real edge.
- Provide a global **panic fade** — one gesture or controller button drops all virtual content to near-zero opacity instantly. This should exist from Phase 1, before there is anything to fade.

**Design note:** it is far easier to build this in from the start than to retrofit it once the garden is pretty and you are reluctant to remove anything.

### 3.3 `GardenGenerator` — creates the fantasy environment

**Owns:** what goes where, given a room and a preset.

**Responsibilities**
- Map roles to decoration rules: wall → climbing vines; corner → larger plant or tree form; floor → moss patches and stones; ceiling → canopy gaps and sky; desk → lantern cluster and framing foliage; bed → soft glow perimeter and hanging vines; dresser → moss and mushroom shelf.
- Be **deterministic from a seed + room hash**, so your bedroom looks the same tomorrow. Persist the seed. A garden that re-randomizes nightly is disorienting, not magical.
- Own the **instancing budget**: emit batched, GPU-instanced placements, not individual GameObjects.
- Submit every placement to `SafetyPolicy` and honor rejections.

**Deliberately excluded until Phase 4+:** procedural growth animation, plant species variety, seasonal change. Phase 3 places static decorations from fixed rules. That is enough to know whether it feels right.

### 3.4 `EnvironmentController` — time, weather, lighting, atmosphere

**Owns:** global mood state.

**Responsibilities**
- Hold the active preset (Midnight / Rain / Moonflower / Astral / Spirit) as **data, not code** — a ScriptableObject per preset containing LUT reference, particle densities, fog parameters, palette, audio bed, and intensity curves.
- Apply the passthrough **Color LUT**, using LUT blending for smooth preset transitions rather than hard cuts.
- Drive time-of-day: moon position and phase from real clock, star field rotation.
- Expose a single global **intensity** value (0 = plain passthrough, 1 = full garden) that everything else scales against. This one value gives you the calm-down behavior, the panic fade, and the "settle when you stop working" reaction for free.

**Design note:** presets-as-data means adding "Rain Garden" later is authoring a ScriptableObject, not writing a subsystem.

### 3.5 `ScreenFrame` — computer integration

**Owns:** the relationship between the virtual garden and your working screen.

Its implementation depends entirely on which route from `RESEARCH.md` §5 survives testing:

- **Route A (OS window):** `ScreenFrame` never touches the screen itself. It reads the `SCREEN` anchor volume from `RoomModel` and instructs `GardenGenerator` to place a keep-clear region plus a decorative frame *around* where the OS window will float. Simple, and the OS composites the window above everything.
- **Route B (passthrough cutout):** `ScreenFrame` renders a hole in the garden aligned to the `SCREEN` volume.
- **Route C (custom stream):** `ScreenFrame` owns a video decode surface, becomes real geometry in the scene, and unlocks foliage *in front of* the screen and screen dimming tied to activity.

**Build the Route A version first regardless** — it is nearly free and its keep-clear logic is needed by every route.

### 3.6 `AudioSystem`

Spatialized ambience: wind, distant water, insects, occasional chimes. Per-preset audio beds crossfading with `EnvironmentController` transitions. Positional cues anchored to garden features rather than head-locked.

**Design note for nighttime use:** audio is where cozy actually lives, and it is far cheaper than pixels. Do not defer it as long as its Phase-6 slot implies if the atmosphere feels flat earlier.

### 3.7 `InteractionSystem`

Hands, controllers, gaze. Minimal by design: preset switching, global dimming, panic fade, and role-assignment during setup. This project is an *environment*, not a game — resist building a mechanic.

### 3.8 PC Companion Service

A single Python process on the PC exposing a WebSocket on the LAN. The Quest app is a client and **must run correctly when it cannot connect**.

Proposed message shape (JSON, ~10Hz for audio, event-driven for state):

```json
{ "t": 1754800000, "audio": { "bass": 0.42, "mid": 0.18, "high": 0.07, "beat": true },
  "activity": { "state": "typing", "idle_s": 0 },
  "clock": { "local": "23:41", "moon_phase": 0.62 },
  "command": null }
```

Why the PC and not the headset: the FFT, the foreground-window polling, and any future weather or calendar lookups are free on a machine that is already awake and already playing the music — and cost battery and frame time on one that is not.

---

## 4. Data flow at runtime

```
startup ──► RoomModel.Load()
              ├─ MRUK room found? ──no──► prompt: run Space Setup, exit
              ├─ roles assigned? ───no──► run role assignment flow (once)
              └─ yes ──► emit RoomDescription
                            │
            GardenGenerator.Generate(RoomDescription, preset, seed)
                            │
                    for each placement ──► SafetyPolicy.Evaluate()
                            │                    ├─ allow
                            │                    ├─ attenuate (reduce density/opacity)
                            │                    └─ reject
                            ▼
                    instanced draw batches

per frame ──► EnvironmentController.Tick()
                ├─ intensity ← preset × PC activity state × panic state
                ├─ passthrough LUT ← blend(presetA, presetB, t)
                ├─ particle density, fog, palette ← intensity
                └─ AudioSystem.SetBed(preset, intensity)

on PC message ──► EnvironmentController receives audio/activity/clock
on drift detect ──► RoomModel re-localizes, generator re-anchors (no re-randomize)
```

---

## 5. Persistence strategy

Three distinct things persist, and conflating them causes pain:

| What | Where | Lifetime |
|---|---|---|
| Room geometry | Horizon OS Space Setup | OS-owned; survives app reinstall |
| Role assignments (anchor UUID → "desk") | Spatial Anchors + local JSON | Yours; must survive app updates |
| Garden seed + preset choice | Local JSON | Yours; regenerating from the same seed reproduces the same garden |

**Do not persist placements.** Persist the *seed* and regenerate. Placements are large, brittle against room changes, and would need migration logic. A seed is 8 bytes and always reproduces.

---

## 6. Performance architecture

The budget is roughly 6–8ms of GPU per frame at 72Hz after passthrough's 20–40% tax. Architectural implications, decided now rather than discovered later:

- **All foliage is GPU-instanced**, batched by material. `GardenGenerator` emits batches, never individual renderers.
- **All lighting is baked or faked.** Emissive materials plus light probes. No real-time lights.
- **Transparent overdraw is the budget**, not triangles. Fog, glow, particles, and foliage cards all cost fill rate. Every preset carries an overdraw budget and `EnvironmentController` scales particle density to stay inside it.
- **Fireflies are one shader-driven particle system**, never `TrailRenderer` (per-instance draw call, CPU rebuild every frame).
- **Depth API occlusion** is enabled globally; hard vs soft mode is a settings toggle, since soft costs measurably more.
- **Foveated rendering** on, at a level tuned during Phase 8.

---

## 7. What this architecture deliberately does not do

Recording these prevents rediscovering them as ideas later:

- **No PC rendering of the garden.** Ruled out in `RESEARCH.md` §2.
- **No custom passthrough shading.** No API exists. LUT only.
- **No automatic furniture recognition.** Space Setup labels are user-defined; the Passthrough Camera API could theoretically run an object detector, but that is a research project, not a feature — and you would be building it to replace a ninety-second manual step.
- **No real lighting of physical objects.** A virtual moon cannot light your real bedspread.
- **No multi-room support.** One bedroom. The OS supports up to 15 rooms; you need one.
- **No multiplayer / shared anchors.** Nothing in your vision requires it.

---

## 8. A design decision I want from you

One choice in `SafetyPolicy` genuinely shapes how the whole thing feels, and it is yours to make rather than mine to assume. It is a trade-off between immersion and physical certainty, and reasonable people land in different places.

**The question: how should the garden behave around real obstacles you might walk into?**

Three defensible policies:

- **Hard keep-clear.** Virtual geometry is simply never placed within a radius of the bed edge, desk edge, and door. Maximum safety, but the garden gets visibly "bald" exactly around the furniture you most wanted enchanted.
- **Highlight-instead-of-hide.** Obstacles get *more* decoration, not less — glowing moss along the bed edge, luminous mushrooms at the desk corner — so real edges become the brightest, most legible things in the room. Immersive and arguably safer than bare passthrough, but it requires the glow to read as "edge here" rather than as decoration.
- **Proximity fade.** Full decoration everywhere, but virtual geometry fades out within ~50cm of your head, revealing plain passthrough as you approach anything. Best of both in theory; risks a constantly-flickering world if you work at a desk with your head near things.

My inclination is **highlight-instead-of-hide as the default, with proximity fade layered on top for anything unlabeled** — but you are the one who will be walking around this room half-asleep at 2am, and you know your bedroom's geometry and your own night-time clumsiness better than I do. When you pick, I will write it into `SafetyPolicy`'s contract before Phase 1 begins.
