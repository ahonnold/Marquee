#!/usr/bin/env python3
"""Marquee data pipeline: merge, validate, dedupe and chunk show listings for the page's database.

The daily refresh (a scheduled Claude task) never edits the feed JSON by hand. It downloads the
current docs, writes what it found into small input files, runs this script, and sends the batch
this script prints. See pipeline/README.md for the full loop.

  python3 marquee_pipeline.py build \
      --feed  DIR            # current feed docs, e.g. ArtifactData list feed --out_dir → DIR/feed/*.json
      --meta  FILE           # current meta/status doc (optional on first run)
      --profile-dir DIR      # profile docs (owner.json, music.json) for "notable" detection (optional)
      --add   FILE ...       # new or updated events (arrays of event objects, see SCHEMA.md)
      --patch FILE ...       # partial updates [{id, field: value, ...}]; {"id", "cancelled": true} removes
      --remove FILE          # ["event-id", ...]
      --versions FILE        # {"feed/m-2026-11": 3, "meta/status": 7}: versions from the listing, for if_version
      --today YYYY-MM-DD --now ISO8601   # defaults: current UTC time
      --out DIR

Outputs in --out: feed/<doc>.json, meta.json, writes.json (ready for one ArtifactData batch call;
writes_2.json ... when the batch would exceed the size limit), summary.txt.
"""
import argparse, collections, datetime, glob, json, os, re, sys, unicodedata

CATEGORIES = ('music', 'comedy', 'theater')
STATUSES = ('on_sale', 'announced', 'sold_out', 'low_tickets')
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
FIELDS = ['id', 'category', 'title', 'headliner', 'supporting', 'venue', 'city', 'address', 'date', 'end_date',
          'time', 'doors', 'on_sale', 'presale', 'ticket_url', 'price', 'status', 'notes', 'tags', 'region',
          'pick', 'pick_reason', 'suggested', 'first_seen']
BAY = ['san francisco', 'oakland', 'berkeley', 'san jose', 'mountain view', 'palo alto', 'stanford', 'saratoga',
       'concord', 'santa clara', 'sausalito', 'mill valley', 'san mateo', 'redwood city', 'emeryville', 'richmond',
       'walnut creek', 'daly city', 'south san francisco', 'san rafael', 'larkspur', 'fremont', 'hayward', 'alameda',
       'livermore', 'sunnyvale', 'menlo park', 'burlingame', 'san carlos', 'los gatos', 'campbell', 'cupertino',
       'petaluma', 'napa', 'novato', 'pleasanton', 'danville', 'orinda', 'lafayette', 'corte madera',
       'half moon bay', 'pacifica', 'millbrae', 'san bruno', 'san leandro', 'castro valley', 'milpitas', 'belmont',
       'foster city', 'tiburon', 'santa rosa', 'vallejo', 'benicia', 'martinez', 'dublin', 'pittsburg', 'antioch',
       'brisbane', 'sf']
DOC_LIMIT = 190_000      # bytes per feed doc (db cap is 256 KiB)
BATCH_LIMIT = 900_000    # bytes of file content per batch call (cap is 1 MiB)
BATCH_WRITES = 50


def norm(s):
    s = unicodedata.normalize('NFD', s or '')
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn').lower()
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def slug(s):
    return re.sub(r'[^a-z0-9]+', '-', norm(s)).strip('-')


def region(city):
    c = norm(city)
    if not c:
        return 'other'
    toks = c.split()
    in_ca = 'ca' in toks or 'california' in c
    other_state = len(toks) >= 2 and len(toks[-1]) == 2 and toks[-1] != 'ca'
    for b in BAY:
        if (c.startswith(b) or f' {b} ' in f' {c} ') and (in_ca or not other_state):
            return 'bay'
    return 'ca' if in_ca else 'other'


def make_id(e):
    return slug(f"{e['category']} {e['headliner']} {e['date']} {e['venue']} {e.get('time') or ''}")[:150] or slug(
        f"{e['category']} {e['date']}")


