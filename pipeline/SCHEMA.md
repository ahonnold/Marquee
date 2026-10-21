# Event record schema

Used by `marquee_pipeline.py` inputs (`--add`) and the feed docs. The pipeline adds `id` (if missing), `region` and `first_seen`.

Each event:
{
  "id": "short-slug-unique e.g. comedy-gianmarco-soresi-2027-01-15-sf-punchline",
  "category": "music" | "comedy" | "theater",
  "title": "Event title as listed",
  "headliner": "Main act (artist / comedian / production name)",
  "supporting": ["openers or co-bill, if listed"],
  "venue": "Venue name",
  "city": "City, ST",
  "address": "Street address if easy to find, else null",
  "date": "YYYY-MM-DD (first date; for multi-night runs use first night)",
  "end_date": "YYYY-MM-DD or null (for runs / multi-night)",
  "time": "Show time like '8:00 PM' or null",
  "doors": "Doors time or null",
  "on_sale": "YYYY-MM-DD or null (general on-sale if in future / known)",
  "presale": "short text on presale if known, else null",
  "ticket_url": "Direct ticket/event page URL",
  "source_url": "Page where you found it",
  "price": "price range text or null",
  "status": "on_sale" | "announced" | "sold_out" | "low_tickets" | null,
  "notes": "anything notable (rare visit, new special taping, small room...)",
  "tags": ["genre / style tags, e.g. 'indie rock', 'musical', 'stand-up', 'improv'"]
}

Rules:
- Only real events you found on a source page. Never invent dates. If uncertain, skip it.
- Date window: 2026-10-20 through 2027-08-31.
- Use real URLs you actually saw.

Pipeline-managed fields: "id" (stable slug), "region" ("bay" | "ca" | "other"), "first_seen" (ISO time the show first appeared), optional "pick"/"pick_reason" (theater), "suggested" (comedy).
