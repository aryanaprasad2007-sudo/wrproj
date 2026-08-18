# Phase 1 — build and wiring guide

Six scripts are in `unity-scripts/`. This is how to get them running on the headset.

---

## Step 1 — Create the project

**In Unity Hub → New Project → Universal 3D → name `EnchantedNightGarden`.**

**Location: `C:\Dev\` — not OneDrive.** See the warning in `SETUP.md`; Unity's `Library/` cache and OneDrive sync actively fight each other.

---

## Step 2 — Install the packages

**Meta XR Core SDK + MR Utility Kit** — the simplest route is the Unity Asset Store:

1. Open <https://assetstore.unity.com/packages/tools/integration/meta-xr-all-in-one-sdk-269657> in a browser, add to your Unity account (free)
2. In Unity: `Window → Package Manager → My Assets` → find **Meta XR All-in-One SDK** → Download → Import

Or, if you prefer the leaner install, add just what Phase 1 needs via `Package Manager → + → Add package by name`:

```
com.meta.xr.sdk.core
com.meta.xr.mrutilitykit
```

**Unity OpenXR Plugin:** `Package Manager → Unity Registry → OpenXR Plugin → Install`

Then `Edit → Project Settings → XR Plug-in Management → Android tab`:
- ✅ **OpenXR**
- Under `OpenXR → Android`, enable: **Meta XR**, **Meta XR Foveation**, **Meta XR Subsampled Layout**

Finally run `Meta → Tools → Project Setup Tool` and apply every recommended fix. It catches a dozen Android/XR settings you'd otherwise hit one at a time as runtime errors.

---

## Step 3 — Scene setup

New scene. Then:

1. **Delete the default Main Camera.** MRUK requires `OVRCameraRig` instead — leaving both causes two cameras fighting over the same eye.
2. Add **`OVRCameraRig`** prefab (search the Meta XR package).
3. Add the **`MRUK`** prefab.
4. On the MRUK component, set scene loading to **load from device**.
5. On `OVRCameraRig → OVRManager`:
   - **Passthrough Support** → *Supported*
   - **Enable Passthrough** → ✅
   - **Scene Support** → *Required* (this drives the runtime spatial-data permission prompt)
   - **Anchor Support** → *Enabled*
6. Add an **`OVRPassthroughLayer`** component (on `OVRCameraRig` is fine):
   - **Placement** → *Underlay*
7. Add **`EnvironmentDepthManager`** anywhere in the scene (Meta XR Core SDK → `Scripts/EnvironmentDepth`). This is Depth API occlusion — it needs no configuration to start.

---

## Step 4 — Wire the scripts

Copy `unity-scripts/*.cs` into `Assets/Scripts/`. Then create an empty GameObject called **`Garden`** and add:

| Component | Goes on | Inspector fields to set |
|---|---|---|
| `GardenBootstrap` | `Garden` | Drag in the other five |
| `RoomWireframe` | `Garden` | `Line Material` → any unlit material |
| `SafetyPolicy` | `Garden` | defaults are fine |
| `AnchorPlanter` | `Garden` | `Flower Prefab`, `Vine Prefab` (see below) |
| `DebugOverlay` | `Garden` | `Text` → a child TextMesh |
| `NightAtmosphere` | **`OVRCameraRig`** (same object as `OVRPassthroughLayer`) | `Night Lut` → see Step 5 |

**Placeholder prefabs — deliberately crude, this is Phase 1:**
- **Flower:** a sphere scaled to 0.08, unlit material, emissive pale-blue
- **Vine:** a cube scaled to `(0.03, 0.6, 0.03)`, emissive green

Do not author real art yet. If you find yourself in Blender this week, the prototype has drifted.

---

## Step 5 — The night LUT

`NightAtmosphere` needs a `Texture2D` LUT. Fastest path:

1. Grab a neutral 32×32×32 identity LUT strip (a 1024×32 PNG), or export one from any colour-grading tool
2. Grade it toward deep blue/purple — lift shadows slightly blue, pull warmth out of highlights, drop overall saturation a little
3. Import into Unity with **Compression: None**, **sRGB: off**, **Generate Mip Maps: off** — a compressed LUT produces visible banding
4. Assign to `NightAtmosphere → Night Lut`

**Start subtle.** A LUT that looks perfect on a monitor is usually far too strong in the headset. That's what the `Lut Weight` slider and the A-button toggle are for.

---

## Step 6 — Build and deploy

`File → Build Settings → Android → Switch Platform`, then deploy through **MQDH** (easier than Unity's build-and-run — better logs).

First run will prompt on-headset for **spatial data permission**. Accept it, or MRUK returns an empty room and `GardenBootstrap` logs the 15-second timeout.

---

## Controls

| Button | Action |
|---|---|
| **A** | Toggle the night LUT on/off — your A/B test |
| **B** (hold) | **Panic fade** — everything virtual drops out |
| **X** | Plant the flower + vine at your current position |
| **Y** | Erase both anchors |
| **Left thumbstick click** | Cycle overlay: compact → full label dump → hidden |

---

## What to check on night one

1. Wireframe sits on your real walls
2. Label dump (thumbstick click twice) — **write down what your desk, dresser, monitor and bed are called**. That's Test #3.
3. LUT on vs. off — does it read as moonlit or just dark?
4. Frame time with and without the Mixed Reality Link window open — that's Test #2b
5. Wave a hand in front of the vine — does Depth occlusion cut it correctly?
6. Press X to plant. Note where the flower is.

## What to check on night two

**This is the real test.** Fresh launch, after the headset has slept:

- Is the flower in the same physical spot?
- What does `drift` read after 30 minutes?
- Does the wireframe still hug your walls?

---

## If something breaks

| Symptom | Cause |
|---|---|
| "No MRUK instance in scene" | MRUK prefab missing |
| "MRUK loaded no room within 15s" | Spatial data permission denied, or you're not in the scanned `office` space |
| Everything black, no passthrough | `OVRPassthroughLayer` placement isn't *Underlay*, or Passthrough Support isn't *Supported* |
| Anchors never restore | Normal on first run. If it persists, check the log for the `LocalizeAsync` warning — usually means the headset hasn't recognised the room yet |
| Compile errors on `MRUKAnchor.Label` or `SaveAnchorAsync` | SDK version differences. These are the two most version-volatile APIs; tell me the error and it's a one-line fix |

---

## One thing waiting on you

`SafetyPolicy.cs` has a `HighlightCurve()` function with a placeholder in it and three candidate approaches written out above it. That function defines how highlight-instead-of-hide actually *feels* in a dark room. It's about five lines. Details in the comment block — worth writing yourself rather than taking my guess.
