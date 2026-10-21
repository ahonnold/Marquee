#!/usr/bin/env python3
"""Spotify artist ids for profile/music, without hand-editing it.

The page links an act with an id straight to its artist page (open.spotify.com/artist/ID?go=1, which hands
off to the app). Acts without one fall back to a Spotify search link, which is clumsier, especially on
phones. The Spotify export has no artist ids, so they are looked up with the Spotify connector.

  spotify_ids.py missing <feed_dir> <profile_music.json>
      Prints, one per line, music acts that play a show in the feed but have no id yet.
  spotify_ids.py fill <profile_music.json> <ids.json> [<ids2.json> ...] --out <out.json>
      ids.json: {"Artist name": "spotifyArtistId" or "https://open.spotify.com/artist/ID", ...}
      Fills ids only for acts whose name matches exactly (case, accents and punctuation ignored) and that
      have no id yet, so a wrong guess never overwrites a known one.
"""
import glob, json, os, re, sys, unicodedata

def norm(s):
    s = unicodedata.normalize('NFD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()

def sid(v):
    m = re.search(r'artist[/:]([A-Za-z0-9]{22})', v or '')
    if m:
        return m.group(1)
    return v if re.fullmatch(r'[A-Za-z0-9]{22}', v or '') else None

def load_acts(path):
    doc = json.load(open(path))
    doc = doc.get('data', doc)
    idx = {}
    for a in doc['acts']:
        idx.setdefault(norm(a[0]), a)
    return doc, idx

def missing(feed_dir, prof):
    _, idx = load_acts(prof)
    out = {}
    for f in sorted(glob.glob(os.path.join(feed_dir, '*.json'))):
        d = json.load(open(f)); d = d.get('data', d)
        for e in d.get('events', []):
            if e.get('category') != 'music':
                continue
            for n in [e.get('headliner')] + list(e.get('supporting') or []):
                a = idx.get(norm(n))
                if a and not a[3]:
                    out[a[0]] = a[1]
    names = sorted(out, key=lambda n: -out[n])
    for n in names:
        print(n)
    return names

def fill(prof, id_files, out):
    doc, idx = load_acts(prof)
    ids = {}
    for f in id_files:
        ids.update(json.load(open(f)))
    filled, unknown, bad = 0, [], []
    for name, v in ids.items():
        s = sid(v)
        if not s:
            bad.append(name); continue
        a = idx.get(norm(name))
        if a is None:
            unknown.append(name); continue
        if not a[3]:
            a[3] = s; filled += 1
    s = json.dumps({'acts': doc['acts']}, ensure_ascii=False, separators=(',', ':'))
    assert len(s.encode()) < 250_000, 'profile/music too big'
    open(out, 'w').write(s)
    have = sum(1 for a in doc['acts'] if a[3])
    print(f'filled {filled} ids; {have}/{len(doc["acts"])} acts have one; '
          f'no act named: {", ".join(unknown) or "-"}; not an id: {", ".join(bad) or "-"}')
    return filled

def main(argv):
    if len(argv) >= 3 and argv[0] == 'missing':
        missing(argv[1], argv[2])
    elif len(argv) >= 4 and argv[0] == 'fill' and '--out' in argv:
        i = argv.index('--out'); out = argv[i + 1]; rest = argv[1:i] + argv[i + 2:]
        fill(rest[0], rest[1:], out)
    else:
        sys.exit(__doc__)

if __name__ == '__main__':
    main(sys.argv[1:])
