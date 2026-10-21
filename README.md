# Marquee

Songkick broke my heart.

Marquee is a personal tracker for concerts, comedy and theater in the SF Bay Area. It ranks shows
by what you actually listen to and laugh at, syncs the ones you care about to Google Calendar, and
keeps an eye on tickets.

It runs as a [claude.ai](https://claude.ai) artifact: a single HTML page with a small shared
database, plus two scheduled Claude tasks that keep the data fresh.

## What it does

- **Best-match feed.** Every show is scored against your taste: Spotify listening (plays, liked
  songs, recency), hand-picked comedians and the ones like them, and what you tap. Interested /
  Going nudges an act and its genres up; "Not into this act" mutes it.
- **New since your last visit.** Shows the refresh found since you last opened the page get a
  NEW pill and their own filter.
- **Google Calendar.** Interested shows land as free time, Going as busy, on a calendar you pick
  (it defaults to one named "Shows"). Events start at doors and lead with "Doors X · Show Y".
  Un-saving a show removes its event.
- **Tickets.** Purchase emails are matched to saved shows. Otherwise mark "I have tickets",
  "Someone else has tickets" or leave a plan note. A reminder every couple of weeks lists saved
  shows that still need tickets, with on-sale and presale dates.
- **Friends.** Share a show link or an invite. Friends' picks show up on cards, with a "Friends
  going" filter.
- **Been there.** Past Going shows become a diary with 1–5 stars and a note. Ratings feed the
  taste model.
- **Mobile and desktop.** Compact expandable cards, swipe right to save, swipe left to hide,
  undo in toasts, a compact header on scroll, and a side panel on wide screens.

## Layout

```
app/index.html            the page (published as the artifact)
pipeline/
  marquee_pipeline.py     deterministic merge / dedupe / month chunks / changelog → batch writes
  spotify_import.py       Spotify Extended Streaming History → listening aggregates
  build_profile.py        aggregates + comedians → profile/owner, profile/music, profile/tracks
  recent_boost.py         weekly Spotify connector signals → profile/music
  README.md               database layout and the daily refresh loop
  SCHEMA.md               event fields
tests/
  test_pipeline.py        pipeline unit tests (pytest)
  stage_test.py           headless-Chromium tests of the page against a mocked claude.ai runtime
  fixtures/               public listings and synthetic taste data
```

## How data flows

1. A daily scheduled task researches new dates. It runs every day for saved shows, favorite
   acts and tracked acts, rotates through the long tail over the week, and sweeps venues
   (SF music on Monday, East/South Bay on Wednesday, comedy and theater on Friday).
2. It writes what it found to `add.json` / `patch.json`. Then it runs
   `marquee_pipeline.py build`, which validates, merges duplicates, drops past shows, splits by
   month, and emits only the docs that changed as version-checked batch writes.
3. The page reads `feed/m-YYYY-MM` docs live and scores them in the browser. Each viewer's
   picks live in their own `marks/<id>` doc.
4. A push notification arrives only when something notable happened: a new date for an act you
   love, a saved show selling out or moving, or an on-sale coming up. Every other day gets a
   one-line "Quiet refresh".

See [`pipeline/README.md`](pipeline/README.md) for the database layout.

## Privacy

This repo is public. Personal data — listening history, Instagram likes, the generated profile
docs, picks, ticket evidence — lives only in the artifact's database (private docs where
appropriate) and is excluded by `.gitignore`. The test fixtures use public listings and synthetic
taste data.

## Tests

```
pip install pytest playwright && python -m playwright install chromium
python -m pytest -q tests/test_pipeline.py
python tests/stage_test.py          # screenshots in tests/shots/
```

CI runs both on every push.
