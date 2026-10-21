#!/usr/bin/env python3
"""Build Marquee taste-profile docs from Spotify stats + the current profile.

Usage: build_profile.py <spotify_stats.json> <current_profile_owner.json> <out_dir>
Writes three db docs (each must stay < 256 KB):
  profile/owner  {"acts": [seed/suggested comedians, tracked extras], "music_source": ..., "updatedAt"}
  profile/music  {"acts": [[name, score, why, spotify_artist_id|null, liked_playlist_id|null, similar(0/1)], ...]}
  profile/tracks {"t": {artist_name: [[track_name, track_id], ...]}}   (top artists only)
Scoring (0..1): 0.6*f(recency-weighted plays) + 0.4*g(all-time plays), log-scaled;
f = ln(1+w)/ln(151), g = ln(1+p)/ln(2001), each capped at 1; followed artists +0.05.
"""
import json, math, sys, os, re, datetime

def score(w, p):
    f = min(1.0, math.log1p(w) / math.log1p(150)); g = min(1.0, math.log1p(p) / math.log1p(2000))
    return round(0.6 * f + 0.4 * g, 3)

def why(r, rank):
    bits = []
    if rank <= 25: bits.append(f'#{rank} most played')
    if r['plays90'] >= 10: bits.append(f"{r['plays90']} plays lately")
    elif r['plays365'] >= 20: bits.append(f"{r['plays365']} plays this year")
    elif not bits: bits.append(f"{r['plays']:,} plays all-time")
    return ' · '.join(bits[:2])

def sid(url, kind):
    m = re.search(rf'open\.spotify\.com/{kind}/([A-Za-z0-9]+)', url or '')
    return m.group(1) if m else None

def main(stats_path, prof_path, out):
    stats = json.load(open(stats_path)); prof = json.load(open(prof_path))
    old_music = {a['name'].lower(): a for a in prof['acts'] if a.get('kind') == 'music'}
    keep = [a for a in prof['acts'] if a.get('kind') != 'music']
    followed = {k for k, a in old_music.items() if 'follow' in (a.get('why') or '')}
    rows = [r for r in stats if r['plays'] >= 10]
    bonus = lambda r: 0.05 if r['name'].lower() in followed else 0
    rows.sort(key=lambda r: -(score(r['weighted'], r['plays']) + bonus(r)))
    music, tracks, seen = [], {}, set()
    for rank, r in enumerate(rows, 1):
        k = r['name'].lower(); seen.add(k); o = old_music.get(k, {})
        s = min(1.0, score(r['weighted'], r['plays']) + bonus(r))
        if s < 0.1: continue
        music.append([r['name'], round(s, 3), why(r, rank), sid(o.get('spotify'), 'artist'), sid(o.get('liked'), 'playlist'), 0])
        if len(tracks) < 600 and r['tracks']:
            tracks[r['name']] = [[t[0], t[1]] for t in r['tracks'][:5] if t[1]]
    # connector-only artists (followed / saved albums / similar guesses) that the export doesn't cover
    for k, o in old_music.items():
        if k in seen: continue
        music.append([o['name'], o['score'], o.get('why', ''), sid(o.get('spotify'), 'artist'), sid(o.get('liked'), 'playlist'), 1 if o.get('similar') else 0])
    music.sort(key=lambda m: -m[1])
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    os.makedirs(out, exist_ok=True)
    docs = {'owner': {'acts': keep, 'music_source': 'spotify_export', 'updatedAt': now},
            'music': {'acts': music, 'updatedAt': now},
            'tracks': {'t': tracks, 'updatedAt': now}}
    for k, d in docs.items():
        s = json.dumps(d, ensure_ascii=False, separators=(',', ':'))
        assert len(s.encode()) < 250_000, f'profile/{k} too big: {len(s)}'
        open(os.path.join(out, f'profile_{k}.json'), 'w').write(s)
        print(f'profile/{k}: {len(s.encode())//1024} KB')
    print(f'music acts: {len(music)} (>=0.7: {sum(m[1]>=0.7 for m in music)}, >=0.45: {sum(m[1]>=0.45 for m in music)}, >=0.3: {sum(m[1]>=0.3 for m in music)})')

if __name__ == '__main__':
    main(*sys.argv[1:4])
