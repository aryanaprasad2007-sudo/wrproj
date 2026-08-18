"""
NightOwl anime tracker.

Pulls the current season and upcoming episode times from AniList's public
GraphQL API (no key, no account), caches them locally, and keeps a small
watchlist with per-show episode progress.

    python anime_sync.py              refresh the season cache
    python anime_sync.py --track 1234 add a show to the queue
    python anime_sync.py --watch 1234 mark one more episode watched
    python anime_sync.py --unwatch 1234
    python anime_sync.py --untrack 1234
"""

import json
import os
import ssl
import sys
import time
import urllib.request
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
CACHE = os.path.join(DATA, "anime.json")
WATCHLIST = os.path.join(DATA, "watchlist.json")
CACHE_HOURS = 6

QUERY = """
query ($season: MediaSeason, $year: Int, $page: Int) {
  Page(page: $page, perPage: 50) {
    media(season: $season, seasonYear: $year, type: ANIME,
          sort: POPULARITY_DESC, isAdult: false) {
      id
      title { romaji english }
      episodes
      averageScore
      popularity
      genres
      format
      status
      duration
      coverImage { large color }
      siteUrl
      nextAiringEpisode { airingAt episode }
    }
  }
}
"""

BY_ID = """
query ($ids: [Int]) {
  Page(page: 1, perPage: 50) {
    media(id_in: $ids, type: ANIME) {
      id
      title { romaji english }
      episodes
      averageScore
      genres
      format
      status
      duration
      coverImage { large color }
      siteUrl
      nextAiringEpisode { airingAt episode }
    }
  }
}
"""


def _ensure_dirs():
    os.makedirs(DATA, exist_ok=True)


def _post(query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        "https://graphql.anilist.co",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "NightOwl/1.0",
        },
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=30, context=ctx) as f:
        payload = json.loads(f.read().decode("utf-8"))
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]


def current_season(now=None):
    now = now or datetime.now()
    season = {
        1: "WINTER", 2: "WINTER", 3: "WINTER",
        4: "SPRING", 5: "SPRING", 6: "SPRING",
        7: "SUMMER", 8: "SUMMER", 9: "SUMMER",
        10: "FALL", 11: "FALL", 12: "FALL",
    }[now.month]
    return season, now.year


def _shape(m):
    t = m["title"]
    nxt = m.get("nextAiringEpisode")
    out = {
        "id": m["id"],
        "title": t.get("english") or t.get("romaji"),
        "romaji": t.get("romaji"),
        "episodes": m.get("episodes"),
        "score": m.get("averageScore"),
        "genres": (m.get("genres") or [])[:3],
        "format": m.get("format"),
        "status": m.get("status"),
        "duration": m.get("duration"),
        "cover": (m.get("coverImage") or {}).get("large"),
        "color": (m.get("coverImage") or {}).get("color") or "#c084fc",
        "url": m.get("siteUrl"),
        "nextEpisode": None,
        "nextAiringAt": None,
    }
    if nxt:
        out["nextEpisode"] = nxt["episode"]
        out["nextAiringAt"] = nxt["airingAt"]
    return out


def load_watchlist():
    if os.path.exists(WATCHLIST):
        try:
            with open(WATCHLIST, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"items": []}


def save_watchlist(wl):
    _ensure_dirs()
    with open(WATCHLIST, "w", encoding="utf-8") as f:
        json.dump(wl, f, indent=2)