def clean(e, problems):
    """Normalize one event; return None (and log why) if it can't be used."""
    if not isinstance(e, dict):
        problems.append('not an object'); return None
    cat = e.get('category')
    head = (e.get('headliner') or e.get('title') or '').strip()
    d = str(e.get('date') or '')
    if cat not in CATEGORIES or not head or not DATE.match(d):
        problems.append(f"invalid: {e.get('id') or head or '?'} (category/headliner/date)"); return None
    try:
        datetime.date.fromisoformat(d)
    except ValueError:
        problems.append(f'bad date {d} for {head}'); return None
    end = e.get('end_date') if e.get('end_date') and DATE.match(str(e['end_date'])) else None
    url = e.get('ticket_url') or e.get('source_url') or None
    if url and not re.match(r'^https?://', str(url)):
        url = None
    out = {
        'category': cat, 'title': (e.get('title') or head).strip(), 'headliner': head,
        'supporting': [s.strip() for s in (e.get('supporting') or []) if isinstance(s, str) and s.strip()][:8],
        'venue': (e.get('venue') or '').strip(), 'city': (e.get('city') or '').strip(),
        'address': e.get('address') or None, 'date': d, 'end_date': end if end and end > d else None,
        'time': e.get('time') or None, 'doors': e.get('doors') or None,
        'on_sale': e.get('on_sale') if e.get('on_sale') and DATE.match(str(e['on_sale'])) else None,
        'presale': e.get('presale') or None, 'ticket_url': url, 'price': e.get('price') or None,
        'status': e.get('status') if e.get('status') in STATUSES else None,
        'notes': (e.get('notes') or None), 'tags': [t.lower().strip() for t in (e.get('tags') or []) if isinstance(t, str) and t.strip()][:4],
    }
    if out['notes'] and len(out['notes']) > 260:
        out['notes'] = out['notes'][:257] + '…'
    if e.get('pick'):
        out['pick'] = True; out['pick_reason'] = (e.get('pick_reason') or 'Pick for you')[:120]
    if e.get('suggested') or 'suggested comic' in (e.get('notes') or '').lower():
        out['suggested'] = True
    out['region'] = region(out['city'])
    out['id'] = e.get('id') if isinstance(e.get('id'), str) and re.match(r'^[a-z0-9-]{3,150}$', e['id']) else make_id(out)
    if e.get('first_seen'):
        out['first_seen'] = str(e['first_seen'])[:20]
    return out


def richness(e):
    return sum(1 for k, v in e.items() if v not in (None, '', [], False))


def performers(e):
    names = {norm(e['headliner'])} | {norm(s) for s in e.get('supporting') or []}
    # headliners like "Chromeo & Marc Rebillet" also count as their parts
    for part in re.split(r'\s*(?:&| and |,| with | x |/)\s*', e['headliner'], flags=re.I):
        if norm(part):
            names.add(norm(part))
    return {n for n in names if n}


def same_show(a, b):
    if a['category'] != b['category'] or a['date'] != b['date']:
        return False
    va, vb = norm(a['venue']).replace(' ', ''), norm(b['venue']).replace(' ', '')
    if not va or not vb or not (va[:8] == vb[:8] or va in vb or vb in va):
        return False
    if a.get('time') and b.get('time') and norm(a['time']) != norm(b['time']):
        return False                     # early/late shows are separate events
    return bool(performers(a) & performers(b))


def merge(keep, other):
    """Fill keep's empty fields from other; keep the older first_seen."""
    for k, v in other.items():
        if k in ('id',):
            continue
        if keep.get(k) in (None, '', []) and v not in (None, '', []):
            keep[k] = v
    if other.get('first_seen') and (not keep.get('first_seen') or other['first_seen'] < keep['first_seen']):
        keep['first_seen'] = other['first_seen']
    return keep


def dedupe(events):
    by_day = collections.defaultdict(list)
    for e in events:
        by_day[(e['category'], e['date'])].append(e)
    out, merged = [], 0
    for group in by_day.values():
        kept = []
        for e in sorted(group, key=lambda x: (x.get('first_seen') or '9', -richness(x))):
            twin = next((k for k in kept if same_show(k, e)), None)
            if twin:
                merge(twin, e); merged += 1
            else:
                kept.append(e)
        out.extend(kept)
    return out, merged


def load_events(feed_dir):
    events, names = [], {}
    for f in sorted(glob.glob(os.path.join(feed_dir, '**', '*.json'), recursive=True)):
        doc = json.load(open(f))
        names[os.path.splitext(os.path.basename(f))[0]] = doc
        events.extend(doc.get('events') or [])
    return events, names


