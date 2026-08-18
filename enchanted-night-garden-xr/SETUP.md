# Setup — everything you need installed

Machine audit run 2026-08-09. Install in the order listed; later items depend on earlier ones.

---

## ⚠️ Read this first — do NOT put the Unity project in OneDrive

Your working directory is `C:\Users\aware\OneDrive\Desktop\wrproj`. **A Unity project must not live inside a OneDrive-synced folder.**

Unity's `Library/` folder is a multi-gigabyte cache that it rewrites constantly while the editor is open. OneDrive will try to sync every one of those writes, which produces file-lock conflicts, corrupted imports, `.tmp` collisions, and editor crashes that look like Unity bugs but aren't. This bites people regularly and the symptoms are confusing.

**Put the Unity project here instead:**

```
C:\Dev\EnchantedNightGarden
```

The docs (`RESEARCH.md`, `ARCHITECTURE.md`, etc.) can happily stay in OneDrive — they're small text files. Only the Unity project needs to move out. We'll use git to connect the two if you want them versioned together.

---

## Tier 1 — required before Phase 1 can start

### 1. Unity Hub
- **Where:** <https://unity.com/download>
- **Size:** ~150 MB
- **Why:** manages editor versions and licenses. You never install the editor directly.

### 2. Unity ID (free)
- **Where:** created during Hub sign-in
- **License:** Personal — free. Sign in inside Hub before installing an editor or the editor will refuse to open.

### 3. Unity Editor **6.0 LTS** (`6000.0.81f1`)
- **Where:** installed *through* Unity Hub, not downloaded separately
- **Size:** ~10–13 GB with the Android modules below
- **Modules to tick during install — all three are required:**
  - ✅ **Android Build Support**
  - ✅ **OpenJDK**
  - ✅ **Android SDK & NDK Tools**
- **Version choice matters — worked out the hard way 2026-08-09.** Meta XR All-in-One SDK is **v205.0** (July 2026) with a stated minimum of **`6000.0.66f2`**. A minimum expressed as a `6000.0.x` patch means Meta actively tests the 6000.0 line. *Newer is not safer here*:

  | Version | Verdict |
  |---|---|
  | ✅ **Unity 6.0 LTS `6000.0.81f1`** | **Use this.** LTS, above the SDK floor, in the tested line, no reported issues. |
  | 🟡 Unity 6.3 LTS `6000.3.21f1` | LTS and above the floor, but a Meta XR Core license/package error was reported. Unverified whether fixed (Meta forum returns 403). **Fallback only.** |
  | ❌ Unity 6.4 (6000.4.x) | Reported `com.oculus.Integration` namespace conflict. |
  | ❌ Unity 6.5 (6000.5.x) | Confirmed build failure: `CS0619 GetInstanceID/EntityId`. Ari installed 6000.5.7f1 first and had to replace it. |
  | ⚠️ Unity 6.1 / 6.2 | **Not LTS lines** — tech-stream releases, no longer listed in Hub's Official releases. Earlier drafts of this doc wrongly called 6.1 an LTS. |
- **Pin it.** Once Phase 1 builds, do not upgrade the editor mid-phase.
- **Modules are per-editor-install.** If a platform tab is missing from `XR Plug-in Management`, the module isn't installed — add it via `Hub → Installs → ⚙ → Add modules`. A monitor icon is Standalone; a globe is WebGL; Android has its own icon and only appears once Android Build Support is present.

### 4. Meta developer account + organization
- **Where:** <https://developers.meta.com/horizon/>
- **Cost:** free
- **Why:** you cannot enable Developer Mode on the headset without belonging to a developer organization. Create one (it can be a solo org with any name).

### 5. Meta Horizon app on your phone
- **Where:** iOS App Store / Google Play
- **Why:** Developer Mode is toggled from the *phone* app, not the headset. `Devices → your Quest 3 → Headset Settings → Developer Mode → On`. Reboot the headset after.
- You may already have this from initial headset setup.

### 6. Meta Quest Developer Hub (MQDH)
- **Where:** <https://developers.meta.com/horizon/documentation/unity/ts-odh/>
- **Size:** ~500 MB
- **Why:** one-click deploy of builds to the headset, device logcat, performance capture, file transfer. This is how you'll get the prototype onto the Quest.
- Bundles its own `adb` — you don't need Android Studio.