def load_cache():
    if os.path.exists(CACHE):
        try:
            with open(CACHE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def _save_cache(cache):
    _ensure_dirs()
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


def _enrich_watchlist(cache):
    """Pull in tracked shows that aren't in the current season (carry-overs,
    older series). Runs on every call, not just cache misses - otherwise a show
    tracked while the cache is warm never gets a title or cover."""
    wl_ids = [i["id"] for i in load_watchlist().get("items", [])]
    if not wl_ids:
        return cache
    have = {s["id"] for s in cache.get("shows", [])}
    missing = [i for i in wl_ids if i not in have]
    if not missing:
        return cache
    try:
        data = _post(BY_ID, {"ids": missing})
        cache.setdefault("shows", []).extend(_shape(m) for m in data["Page"]["media"])
        _save_cache(cache)
    except Exception:
        pass
    return cache


def refresh(force=False):
    """Fetch the season. Falls back to the last good cache if the network is down."""
    _ensure_dirs()
    cache = load_cache()
    fresh = (cache is not None
             and not force
             and (time.time() - cache.get("fetchedAt", 0)) < CACHE_HOURS * 3600)

    if not fresh:
        season, year = current_season()
        try:
            shows = []
            for page in (1, 2):
                data = _post(QUERY, {"season": season, "year": year, "page": page})
                shows.extend(_shape(m) for m in data["Page"]["media"])
                time.sleep(0.8)      # AniList asks for <= 90 req/min; be polite
            cache = {
                "season": season,
                "year": year,
                "fetchedAt": time.time(),
                "fetchedAtLocal": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "shows": shows,
                "stale": False,
            }
            _save_cache(cache)
        except Exception as e:
            if cache:
                cache["stale"] = True
                cache["error"] = str(e)
            else:
                raise

    return _enrich_watchlist(cache)


def upcoming(shows, days=7, now=None):
    """Episodes airing in the next `days`, grouped by local calendar date."""
    now = now or datetime.now()
    horizon = now + timedelta(days=days)
    rows = []
    for s in shows:
        if not s.get("nextAiringAt"):
            continue
        when = datetime.fromtimestamp(s["nextAiringAt"])
        if now <= when <= horizon:
            rows.append({
                "id": s["id"],
                "title": s["title"],
                "episode": s["nextEpisode"],
                "at": when.isoformat(),
                "date": when.strftime("%Y-%m-%d"),
                "day": when.strftime("%a"),
                "time": when.strftime("%H:%M"),
                "cover": s["cover"],
                "color": s["color"],
                "url": s["url"],
            })
    rows.sort(key=lambda r: r["at"])
    return rows


def _find(shows, sid):
    for s in shows:
        if s["id"] == sid:
            return s
    return None


def track(sid):
    wl = load_watchlist()
    if any(i["id"] == sid for i in wl["items"]):
        return wl
    # Add first, then refresh - the enrich step only fetches shows that are
    # already on the watchlist.
    wl["items"].append({"id": sid, "title": str(sid), "progress": 0,
                        "added": datetime.now().isoformat()})
    save_watchlist(wl)

    cache = refresh()
    show = _find(cache.get("shows", []), sid)
    if show:
        for i in wl["items"]:
            if i["id"] == sid:
                i["title"] = show["title"]
        save_watchlist(wl)
    return wl


def untrack(sid):
    wl = load_watchlist()
    wl["items"] = [i for i in wl["items"] if i["id"] != sid]
    save_watchlist(wl)
    return wl


def bump(sid, delta):
    wl = load_watchlist()
    for i in wl["items"]:
        if i["id"] == sid:
            i["progress"] = max(0, i.get("progress", 0) + delta)
            i["lastWatched"] = datetime.now().isoformat()
    save_watchlist(wl)
    return wl


def digest():
    """Episodes watched since the last digest, per tracked show, then resets
    the checkpoint. Deterministic here rather than left to the caller so a
    digest can never double-count or silently drift."""
    wl = load_watchlist()
    cache = refresh()
    by_id = {s["id"]: s for s in cache.get("shows", [])}
    now = datetime.now()

    rows = []
    for item in wl["items"]:
        show = by_id.get(item["id"], {})
        progress = item.get("progress", 0)
        last_digest = item.get("lastDigestProgress", 0)
        watched_since = max(0, progress - last_digest)
        total = show.get("episodes")
        behind = None
        next_ep = show.get("nextEpisode")
        if next_ep:
            behind = max(0, (next_ep - 1) - progress)
        rows.append({
            "title": show.get("title") or item.get("title"),
            "progress": progress,
            "episodes": total,
            "watchedSinceLastDigest": watched_since,
            "behind": behind,
        })
        item["lastDigestProgress"] = progress

    item_ids_watched = sum(r["watchedSinceLastDigest"] for r in rows)
    save_watchlist(wl)

    return {
        "generatedAtLocal": now.strftime("%Y-%m-%d %H:%M"),
        "season": f"{cache.get('season','').title()} {cache.get('year','')}",
        "totalEpisodesSinceLastDigest": item_ids_watched,
        "shows": rows,
    }


def main(argv):
    args = argv[1:]
    if not args:
        c = refresh()
        print(f"{len(c['shows'])} shows | {c['season']} {c['year']} | "
              f"stale={c.get('stale', False)}")
        return 0

    cmd = args[0]
    sid = int(args[1]) if len(args) > 1 else None
    if cmd == "--refresh":
        c = refresh(force=True)
        print(f"refreshed {len(c['shows'])} shows")
    elif cmd == "--track":
        track(sid); print(f"tracking {sid}")
    elif cmd == "--untrack":
        untrack(sid); print(f"untracked {sid}")
    elif cmd == "--watch":
        bump(sid, 1); print(f"+1 ep for {sid}")
    elif cmd == "--unwatch":
        bump(sid, -1); print(f"-1 ep for {sid}")
    elif cmd == "--digest":
        print(json.dumps(digest(), indent=2))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
