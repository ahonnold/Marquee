#!/usr/bin/env python3
"""Turn a Spotify Extended Streaming History export into per-artist taste stats.

Usage: spotify_import.py <export_dir> <out.json> [--today YYYY-MM-DD]
Reads Streaming_History_Audio_*.json. Writes aggregates only (no IPs, no raw history):
[{name, plays, hours, plays90, plays365, weighted, repeat_tracks, first, last, tracks:[[name, track_id, plays]]}]
A "play" is >= 30s listened. weighted = sum of 0.5^(age_days/180) over plays.
"""
import json, glob, os, sys, math, datetime, collections

def main(src, out, today=None):
    today = datetime.datetime.fromisoformat(today) if today else datetime.datetime.utcnow()
    A = collections.defaultdict(lambda: {'plays': 0, 'ms': 0, 'p90': 0, 'p365': 0, 'w': 0.0, 'first': None, 'last': None,
                                         'tracks': collections.Counter(), 'tid': {}})
    files = sorted(glob.glob(os.path.join(src, '**', 'Streaming_History_Audio_*.json'), recursive=True))
    n = 0
    for f in files:
        for r in json.load(open(f, encoding='utf8')):
            artist = r.get('master_metadata_album_artist_name'); track = r.get('master_metadata_track_name')
            if not artist or not track: continue  # podcasts / audiobooks
            ms = r.get('ms_played') or 0
            a = A[artist]; a['ms'] += ms
            if ms < 30000: continue
            ts = datetime.datetime.fromisoformat(r['ts'].replace('Z', ''))
            age = (today - ts).days
            a['plays'] += 1; n += 1
            if age <= 90: a['p90'] += 1
            if age <= 365: a['p365'] += 1
            a['w'] += 0.5 ** (max(age, 0) / 180)
            d = ts.date().isoformat()
            a['first'] = min(a['first'] or d, d); a['last'] = max(a['last'] or d, d)
            a['tracks'][track] += 1
            uri = r.get('spotify_track_uri') or ''
            if uri.startswith('spotify:track:'): a['tid'][track] = uri.split(':')[-1]
    rows = []
    for name, a in A.items():
        if a['plays'] < 3: continue
        top = [[t, a['tid'].get(t), c] for t, c in a['tracks'].most_common(5)]
        rows.append({'name': name, 'plays': a['plays'], 'hours': round(a['ms'] / 3.6e6, 1), 'plays90': a['p90'],
                     'plays365': a['p365'], 'weighted': round(a['w'], 2),
                     'repeat_tracks': sum(1 for c in a['tracks'].values() if c >= 3),
                     'first': a['first'], 'last': a['last'], 'tracks': top})
    rows.sort(key=lambda r: -r['weighted'])
    json.dump(rows, open(out, 'w'))
    print(f'{len(files)} files, {n} plays, {len(rows)} artists with 3+ plays')

if __name__ == '__main__':
    args = sys.argv[1:]
    today = None
    if '--today' in args:
        i = args.index('--today'); today = args[i + 1]; del args[i:i + 2]
    main(args[0], args[1], today)
