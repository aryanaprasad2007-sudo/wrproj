# Beat Saber Mod Research

Date: 2026-08-18

This is an initial compatibility and relevance pass using official repositories and BeatMods. I have not installed anything yet.

## Notes

- BeatLeader’s official PC mod repo says to download the release matching the game version and install the required dependencies.
- BeatMods currently lists Beat Saber versions through `1.44.1`, which makes it the first place to verify compatibility for the current PC mod ecosystem.
- For the exact installed game version on this machine, the local executable reports `6000.0.40f1`, so compatibility should be checked against the matching Beat Saber release line before installing anything.

## Core Candidates

| Mod | Current Version | Beat Saber Compatibility | Purpose | Priority | Performance Risk | Install? |
| --- | --- | --- | --- | --- | --- | --- |
| BeatLeader | `v0.10.0` | Official repo release notes say `Beat Saber 1.42` for the latest release I found; must verify the exact release for this machine’s game build before install. | Leaderboards, replay recording, score submission, analysis. | Essential | Low to moderate | Yes, if a matching build exists. |
| HitScoreVisualizer | `3.7.3` | Latest release found says `BS 1.42.0`; installed as a current build on this machine. | Cut-score and swing feedback. | High | Low | Installed. |
| EasyOffset | `v2.1.15` | GitHub release notes show support for `1.42.0`; older releases explicitly map to older Beat Saber versions. | Controller geometry tuning and benchmarking. | Essential | Low | Yes, if compatible with the installed build. |
| Counters+ | `2.3.11` | GitHub shows a latest release dated Jan 3, 2025; exact Beat Saber support still needs confirmation on the matching release / BeatMods entry. | HUD counters for accuracy, misses, and swing stats. | High | Low | Maybe. |
| SliceDetails | `1.1.1` | BeatSaber mod list entry found via GitHub mirror; current PC compatibility still needs confirmation from the source repo or BeatMods. | Individual cut analysis. | High | Low | Maybe. |
| PracticePlugin | `9.1.0` | Latest release found says `bs1.40.4`; installed. | Controlled practice and repeatable experiments. | High | Low | Installed. |
| JDFixer | `7.4.0` | Official repo states `BS 1.40.0+`. | Jump distance / reaction time experimentation. | High | Low | Maybe, depending on whether visual tuning is needed. |
| PPPredictor | UNKNOWN | Needs current official compatibility check. | Estimate PP gain from better scores. | Medium | Low | Not installed. |
| SongPlayHistory | `2.3.0` | Latest release found says `bs1.41.1`; installed. | Track practice history. | Medium | Low | Installed. |

## Secondary Candidates

| Mod | Current Version | Beat Saber Compatibility | Purpose | Priority | Performance Risk | Install? |
| --- | --- | --- | --- | --- | --- | --- |
| BetterSongSearch | `0.8.2` | Latest release found says `1.42.0+ / 1.39.1+`; installed. | Better map search. | Medium | Low | Installed. |
| PlaylistManager | `1.6.6` | Latest release found; installed, but it is an older build and should be treated as a legacy utility. | Playlist organization. | Medium | Low | Installed. |
| MorePrecisePlayerHeight | UNKNOWN | Needs verification. | Player-height tuning. | Low to medium | Low | Not installed. |
| SongRankedBadge | `1.0.6` | Latest release found says `BS 1.40.0`; installed. | Ranked-map badges. | Low | Low | Installed. |
| TakeMeToResults | UNKNOWN | Needs verification. | Faster post-song flow. | Low | Low | Not installed. |
| Camera2 | `0.6.119` | Latest release found says `BS 1.42.0+`; installed. | Analysis / recording camera. | Medium | Medium | Installed. |

## Conditional Candidates

| Mod | Current Version | Beat Saber Compatibility | Purpose | Priority | Performance Risk | Install? |
| --- | --- | --- | --- | --- | --- | --- |
| GottaGoFast | UNKNOWN | Needs verification. | Performance / speed tweaks. | Low | Medium | Only if a measurable need appears. |
| PrioritySetter | UNKNOWN | Needs verification. | Process priority management. | Low | Medium | Only if benchmarked benefit appears. |
| BeatSaberPlus | UNKNOWN | Needs verification. | Feature bundle / UI extras. | Low | Medium | Avoid unless a specific feature is required. |
| Chroma | UNKNOWN | Needs verification. | Lighting/effect support. | Low | Medium | Only for maps that require it. |
| NoodleExtensions | UNKNOWN | Needs verification. | Advanced mapping support. | Low | Medium | Only when required by maps you actually play. |
| Heck | UNKNOWN | Needs verification. | Map / environment features. | Low | Medium | Only if a map needs it. |
| Vivify | UNKNOWN | Needs verification. | Visual effects support. | Low | Medium | Only if required. |
| MappingExtensions | UNKNOWN | Needs verification. | Mapping dependencies. | Low | Medium | Only when a map or mod depends on it. |

## Relevance Filter

Prioritize the following for competitive play:

1. BeatLeader
2. EasyOffset
3. HitScoreVisualizer
4. Counters+
5. SliceDetails
6. PracticePlugin
7. JDFixer
8. PPPredictor
9. SongPlayHistory

## Sources

- [BeatLeader PC mod repository](https://github.com/BeatLeader/beatleader-mod)
- [BeatLeader organization](https://github.com/BeatLeader)
- [BeatMods mod listing](https://beatmods.com/mods)
- [EasyOffset repository](https://github.com/Reezonate/EasyOffset)
- [Counters+ repository](https://github.com/NuggoDEV/CountersPlus)
- [JDFixer repository](https://github.com/zeph-yr/JDFixer)
- [JDFixer releases](https://github.com/zeph-yr/JDFixer/releases)
- [SliceDetails entry in a Beat Saber mod list mirror](https://github.com/ComputerElite/BM/blob/main/mods.json)
- [BetterSongSearch repository](https://github.com/kinsi55/BeatSaber_BetterSongSearch)
- [BetterSongList repository](https://github.com/kinsi55/BeatSaber_BetterSongList)
- [Camera2 repository](https://github.com/kinsi55/CS_BeatSaber_Camera2)
- [PlaylistManager repository](https://github.com/rithik-b/PlaylistManager)
- [PracticePlugin repository](https://github.com/denpadokei/PracticePlugin)
- [SongPlayHistory repository](https://github.com/qe201020335/SongPlayHistory)
- [SongRankedBadge repository](https://github.com/qe201020335/SongRankedBadge)
- [HitScoreVisualizer repository](https://github.com/ErisApps/HitScoreVisualizer)

## Caution

The compatibility entries here are provisional. Before installing any mod, I still need to verify:

- the exact Beat Saber release line that matches the local executable
- the exact compatible release for each mod
- whether BeatMods or the official repo release is the safest source for that version
