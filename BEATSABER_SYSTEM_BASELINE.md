# Beat Saber System Baseline

Date: 2026-08-18

## Scope

This baseline records what I could verify locally without changing anything on disk. Anything I could not confirm is marked `UNKNOWN`.

## Hardware

| Item | Status | Notes |
| --- | --- | --- |
| CPU | Known | Intel Core Ultra 7 265K @ 3.90 GHz |
| GPU | Known | NVIDIA GeForce RTX 4060, 8 GB VRAM |
| RAM | Known | 32.0 GB installed, 31.7 GB usable |
| Motherboard | UNKNOWN | Not yet readable from available local checks. |
| Windows version | Known | Windows 11 Home, version 25H2, OS build 26200.9168 |
| Monitor refresh rate | UNKNOWN | Not yet detected. |
| Available storage | Known | 813 GB of 932 GB used |

## VR Environment

| Item | Status | Notes |
| --- | --- | --- |
| SteamVR | PRESENT | `C:\Program Files (x86)\Steam\steamapps\common\SteamVR` exists. |
| Virtual Desktop Streamer | PRESENT | `C:\Program Files\Virtual Desktop Streamer` exists. |
| Meta / Oculus PC software | UNKNOWN | No installation path verified yet. |
| OpenXR runtime | Known | Meta Horizon Oculus runtime: `C:\Program Files\Meta Horizon\Support\oculus-runtime\oculus_openxr_64.json` |
| Current connection method | UNKNOWN | Need headset/runtime inspection to confirm Link, Air Link, Virtual Desktop, or other. |
| Headset model | UNKNOWN | Not yet detected. |
| Headset refresh-rate capabilities | UNKNOWN | Not yet detected. |

## Beat Saber Install

| Item | Status | Notes |
| --- | --- | --- |
| PC store | Steam | `C:\Program Files (x86)\Steam\steamapps\common\Beat Saber` exists. |
| App ID | 620980 | From `appmanifest_620980.acf`. |
| Install path | Known | `C:\Program Files (x86)\Steam\steamapps\common\Beat Saber` |
| Installed size | 1,680,785,534 bytes | From Steam manifest. |
| Steam buildid | 24107063 | From Steam manifest. |
| Game version | 6000.0.40f1 | From `Beat Saber.exe` file metadata. |
| Standalone install | UNKNOWN | No standalone installation detected yet. |
| Existing mod loader | Present | BSIPA is installed in `IPA/`. |
| Existing mods | Present | BeatLeader, HitScoreVisualizer, EasyOffset, Counters+, JDFixer, BetterSongSearch, BetterSongList, Camera2, PlaylistManager, PracticePlugin, SongPlayHistory, SongRankedBadge, SongDetailsCache. |
| Custom songs | PRESENT | Built-in and custom level folders exist in the install tree. |
| BeatLeader config | UNKNOWN | No local config found yet. |
| Controller config | UNKNOWN | Not yet located. |

## Important Findings

- The Beat Saber install is now modded for competitive analysis, but I kept the standalone install untouched.
- SteamVR and Virtual Desktop Streamer are both installed, so there are at least two viable PCVR pipelines to benchmark later.
- The game executable reports `6000.0.40f1`, which is the most concrete local version marker I found.
- The PC is a strong Beat Saber box on paper: Ultra 7 265K, RTX 4060, and 32 GB RAM should be enough for a competitive PCVR baseline as long as the runtime path stays efficient.
- The active OpenXR runtime is the Meta Horizon Oculus runtime.

## What I Did Not Change

- No Beat Saber files were modified.
- No mods were installed.
- No VR runtime settings were changed.
- No standalone installation was touched.

## Still Needed

1. CPU / GPU / RAM / motherboard details.
2. Monitor refresh rate and available storage.
3. Headset model and current OpenXR runtime.
4. Oculus / Meta software detection.
5. SteamVR and Virtual Desktop launch-path comparison.
6. Local Beat Saber user config discovery under `AppData`.
