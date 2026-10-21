import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'pipeline'))
import marquee_pipeline as mp


def ev(**k):
    base = {'category': 'music', 'headliner': 'Band', 'venue': 'The Chapel', 'city': 'San Francisco, CA',
            'date': '2026-11-13', 'time': '8:00 PM', 'ticket_url': 'https://x.test/t'}
    base.update(k)
    return base


def run(tmp, feed=None, add=None, patch=None, meta=None, versions=None, today='2026-10-21'):
    fd = tmp / 'feed'; fd.mkdir(exist_ok=True)
    for name, events in (feed or {}).items():
        (fd / f'{name}.json').write_text(json.dumps({'events': events}))
    args = ['build', '--feed', str(fd), '--out', str(tmp / 'out'), '--today', today, '--now', today + 'T13:00:00Z']
    if add is not None:
        (tmp / 'add.json').write_text(json.dumps(add)); args += ['--add', str(tmp / 'add.json')]
    if patch is not None:
        (tmp / 'patch.json').write_text(json.dumps(patch)); args += ['--patch', str(tmp / 'patch.json')]
    if meta is not None:
        (tmp / 'meta.json').write_text(json.dumps(meta)); args += ['--meta', str(tmp / 'meta.json')]
    if versions is not None:
        (tmp / 'v.json').write_text(json.dumps(versions)); args += ['--versions', str(tmp / 'v.json')]
    mp.main(args)
    out = tmp / 'out'
    docs = {p.stem: json.loads(p.read_text()) for p in (out / 'feed').glob('*.json')}
    return docs, json.loads((out / 'meta.json').read_text()), json.loads((out / 'writes.json').read_text())


def all_events(docs):
    return [e for d in docs.values() for e in d['events']]


def test_new_events_get_first_seen_and_month_chunks(tmp_path):
    docs, meta, writes = run(tmp_path, add=[ev(), ev(headliner='Other', date='2027-01-05')])
    assert set(docs) == {'m-2026-11', 'm-2027-01'}
    assert all(e['first_seen'] == '2026-10-21T13:00:00Z' for e in all_events(docs))
    assert meta['lastRun']['added'] == 2
    assert [w['doc_id'] for w in writes if w['collection'] == 'feed'] == ['m-2026-11', 'm-2027-01']


def test_duplicate_listings_merge(tmp_path):
    a = ev(headliner='Gracie Abrams', supporting=['Rachel Chinouriri'], venue='Oakland Arena', city='Oakland, CA', time=None, date='2026-12-06')
    b = ev(headliner='Gracie Abrams', venue='Oakland Arena', city='Oakland, CA', time='8:00 PM', date='2026-12-06', price='$60')
    docs, meta, _ = run(tmp_path, add=[a, b])
    evs = all_events(docs)
    assert len(evs) == 1 and evs[0]['time'] == '8:00 PM' and evs[0]['supporting'] == ['Rachel Chinouriri']


def test_combined_headliner_merges_with_single(tmp_path):
    a = ev(headliner='Chromeo & Marc Rebillet', venue='The Midway', date='2026-10-24', time=None)
    b = ev(headliner='Marc Rebillet', supporting=['Chromeo'], venue='The Midway', date='2026-10-24', time='3:00 PM')
    docs, _, _ = run(tmp_path, add=[a, b])
    assert len(all_events(docs)) == 1


def test_early_and_late_shows_stay_separate(tmp_path):
    docs, _, _ = run(tmp_path, add=[ev(category='comedy', time='7:30 PM'), ev(category='comedy', time='9:45 PM')])
    assert len(all_events(docs)) == 2


def test_past_shows_dropped_but_ongoing_runs_kept(tmp_path):
    docs, meta, _ = run(tmp_path, add=[ev(date='2026-10-01'), ev(category='theater', headliner='Play', date='2026-10-01', end_date='2026-11-30', time=None)])
    evs = all_events(docs)
    assert [e['headliner'] for e in evs] == ['Play']
    assert 'm-2026-10' in docs  # ongoing run lives in the current month


