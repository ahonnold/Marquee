# Marquee data pipeline

The page (`app/index.html`) is a claude.ai artifact. Its data lives in the artifact's database, which a
daily scheduled Claude task refreshes. The task never edits JSON by hand: it downloads the current
docs, writes what it found into small input files, runs `marquee_pipeline.py`, and sends the batch the
script prints.

## Database layout

| Doc | Shape | Written by |
|---|---|---|
| `feed/m-YYYY-MM` (or `-a`, `-b` when a month is large) | `{"events": [...], "n": N}` | pipeline |
| `meta/status` | `{updatedAt, total, byCategory, bayArea, chunks, lastRun, log}` | pipeline |
| `profile/owner` | `{"acts": [comedians: seed / suggested, ...]}` | build_profile.py / by hand |
| `profile/music` | `{"acts": [[name, score, why, spotifyArtistId, likedPlaylistId, similar], ...]}` | build_profile.py, recent_boost.py |
| `profile/tracks` | `{"t": {artist: [[track, trackId], ...]}}` | build_profile.py |
| `marks/<userId>` | each viewer's picks, tickets notes, ratings, calendar ids | the page only |
| `data/users/<userId>/tickets` | private ticket evidence from email | refresh / reminder tasks |
| `data/users/<userId>/prefs` | private "last visit" times | the page only |

Event fields are in `SCHEMA.md`. Every event keeps a stable `id`; the page keys picks by it.

## Daily refresh loop (what the scheduled task does)

1. `ArtifactData list` the `feed` collection and `meta` with `out_dir` → `work/live/feed/*.json`,
   `work/live/meta/status.json`; note each doc's `version` into `work/versions.json`
   as `{"feed/m-2026-11": 3, "meta/status": 7}`.
2. `Artifact read` this artifact's published file `pipeline/marquee_pipeline.py` (path) to get the script.
3. Research. Write findings to:
   - `work/add.json` — new shows (full event objects) or updates to known shows (same act/date/venue).
   - `work/patch.json` — `[{"id": ..., "status": "sold_out"}, {"id": ..., "cancelled": true}]`.
4. Run:
   `python3 marquee_pipeline.py build --feed work/live/feed --meta work/live/meta/status.json --profile-dir work/live/profile --add work/add.json --patch work/patch.json --versions work/versions.json --out work/out`
5. Send `work/out/writes.json` as one `ArtifactData batch` (then `writes_2.json` … if printed).
6. The printed summary says what's notable for the push notification.

## Profile updates

- New Spotify export: `spotify_import.py <export_dir> stats.json` then
  `build_profile.py stats.json <current profile/owner.json> out/` and write the three profile docs.
  Stats contain listening history aggregates only; never commit them (this repo is public).
- Weekly connector signal: `recent_boost.py profile_music.json recent.json out.json`.

## Tests

`python3 -m pytest tests/test_pipeline.py` and `python3 tests/stage_test.py` (headless Chromium,
mocked claude.ai runtime, synthetic taste data in `tests/fixtures`).