def canon(doc):
    return json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def loved_acts(profile_dir):
    loved = set()
    if not profile_dir:
        return loved
    for name in ('owner', 'profile_owner'):
        p = os.path.join(profile_dir, name + '.json')
        if os.path.exists(p):
            for a in json.load(open(p)).get('acts', []):
                if a.get('kind') == 'seed' or (a.get('score') or 0) >= 0.7:
                    loved.add(norm(a['name']))
    for name in ('music', 'profile_music'):
        p = os.path.join(profile_dir, name + '.json')
        if os.path.exists(p):
            for m in json.load(open(p)).get('acts', []):
                if m[1] >= 0.7 and not (len(m) > 5 and m[5]):
                    loved.add(norm(m[0]))
    return loved


def fmt_day(d):
    dt = datetime.date.fromisoformat(d)
    return dt.strftime('%b ') + str(dt.day) + (dt.strftime(' %Y') if dt.year != datetime.date.today().year else '')


def build(a):
    now = a.now or datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    today = a.today or now[:10]
    problems = []
    raw, old_docs = load_events(a.feed) if a.feed else ([], {})
    old = {}
    for e in raw:
        c = clean(e, problems)
        if c:
            c.setdefault('first_seen', a.baseline or today)
            old[c['id']] = c
    before = {k: dict(v) for k, v in old.items()}
    events = dict(old)
    added, updated, removed = [], set(), []

    # additions: new events, or updates when they match an existing show
    for f in a.add or []:
        for e in json.load(open(f)):
            c = clean(e, problems)
            if not c:
                continue
            twin = events.get(c['id']) or next((x for x in events.values() if same_show(x, c)), None)
            if twin:
                changed = False
                for k, v in c.items():
                    if k in ('id', 'first_seen') or v in (None, '', []):
                        continue
                    if twin.get(k) != v:
                        twin[k] = v; changed = True
                if changed:
                    updated.add(twin['id'])
            else:
                c['first_seen'] = now
                events[c['id']] = c; added.append(c['id'])

    for f in a.patch or []:
        for p in json.load(open(f)):
            e = events.get(p.get('id'))
            if not e:
                problems.append(f"patch for unknown id {p.get('id')}"); continue
            if p.get('cancelled'):
                removed.append(e['id']); del events[e['id']]; continue
            for k, v in p.items():
                if k in ('id', 'source_url', 'cancelled') or k not in FIELDS:
                    continue
                if k == 'status' and v not in STATUSES + (None,):
                    continue
                if e.get(k) != v:
                    e[k] = v; updated.add(e['id'])

    if a.remove:
        for rid in json.load(open(a.remove)):
            if rid in events:
                del events[rid]; removed.append(rid)

    # re-validate everything after edits, dedupe, drop past shows
    final = []
    for e in events.values():
        c = clean(e, problems)
        if c:
            c['first_seen'] = e.get('first_seen') or now
            final.append(c)
    final, merged = dedupe(final)
    past = [e['id'] for e in final if (e['end_date'] or e['date']) < today]
    final = [e for e in final if (e['end_date'] or e['date']) >= today]
    final.sort(key=lambda e: (e['date'], e['headliner'].lower(), e.get('time') or ''))

    # status changes worth reporting
    status_changes = []
    for e in final:
        b = before.get(e['id'])
        if b and b.get('status') != e.get('status') and e.get('status') in ('sold_out', 'low_tickets'):
            status_changes.append({'id': e['id'], 'from': b.get('status'), 'to': e['status']})

    loved = loved_acts(a.profile_dir)
    notable = []
    final_ids = {e['id'] for e in final}
    for e in final:
        if e['id'] in added and e['region'] == 'bay' and performers(e) & loved:
            notable.append(f"{e['headliner']} · {e['venue']} · {fmt_day(e['date'])}")

    # chunk by month (ongoing runs count toward the current month)
    months = collections.OrderedDict()
    for e in final:
        months.setdefault('m-' + max(e['date'], today)[:7], []).append(e)
    docs = collections.OrderedDict()
    for mid, evs in months.items():
        part, size, parts = [], 0, []
        for e in evs:
            s = len(json.dumps(e, ensure_ascii=False, separators=(',', ':')).encode()) + 1
            if part and size + s > DOC_LIMIT:
                parts.append(part); part, size = [], 0
            part.append(e); size += s
        parts.append(part)
        for i, p in enumerate(parts):
            docs[mid if len(parts) == 1 else f'{mid}-{chr(97 + i)}'] = {'events': p, 'n': len(p)}

    versions = json.load(open(a.versions)) if a.versions and os.path.exists(a.versions) else {}
    os.makedirs(os.path.join(a.out, 'feed'), exist_ok=True)
    writes = []
    for did, doc in docs.items():
        path = os.path.abspath(os.path.join(a.out, 'feed', did + '.json'))
        open(path, 'w').write(json.dumps(doc, ensure_ascii=False, separators=(',', ':')))
        if did in old_docs and canon(old_docs[did]) == canon(doc):
            continue
        w = {'op': 'set', 'collection': 'feed', 'doc_id': did, 'file_path': path}
        if did in old_docs and versions.get(f'feed/{did}'):
            w['if_version'] = versions[f'feed/{did}']
        writes.append(w)
    for did in old_docs:
        if did not in docs:
            w = {'op': 'delete', 'collection': 'feed', 'doc_id': did}
            if versions.get(f'feed/{did}'):
                w['if_version'] = versions[f'feed/{did}']
            writes.append(w)

    old_meta = json.load(open(a.meta)) if a.meta and os.path.exists(a.meta) else {}
    run = {'at': now, 'added': len([i for i in added if i in final_ids]), 'updated': len(updated & final_ids),
           'removed': len(removed), 'merged': merged, 'past': len(past),
           'statusChanges': status_changes[:20], 'notable': notable[:10]}
    bycat = collections.Counter(e['category'] for e in final)
    meta = {'updatedAt': now, 'total': len(final), 'byCategory': dict(bycat),
            'bayArea': sum(e['region'] == 'bay' for e in final), 'chunks': list(docs),
            'lastRun': run,
            'log': ([{k: run[k] for k in ('at', 'added', 'updated', 'removed')}] + (old_meta.get('log') or []))[:14]}
    mpath = os.path.abspath(os.path.join(a.out, 'meta.json'))
    open(mpath, 'w').write(json.dumps(meta, ensure_ascii=False, separators=(',', ':')))
    w = {'op': 'set', 'collection': 'meta', 'doc_id': 'status', 'file_path': mpath}
    if versions.get('meta/status'):
        w['if_version'] = versions['meta/status']
    writes.append(w)

    # split into batches under the size and count limits
    batches, cur, size = [], [], 0
    for w in writes:
        s = os.path.getsize(w['file_path']) if 'file_path' in w else 100
        if cur and (size + s > BATCH_LIMIT or len(cur) >= BATCH_WRITES):
            batches.append(cur); cur, size = [], 0
        cur.append(w); size += s
    batches.append(cur)
    for old_f in glob.glob(os.path.join(a.out, 'writes*.json')):
        os.remove(old_f)
    for i, b in enumerate(batches):
        open(os.path.join(a.out, 'writes.json' if i == 0 else f'writes_{i + 1}.json'), 'w').write(json.dumps(b, indent=1))

    summary = [f"{len(final)} shows in {len(docs)} docs ({dict(bycat)}); bay area {meta['bayArea']}",
               f"added {run['added']}, updated {run['updated']}, removed {run['removed']}, merged duplicates {merged}, dropped past {len(past)}",
               f"writes: {len(writes)} in {len(batches)} batch(es) -> {', '.join('writes.json' if i == 0 else f'writes_{i + 1}.json' for i in range(len(batches)))}"]
    if notable:
        summary.append('NOTABLE (new Bay Area dates for loved acts): ' + ' | '.join(notable))
    if status_changes:
        summary.append('STATUS: ' + ' | '.join(f"{s['id']} {s['from']}->{s['to']}" for s in status_changes))
    if problems:
        summary.append(f'{len(problems)} input problems: ' + '; '.join(problems[:15]))
    open(os.path.join(a.out, 'summary.txt'), 'w').write('\n'.join(summary) + '\n')
    print('\n'.join(summary))
    return meta, writes


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build')
    b.add_argument('--feed'); b.add_argument('--meta'); b.add_argument('--profile-dir')
    b.add_argument('--add', nargs='*'); b.add_argument('--patch', nargs='*'); b.add_argument('--remove')
    b.add_argument('--versions'); b.add_argument('--today'); b.add_argument('--now'); b.add_argument('--baseline')
    b.add_argument('--out', required=True)
    a = p.parse_args(argv)
    if a.cmd == 'build':
        build(a)


if __name__ == '__main__':
    main()
