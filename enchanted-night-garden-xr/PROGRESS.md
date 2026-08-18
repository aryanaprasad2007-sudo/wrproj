# Progress log

## 2026-08-10 — project consolidation + first clean compile

### What happened

Two projects existed at once. Ari created `TrueEnchantedNightGarden` inside
OneDrive and imported the Meta XR SDK there; the unattended session had
separately built a scaffold at `C:\Dev\EnchantedNightGarden` with the LUTs and
scripts. Merged them, keeping Ari's (the SDK import is the account-gated,
expensive part) and moving it out of OneDrive.

`du -sh` on the OneDrive copy **timed out after two minutes** — a concrete
demonstration of why the project can't live there.

### Consolidation

- Stashed `Assets/Garden` from the scaffold, `.meta` files included so GUIDs survived
- Deleted `Library/` + `Logs/` from the source (regenerable; made the move instant)
- Moved `TrueEnchantedNightGarden` → `C:\Dev\EnchantedNightGarden`
- Merged the Garden assets in; renamed `Scripts~` → `Scripts`
- Deleted the scaffold and stale `.slnx`/`.csproj`

### First compile against the real SDK — 4 errors, all API drift, all fixed

Signatures read from the installed SDK source in `Library/PackageCache/`, not guessed:

| Was | Now | Why |
|---|---|---|
| `anchor.HasVolume` / `HasPlane` | `VolumeBounds.HasValue` / `PlaneRect.HasValue` | Deprecated |
| `anchor.VolumeBounds` (as `Bounds`) | `.Value` | Now `Bounds?` |
| `room.FloorAnchor` | `room.FloorAnchors[0]` | Deprecated — HiFi Scene allowed multiple floors |
| `GetClosestSurfacePosition(pos)` | `GetClosestSurfacePosition(pos, out Vector3)` | Returns distance, outputs position |
| `layer.ClearColorLut()` | `layer.DisableColorMap()` | No such method in SDK 205 |

**The volatile anchor API I was most worried about compiled clean** —
`SaveAnchorAsync`, `LoadUnboundAnchorsAsync`, `LocalizeAsync`, `BindTo`,
`EraseAnchorAsync` all correct as written.

### Verified state

```
C:\Dev\EnchantedNightGarden          (out of OneDrive)
  Unity 6000.0.81f1
  com.meta.xr.sdk.all  205.0.0
  com.unity.xr.openxr  1.16.1
  Assets/Garden/{Scripts, LUTs, Editor, Prefabs}
  → headless compile: 0 errors, 0 warnings, exit 0
  → LUT postprocessor applied to all 4 textures
```

**Canonical source for the scripts is `enchanted-night-garden-xr/unity-scripts/`;
the project holds copies.** Edit there and re-sync, so fixes aren't lost.

### Still to do (needs the editor open / headset present)

1. XR Plug-in Management → **Android tab** → OpenXR + Meta Quest feature group
2. `Meta → Tools → Project Setup Tool` → Fix All
3. Scene wiring per `PHASE1.md` steps 3–4
4. Two placeholder prefabs (emissive sphere, stretched cube)
5. Deploy via MQDH

---

## 2026-08-09 — unattended session (Ari away from machine)

### Done

**Unity project created and verified** — `C:\Dev\EnchantedNightGarden`

Built from the editor's own `com.unity.template.urp-blank` (which is what Hub
labels "Universal 3D"), so it is byte-identical to what you'd have got clicking
through Hub — including the URP `Mobile_RPAsset` / `Mobile_Renderer` assets that
matter for Quest.

- `ProjectVersion.txt` pinned to `6000.0.81f1`
- Two headless import passes run, both **exit code 0, zero compile errors**
- `Library/`, `.sln`, and `.csproj` generated — the project opens cold and clean
- Not in OneDrive ✅

**Four passthrough Color LUTs generated** — `Assets/Garden/LUTs/`

Written by `tools/make_luts.py`, pure standard library (this machine's Python
3.14 has no numpy or PIL, and the house rule is to vendor rather than install —
so the script includes its own zlib-based PNG encoder).

| File | Purpose |
|---|---|
| `lut_identity_32.png` | Correctness self-test — applies no change |
| `lut_midnight_32.png` | Phase 1 default. Cool blue moonlight |
| `lut_midnight_soft_32.png` | Half strength |
| `lut_moonflower_32.png` | Purple/magenta, Phase 7 range-finding |

Format is 1024×32 (R=32, 32 tiles of 32×32; X=red, Y=green, tiles=blue) per
Meta's spec. Both the identity and midnight strips were visually inspected and
are correct — identity shows the textbook RGB cube unroll, midnight is visibly
desaturated and cooled.

**LUT import settings automated** — `Assets/Garden/Editor/LutImportSettings.cs`

An `AssetPostprocessor` rather than hand-set inspector values, so it can't be
forgotten and survives re-imports. Verified in the generated `.meta`:
`sRGBTexture: 0`, mipmaps off, clamp, and an Android override with
`overridden: 1`, RGB24, `textureCompression: 0`.

This matters more than it sounds: a DXT/ASTC-compressed LUT produces visible
banding across the entire room, which reads as "my grade is bad" rather than
"my importer ate it."

**Six Phase 1 scripts staged** — `Assets/Garden/Scripts~/`

Parked behind a trailing `~` (Unity ignores such folders) because they reference
`Meta.XR.MRUtilityKit` and `OVR*` types that don't exist in the project yet.
Without the tilde the editor would open into a broken compile state.

### Blocked on you — cannot be automated

| Task | Why |
|---|---|
| Import **Meta XR All-in-One SDK** | Asset Store requires your account signed in *inside* the editor. No Asset Store cache exists on disk to work from. |
| Install **Unity OpenXR Plugin** | Trivial once the editor is open; version resolution is safer done by Package Manager than guessed by hand in `manifest.json`. |
| Rename `Scripts~` → `Scripts` | Must happen *after* the SDK import |
| Run `Meta → Tools → Project Setup Tool` | Interactive |
| Create placeholder flower/vine prefabs | Trivial in-editor, error-prone to hand-author as YAML |
| Deploy to headset | Needs the headset present |

### Deliberately not done

- **Did not hand-edit `manifest.json` to add Meta packages.** Meta XR isn't on a public Unity registry — a fabricated dependency line would fail resolution and block the project from opening at all.
- **Did not write `SafetyPolicy.HighlightCurve()`.** That's your design decision; the placeholder compiles and the three candidate approaches are documented in the comment block.
- **Did not author art.** Phase 1 is spheres and cubes by design.

### Next when you're back

1. Open `C:\Dev\EnchantedNightGarden` in Unity 6000.0.81f1 — expect a clean, empty URP scene
2. Import Meta XR All-in-One SDK from `Package Manager → My Assets`
3. Install Unity OpenXR Plugin; enable OpenXR + Meta Quest feature group on the **Android** tab
4. `Meta → Tools → Project Setup Tool` → Fix All
5. **Checkpoint:** build the empty scene to the headset via MQDH before adding anything
6. Rename `Assets/Garden/Scripts~` → `Scripts`
7. Wire the scene per `PHASE1.md` steps 3–4
8. Load `lut_identity_32` first and confirm passthrough looks normal — that validates flipY before you judge any grade