### 7. USB-C data cable
- **Not just a charging cable.** Needs actual data lines. If your Quest 3's original cable is around, that works.
- Used for first-time deploys and for Passthrough over Link. Wireless deploy via MQDH works after initial pairing.

### 8. Packages installed *inside* Unity (no separate download)
Added via Package Manager / Asset Store once the project exists:
- **Meta XR Core SDK** (v83+) — passthrough, Depth API, spatial anchors
- **Meta MR Utility Kit / MRUK** (v83+) — room understanding
- **Unity OpenXR Plugin** — Meta now recommends this over the deprecated Oculus XR Plugin
- **URP** — comes with the "Universal 3D" project template; pick that template at project creation

---

## Tier 2 — strongly recommended, not blocking

### 9. Meta Horizon Link PC app
- **Where:** <https://www.meta.com/help/quest/pc-app/>
- **Why:** enables **Passthrough over Link** and **Spatial Data over Link**, which let you preview passthrough and your real room's scan data *inside the Unity Editor* without building and deploying every time. This roughly halves your iteration loop.
- After installing: `Settings → Beta` → enable **Developer Runtime Features**, **Passthrough over Meta Quest Link**, and **Spatial Data over Meta Quest Link**.
- Reminder from research: this is a **dev-only, wired-only** feature. It's a tool, not part of the shipped app.

### 10. VS Code C# extensions ✅ *VS Code already installed*
- Add the **C# Dev Kit** extension for IntelliSense against Unity's assemblies.
- Alternatively Visual Studio Community (heavier, better Unity debugging).

---

## Tier 3 — not needed until later phases

| Tool | Needed from | Why |
|---|---|---|
| **Blender** (free) | Phase 3 | Authoring stylized vines, lanterns, foliage. Not currently installed. |
| **Python 3** ✅ *already available as `py -3`* | Phase 6 | The PC companion service. |
| **OVR Metrics Tool** (sideloaded APK) | Phase 8 | On-device GPU/CPU profiling and thermal monitoring. |
| **RenderDoc** | Phase 8 | Frame-level GPU debugging, only if you hit a wall. |

---

## Already handled ✅

| Item | Status |
|---|---|
| **Mixed Reality Link** | Working — verified alongside Beat Saber |
| **Space Setup ("office")** | Scanned and trusted |
| **git** | 2.55.0 installed |
| **VS Code** | Installed |
| **Windows 11** | 10.0.26200 — meets Mixed Reality Link requirements |
| **RTX 4060 Ti** | Far exceeds anything this project asks of it |

---

## Disk space check

**~89 GB free on C:.** Enough, but not lavish:

| Item | Approx. |
|---|---|
| Unity Editor 6.1 + Android modules | 10–13 GB |
| MQDH | 0.5 GB |
| Project + `Library/` cache | 3–8 GB, grows over time |
| Blender (later) | 1 GB |
| **Total** | **~15–23 GB** |

Fine — just don't accumulate three Unity editor versions. Uninstall old ones from Hub as you go.

---

## Install order

```
1. Unity Hub          →  2. Sign in / Unity ID
3. Unity 6.1 LTS + Android modules  (longest download — start it early)
4. Meta developer account + org
5. Phone app → Developer Mode ON → reboot headset
6. MQDH → pair headset → confirm it appears
7. Create project at C:\Dev\EnchantedNightGarden (Universal 3D template)
8. Add Meta XR Core SDK + MRUK + OpenXR plugin
9. (Optional) Meta Horizon Link PC app + beta toggles
```

**Checkpoint before Phase 1 code:** build Unity's default empty scene to the headset via MQDH and see it run. If a grey empty scene deploys and launches, the entire toolchain is proven and everything after that is just code.

---

## Known gotchas

| Gotcha | Avoidance |
|---|---|
| Unity project inside OneDrive | Use `C:\Dev\` — see the warning at the top |
| Meta XR Core SDK 83.0 on Unity 6.3 | Use Unity **6.1 LTS** |
| Developer Mode missing from the phone app | You must create a developer **organization** first |
| Oculus XR Plugin vs OpenXR | Use **Unity OpenXR Plugin** — Meta's current recommendation |
| Depth API silently unavailable | Requires Unity 6+ **and** Meta XR Core SDK v74+. Both satisfied here. |
| Editor upgrade mid-project | Pin the version; don't chase updates during a phase |
