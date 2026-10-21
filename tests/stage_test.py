#!/usr/bin/env python3
"""Staged usability test for the Marquee page.

Runs app/index.html in headless Chromium with a mock of the claude.ai runtime (db, user, mcp,
permissions) that behaves like the real one: snapshots are frozen, saves are async, calendar calls
are slow and need permission. Exercises the main flows and prints PASS/FAIL per check.

  python3 tests/stage_test.py [--page app/index.html] [--fixtures tests/fixtures] [--shots DIR]
Env CHROMIUM=/path/to/chrome overrides the browser binary.
"""
import argparse, asyncio, json, os, sys
from playwright.async_api import async_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ap = argparse.ArgumentParser()
ap.add_argument('--page', default=os.path.join(ROOT, 'app', 'index.html'))
ap.add_argument('--fixtures', default=os.path.join(ROOT, 'tests', 'fixtures'))
ap.add_argument('--shots', default=os.path.join(ROOT, 'tests', 'shots'))
args = ap.parse_args()
os.makedirs(args.shots, exist_ok=True)
F = lambda n: json.load(open(os.path.join(args.fixtures, n)))
feed, music, tracks, owner, meta = F('feed.json'), F('music.json'), F('tracks.json'), F('owner.json'), F('meta.json')
events = feed['events']
marked = [e for e in events if e['category'] == 'music'][:3]
marks = {'u_me': {'events': {
    marked[0]['id']: {'s': 'interested', 'at': 'x', 'when': None},
    marked[1]['id']: {'s': 'going', 'at': 'x', 'when': None},
    'past-show-id': {'s': 'going', 'at': 'x', 'snap': {'c': 'music', 'h': 'A Past Band', 'v': 'The Chapel', 'city': 'San Francisco, CA', 'd': '2026-09-12'}}},
    'settings': {'cal': True}, 'tracked': {},
    'cal': {marked[0]['id']: {'id': 'oldcal1', 'kind': 'interested', 'sig': 'v2|interested||'}}},
    'u_friend': {'events': {marked[0]['id']: {'s': 'going'}}}}
tickets = {'events': {marked[1]['id']: {'vendor': 'DICE', 'qty': 2, 'detail': '2 general admission', 'email': 'https://mail.google.com/x'}}}
prefs = {'seen': {'prev': '2026-10-20T00:00:00Z', 'last': '2026-10-20T08:00:00Z'}}

MOCK = r"""<script>
(function(){
const FEED=%s, MUSIC=%s, TRACKS=%s, OWNER=%s, META=%s, MARKS=%s, TICKETS=%s, PREFS=%s;
const freeze=o=>{ if(o&&typeof o==='object'){ Object.values(o).forEach(freeze); Object.freeze(o);} return o; };
const clone=o=>JSON.parse(JSON.stringify(o));
const mkDoc=(id,data)=>freeze({id,exists:data!=null,data:()=>data==null?undefined:freeze(clone(data)),metadata:{fromCache:false,hasPendingWrites:false}});
const DOCS={'profile/owner':OWNER,'profile/music':MUSIC,'profile/tracks':TRACKS,'meta/status':META,'data/users/u_me/tickets':TICKETS,'data/users/u_me/prefs':window.__NOPREFS?null:PREFS};
const msubs=[], dsubs={};
const emitMarks=()=>{ const docs=Object.entries(MARKS).map(([k,v])=>mkDoc(k,v)); msubs.forEach(f=>f(freeze({docs,size:docs.length,empty:!docs.length}))); };
window.__writes=[]; window.__docWrites={};
const db={
 collection(p){ return { onSnapshot(next){ setTimeout(()=>{ if(p==='feed') next({docs:[mkDoc('m-1',FEED)]}); if(p==='marks'){ msubs.push(next); emitMarks(); } },80); return ()=>{}; } }; },
 doc(p){ return { onSnapshot(next){ (dsubs[p]=dsubs[p]||[]).push(next); setTimeout(()=>next(mkDoc(p.split('/').pop(), DOCS[p]??null)),90); return ()=>{}; },
   set(d){ if(!d||typeof d!=='object'||Array.isArray(d)) return Promise.reject({code:'invalid_argument'}); const c=clone(d);
     return new Promise(r=>setTimeout(()=>{ if (p.startsWith('marks/')){ window.__writes.push(c); MARKS[p.split('/')[1]]=c; emitMarks(); } else { window.__docWrites[p]=c; DOCS[p]=c; (dsubs[p]||[]).forEach(f=>f(mkDoc(p.split('/').pop(),c))); } r(); },300)); } }; }
};
const user={isOwner:async()=>true,id:async()=>'u_me',profiles:async(ids)=>Object.fromEntries([].concat(ids).map(i=>[i,{id:i,name:i==='u_friend'?'Sam Rivera':'',avatarUrl:'data:image/gif;base64,R0lGODlhAQABAAAAACw=',color:'#888'}]))};
window.__calls=[]; let n=0; window.__perm=window.__PERM0||'prompt';
const mcp={callTool:(s,t,i)=>{ if(window.__perm!=='granted') return Promise.reject({code:'approval_required',message:'no'}); window.__calls.push([t,i]);
  return new Promise(r=>setTimeout(()=>r({payload: t==='create_event'?{id:'gcal_'+(++n)} : t==='list_calendars'? {calendars:[{id:'a@gmail.com',summary:'Personal'},{id:'shows123@group.calendar.google.com',summary:'Shows'},{id:'x@import.calendar.google.com',summary:'Songkick'}]} : {}}),250)); }};
const perms={state:async()=>window.__perm, request:async()=>{ window.__perm='granted'; return {'mcp:Google Calendar':'granted'}; }, manage:async()=>{}};
window.__clip=[]; try { Object.defineProperty(navigator,'clipboard',{value:{writeText:t=>{ window.__clip.push(t); return Promise.resolve(); }}}); } catch(e){}
window.claude={use:(k)=>Promise.resolve(({db,user,mcp,permissions:perms})[k]||null)};
})();
</script>""" % tuple(json.dumps(x) for x in (feed, music, tracks, owner, meta, marks, tickets, prefs))
page = open(args.page, encoding='utf8').read()
html = "<!doctype html><html><head><meta charset=utf8><meta name=viewport content='width=device-width,initial-scale=1'></head><body>" + MOCK + page + "</body></html>"
STAGE = os.path.join(args.shots, 'stage.html')
open(STAGE, 'w').write(html)