def test_unchanged_docs_not_rewritten_and_stale_docs_deleted(tmp_path):
    e = mp.clean(ev(first_seen='2026-10-19'), [])
    feed = {'m-2026-11': [e], 'chunk-0': []}
    (tmp_path / 'feed').mkdir()
    (tmp_path / 'feed' / 'm-2026-11.json').write_text(json.dumps({'events': [e], 'n': 1}))
    (tmp_path / 'feed' / 'chunk-0.json').write_text(json.dumps({'events': []}))
    docs, meta, writes = run(tmp_path, versions={'feed/chunk-0': 4, 'meta/status': 9})
    feed_writes = [w for w in writes if w['collection'] == 'feed']
    assert feed_writes == [{'op': 'delete', 'collection': 'feed', 'doc_id': 'chunk-0', 'if_version': 4}]
    assert [w for w in writes if w['collection'] == 'meta'][0]['if_version'] == 9


def test_patch_status_change_and_cancel(tmp_path):
    a = mp.clean(ev(first_seen='2026-10-19'), []); b = mp.clean(ev(headliner='Gone', first_seen='2026-10-19'), [])
    docs, meta, _ = run(tmp_path, feed={'m-2026-11': [a, b]},
                        patch=[{'id': a['id'], 'status': 'sold_out'}, {'id': b['id'], 'cancelled': True}])
    evs = all_events(docs)
    assert [e['status'] for e in evs] == ['sold_out']
    assert meta['lastRun']['statusChanges'][0]['to'] == 'sold_out' and meta['lastRun']['removed'] == 1


def test_update_via_add_keeps_id_and_first_seen(tmp_path):
    a = mp.clean(ev(first_seen='2026-10-19', time=None), [])
    docs, meta, _ = run(tmp_path, feed={'m-2026-11': [a]}, add=[ev(time=None, doors='7:00 PM', price='$25')])
    e = all_events(docs)[0]
    assert e['id'] == a['id'] and e['first_seen'] == '2026-10-19' and e['doors'] == '7:00 PM'
    assert meta['lastRun']['added'] == 0 and meta['lastRun']['updated'] == 1


def test_invalid_events_rejected(tmp_path):
    docs, meta, _ = run(tmp_path, add=[ev(date='Nov 13'), ev(category='sports'), ev(headliner='')])
    assert all_events(docs) == [] and meta['total'] == 0


def test_log_keeps_last_14(tmp_path):
    old = {'log': [{'at': f'2026-10-{i:02d}', 'added': 0, 'updated': 0, 'removed': 0} for i in range(1, 20)]}
    _, meta, _ = run(tmp_path, add=[ev()], meta=old)
    assert len(meta['log']) == 14 and meta['log'][0]['added'] == 1


def test_large_month_splits(tmp_path):
    many = [ev(headliner=f'Band {i}', notes='x' * 250, time=f'{i % 12 + 1}:00 PM') for i in range(400)]
    docs, _, _ = run(tmp_path, add=many)
    assert len(docs) >= 2 and all(len(json.dumps(d)) < 256_000 for d in docs.values())


def test_spotify_ids_fill_and_missing(tmp_path, capsys):
    import spotify_ids as si
    prof = tmp_path / 'music.json'
    prof.write_text(json.dumps({'acts': [['Café Tacvba', 0.9, '', None, None, 0],
                                         ['Known', 0.8, '', 'KnownId000000000000000', None, 0],
                                         ['Other', 0.5, '', None, None, 0]]}))
    fd = tmp_path / 'feed'; fd.mkdir()
    (fd / 'm-2026-11.json').write_text(json.dumps({'events': [ev(headliner='Cafe Tacvba', supporting=['Other', 'Known']),
                                                              ev(category='comedy', headliner='Other')]}))
    assert si.missing(str(fd), str(prof)) == ['Café Tacvba', 'Other']
    ids = tmp_path / 'ids.json'
    ids.write_text(json.dumps({'cafe tacvba': 'https://open.spotify.com/artist/TacvbaId00000000000000?si=x',
                               'Known': 'WrongId000000000000000', 'Nobody': 'NobodyId00000000000000', 'Other': 'not-an-id'}))
    out = tmp_path / 'out.json'
    assert si.fill(str(prof), [str(ids)], str(out)) == 1
    acts = {a[0]: a[3] for a in json.loads(out.read_text())['acts']}
    assert acts == {'Café Tacvba': 'TacvbaId00000000000000', 'Known': 'KnownId000000000000000', 'Other': None}
