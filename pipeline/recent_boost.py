#!/usr/bin/env python3
"""Fold recent Spotify signals (from the Spotify connector) into profile/music without hand-editing it.

Usage: recent_boost.py <profile_music.json> <recent.json> <out.json>
recent.json: [{"name": "Artist", "kind": "top4w" | "recent" | "followed", "rank": 1, "spotify": "https://open.spotify.com/artist/ID"}]
- top4w (top artists, last 4 weeks): score >= 0.75 - 0.01*rank, why "on repeat lately"
- recent (recently played):          score >= 0.4
- followed:                          score >= 0.4
Existing artists keep their links; new artists are appended. Output stays sorted by score.
"""
import json, re, sys

def sid(url):
    m = re.search(r'open\.spotify\.com/artist/([A-Za-z0-9]+)', url or '')
    return m.group(1) if m else None

def main(prof_path, recent_path, out):
    doc = json.load(open(prof_path)); acts = doc['acts']
    idx = {a[0].lower(): a for a in acts}
    for r in json.load(open(recent_path)):
        name = (r.get('name') or '').strip()
        if not name:
            continue
        kind = r.get('kind'); rank = int(r.get('rank') or 20)
        floor = {'top4w': 0.75 - 0.01 * rank, 'recent': 0.4, 'followed': 0.4}.get(kind, 0.3)
        a = idx.get(name.lower())
        if a is None:
            a = [name, 0.0, '', sid(r.get('spotify')), None, 0]
            acts.append(a); idx[name.lower()] = a
        if a[1] < floor:
            a[1] = round(floor, 3)
        if kind == 'top4w' and 'lately' not in (a[2] or ''):
            a[2] = (a[2].split(' · ')[0] + ' · on repeat lately') if a[2] else 'on repeat lately'
        elif not a[2]:
            a[2] = 'played recently' if kind == 'recent' else 'you follow them'
        if not a[3]:
            a[3] = sid(r.get('spotify'))
        a[5] = 0
    acts.sort(key=lambda a: -a[1])
    s = json.dumps(doc, ensure_ascii=False, separators=(',', ':'))
    assert len(s.encode()) < 250_000, 'profile/music too big'
    open(out, 'w').write(s)
    print(f'{len(acts)} music acts written to {out}')

if __name__ == '__main__':
    main(*sys.argv[1:4])