results = []
def check(name, ok, detail=''):
    results.append(bool(ok)); print(('PASS ' if ok else 'FAIL ') + name + (f' — {detail}' if detail != '' else ''))

async def open_page(b, w=390, h=844, scheme='dark', hash='', init='', ua=None, touch=False):
    ctx = await b.new_context(viewport={'width': w, 'height': h}, color_scheme=scheme, has_touch=touch, is_mobile=touch, **({'user_agent': ua} if ua else {}))
    pg = await ctx.new_page(); errs = []
    pg.on('pageerror', lambda e: errs.append(str(e)))
    if init: await pg.add_init_script(init)
    await pg.goto('file://' + STAGE + hash); await pg.wait_for_timeout(1300)
    return pg, errs

async def main():
    async with async_playwright() as p:
        exe = os.environ.get('CHROMIUM') or next((c for c in ['/opt/pw-browsers/chromium-1194/chrome-linux/chrome'] if os.path.exists(c)), None)
        b = await p.chromium.launch(executable_path=exe) if exe else await p.chromium.launch()
        T = lambda pg: pg.evaluate("document.querySelector('.toast')?.innerText||''")

        # ---- phone, dark ----
        pg, errs = await open_page(b)
        n = await pg.locator('article.tix').count(); check('feed renders cards', n > 10, n)
        heads = [h.upper() for h in await pg.locator('.tier-h h2').all_inner_texts()]
        check('Best match is the default (tiers)', "DON'T MISS" in heads or 'WORTH A LOOK' in heads, heads)
        check('no horizontal scroll at 390px', await pg.evaluate('document.documentElement.scrollWidth - innerWidth') <= 0)
        hs = await pg.eval_on_selector_all('article.tix', 'els=>els.map(e=>e.getBoundingClientRect().height)')
        avg = sum(hs) / len(hs); check('collapsed cards are compact (avg < 235px)', avg < 235, round(avg))
        check('no separate artist chips (names are links)', await pg.locator('.finds').count() == 0 and await pg.locator('h3 .nm-link').count() > 0)
        check('stub tinted by category', len(set(await pg.eval_on_selector_all('.stub', 'els=>els.map(e=>getComputedStyle(e).backgroundColor)'))) >= 2)
        check('genre/similar badges have no star', all(not t.startswith('★') for t in await pg.locator('.b.soft').all_inner_texts()))
        await pg.screenshot(path=os.path.join(args.shots, '01_feed_phone_dark.png'))

        # new since last visit
        chip = pg.locator('.sortbar .chip', has_text='new since')
        check('“new since” chip shows', await chip.count() == 1, await chip.inner_text() if await chip.count() else '')
        if await chip.count():
            await chip.click(); await pg.wait_for_timeout(200)
            check('new filter lists only NEW cards', await pg.locator('article.tix').count() == await pg.locator('article.tix .newpill').count() > 0)
            await chip.click(); await pg.wait_for_timeout(200)

        # expand / collapse
        first = pg.locator('article.tix').first
        await first.locator('.meta').click(); await pg.wait_for_timeout(200)
        check('tap card expands details', await pg.locator('article.tix.open .morebody').count() == 1)
        await pg.screenshot(path=os.path.join(args.shots, '02_card_open.png'))
        await pg.locator('article.tix.open .chev').click(); await pg.wait_for_timeout(200)
        check('chevron collapses', await pg.locator('article.tix.open').count() == 0)

        # interested + undo
        btn = pg.locator('article.tix:not(:has(.act[aria-pressed="true"])) button.act.int').first
        cid = await btn.evaluate('b=>b.closest("article").dataset.id')
        await btn.click(); await pg.wait_for_timeout(150)
        check('Interested turns on', await pg.locator(f'article[data-id="{cid}"] button.act.int').first.get_attribute('aria-pressed') == 'true')
        await pg.locator('.toast button', has_text='Undo').click(); await pg.wait_for_timeout(200)
        check('Undo in toast reverts', await pg.locator(f'article[data-id="{cid}"] button.act.int').first.get_attribute('aria-pressed') == 'false')

        # share link + invite
        free = pg.locator('article.tix:not(:has(.act[aria-pressed="true"]))')
        await free.nth(1).locator('.meta').click(); await pg.wait_for_timeout(150)
        oid = await pg.locator('article.tix.open').first.get_attribute('data-id')
        await pg.locator('article.tix.open button', has_text='Copy link').click(); await pg.wait_for_timeout(150)
        await pg.locator('article.tix.open button', has_text='Invite').click(); await pg.wait_for_timeout(150)
        clip = await pg.evaluate('window.__clip')
        check('copy link = artifact URL + #show-id', len(clip) >= 1 and clip[0].endswith('#' + oid), clip[:1])
        check('invite text names venue and link', len(clip) >= 2 and 'Want to see' in clip[1] and '#' + oid in clip[1])

        # hide → not into this act → acts tab lists it → unmute
        before = await pg.locator('article.tix').count()
        await pg.locator('article.tix.open button', has_text='Hide').click(); await pg.wait_for_timeout(200)
        nb = pg.locator('.toast button', has_text='Not into')
        check('hide toast offers “Not into …”', await nb.count() == 1, await T(pg))
        if await nb.count():
            await nb.click(); await pg.wait_for_timeout(200)
            await pg.click('#tab-acts'); await pg.wait_for_timeout(250)
            check('muted act listed under Not into', 'NOT INTO' in (await pg.inner_text('main')).upper())
            await pg.locator('button', has_text='Unmute').first.click(); await pg.wait_for_timeout(200)
            check('unmute works', 'NOT INTO' not in (await pg.inner_text('main')).upper())
            await pg.click('#tab-feed'); await pg.wait_for_timeout(200)

        # saved tab: ticket row, diary, calendar connect + Shows calendar migration
        await pg.click('#tab-mine'); await pg.wait_for_timeout(300)
        check('Saved shows ticket rows', await pg.locator('.tix-row').count() >= 2)
        check('email tickets recognised', await pg.locator('.tix-row.email').count() == 1)
        check('“Been there” diary lists past show', 'A Past Band' in await pg.inner_text('main'))
        await pg.locator('.stars button').nth(3).click(); await pg.wait_for_timeout(500)
        w = await pg.evaluate('window.__writes[window.__writes.length-1]')
        check('rating saved', w['events']['past-show-id'].get('rating') == 4)
        rv = pg.locator('.drow .live-input'); await rv.click(); await rv.type('Loud and great', delay=30); await pg.wait_for_timeout(1500)
        check('typing survives background saves', await rv.input_value() == 'Loud and great')
        await rv.press('Enter'); await pg.wait_for_timeout(600)
        await pg.screenshot(path=os.path.join(args.shots, '03_saved.png'), full_page=True)
        await pg.locator('button', has_text='Connect Google Calendar').click(); await pg.wait_for_timeout(3500)
        calls = await pg.evaluate('window.__calls')
        names = [c[0] for c in calls]
        check('lists calendars after connecting', 'list_calendars' in names, names)
        moved = [c for c in calls if c[0] == 'create_event' and c[1].get('calendarId') == 'shows123@group.calendar.google.com']
        check('auto-picks “Shows” calendar for new events', len(moved) >= 2, len(moved))
        check('moves old event off primary calendar', any(c[0] == 'delete_event' and c[1].get('eventId') == 'oldcal1' for c in calls))
        await pg.wait_for_timeout(800)
        check('calendar picker offers Shows (not read-only imports)', await pg.locator('#calPick option', has_text='Shows').count() == 1 and await pg.locator('#calPick option', has_text='Songkick').count() == 0)
        check('no uncaught errors (phone)', not errs, errs[:3])

        # ---- deep link ----
        target = events[20]['id']
        pg2, errs2 = await open_page(b, hash='#' + target)
        check('deep link opens the shared show', 'SHARED SHOW' in (await pg2.inner_text('main')).upper() and await pg2.locator(f'article.tix.open[data-id="{target}"]').count() >= 1)

        # ---- first visit: no prefs ----
        pg3, _ = await open_page(b, init='window.__NOPREFS=1')
        await pg3.wait_for_timeout(700)
        check('first visit records last-visit time', 'data/users/u_me/prefs' in await pg3.evaluate('Object.keys(window.__docWrites)'))

        # ---- swipe on a touch phone ----
        pg4, errs4 = await open_page(b, touch=True, ua='Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148')
        cid = await pg4.locator('article.tix:not(:has(.act[aria-pressed="true"]))').first.get_attribute('data-id')
        box = await pg4.locator(f'article[data-id="{cid}"]').first.bounding_box()
        await pg4.evaluate("""([id,x,y])=>{ const c=document.querySelector('article[data-id="'+id+'"]'); const ev=(t,dx)=>c.dispatchEvent(new PointerEvent(t,{bubbles:true,pointerType:'touch',pointerId:7,clientX:x+dx,clientY:y})); ev('pointerdown',0); for (let d=10; d<=140; d+=10) ev('pointermove',d); ev('pointerup',140); }""", [cid, box['x'] + 40, box['y'] + 40])
        await pg4.wait_for_timeout(300)
        check('swipe right marks Interested', await pg4.locator(f'article[data-id="{cid}"] button.act.int').first.get_attribute('aria-pressed') == 'true', await T(pg4))
        hrefs = await pg4.eval_on_selector_all('a.nm-link', 'els=>els.map(a=>a.href)')
        check('phone search links drop /artists', not any(h.endswith('/artists') for h in hrefs))

        # ---- desktop, light ----
        pg5, errs5 = await open_page(b, w=1280, h=900, scheme='light')
        check('desktop shows side panel', await pg5.locator('#side .panel').count() >= 1 and await pg5.locator('#side').is_visible())
        check('side panel lists upcoming saved shows', await pg5.locator('#side .prow').count() >= 2)
        check('header stamp shows refresh summary', '+6 new' in await pg5.inner_text('#stamp'))
        await pg5.click('#stamp'); await pg5.wait_for_timeout(200)
        check('refresh history sheet opens', 'DAILY REFRESH' in (await pg5.inner_text('.sheet')).upper())
        await pg5.locator('.sheet button', has_text='Close').click()
        hrefs = await pg5.eval_on_selector_all('a.nm-link', 'els=>els.map(a=>a.href)')
        check('desktop search links keep /artists', any(h.endswith('/artists') for h in hrefs))
        await pg5.screenshot(path=os.path.join(args.shots, '04_desktop_light.png'))
        await pg5.click('#tab-browse'); await pg5.wait_for_timeout(300)
        check('Browse shows genre chips', await pg5.locator('main .filters .chip').count() > 3)
        await pg5.click('#tab-acts'); await pg5.wait_for_timeout(300)
        await pg5.fill('#actFilter', marked[0]['headliner'][:5]); await pg5.wait_for_timeout(500)
        check('artist filter narrows the music list', 0 < await pg5.locator('.act-row').count() < 15)
        check('no uncaught errors (other views)', not (errs2 or errs4 or errs5), (errs2 + errs4 + errs5)[:3])
        await b.close()
    print(f'\n{sum(results)}/{len(results)} passed')
    sys.exit(0 if all(results) else 1)

asyncio.run(main())
