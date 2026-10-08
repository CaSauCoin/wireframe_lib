#!/usr/bin/env python3
"""Which supplier parts to collect next: JLCPCB's own curated lists, minus what we have.

JLCPCB keeps two short lists out of its seven million: the BASIC library (no
feeder fee — what most boards assembled there are built from) and the
PREFERRED extended parts. Together about 1,600 parts, and they are the
supplier's answer to "what do people actually use", by category, with stock —
a wider and better-founded spread than any list written by hand.

This pages through both (the catalogue search the app's AI_Lcsc_Source uses,
filtered by `componentLibraryType: base` and `preferredComponentFlag: true`),
keeps one row per part number, drops the categories KiCad's generic
footprints already serve (chip resistors, chip capacitors, ferrite beads),
drops what the published library or a previous collection already holds, and
writes `sources/lcsc-parts/to_collect_jlc.txt` for wf-lcsc-collect
(`MPN<TAB>package` a line).

Pages are cached under the library cache (lcsc/catalogue/), so a rerun is free;
requests are spaced, and a refusal stops the run rather than being read as an
empty list.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
import urllib.request
from collections import Counter
from pathlib import Path

import add_ac_packages as common
from libforge import sources

ROOT = common.ROOT
OUT = ROOT / 'sources/lcsc-parts/to_collect_jlc.txt'
KICAD = ROOT / 'sources/lcsc-parts/kicad'
CACHE = sources.LIBRARY_CACHE_DIR / 'lcsc' / 'catalogue'
URL = 'https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList'
LISTS = {'basic': {'componentLibraryType': 'base'}, 'preferred': {'preferredComponentFlag': True}}
# Served by KiCad's generic land patterns; a supplier drawing adds nothing.
SKIP_TOP = {'Resistors', 'Capacitors'}
SKIP_SUB = re.compile(r'Ferrite Bead|Chip Resistor|Resistor Network|MLCC|Tantalum|Aluminum Electrolytic', re.I)


def key(text: str) -> str:
    return re.sub(r'[^a-z0-9]', '', text.lower().rstrip('+'))


def page(list_name: str, number: int, size: int, delay: float) -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f'{list_name}-{size}-{number:03d}.json'
    if path.exists() and time.time() - path.stat().st_mtime < 7 * 86400:
        return json.loads(path.read_text())
    body = json.dumps({'keyword': '', 'currentPage': number, 'pageSize': size, **LISTS[list_name]}).encode()
    request = urllib.request.Request(URL, data=body, headers={
        'Content-Type': 'application/json', 'Accept': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'})
    with urllib.request.urlopen(request, timeout=30) as response:
        text = response.read().decode()
    if text.lstrip().startswith('<'):
        raise SystemExit(f'jlcpcb.com refused page {number} of {list_name} (HTML) — try again later')
    data = json.loads(text)
    path.write_text(text)
    time.sleep(delay)
    return data


def search(keyword: str, size: int, delay: float) -> list[dict]:
    """One catalogue search, cached a week."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"kw-{re.sub(r'[^a-z0-9]+', '_', keyword.lower()).strip('_')}-{size}.json"
    if path.exists() and time.time() - path.stat().st_mtime < 7 * 86400:
        data = json.loads(path.read_text())
    else:
        body = json.dumps({'keyword': keyword, 'currentPage': 1, 'pageSize': size}).encode()
        request = urllib.request.Request(URL, data=body, headers={
            'Content-Type': 'application/json', 'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'})
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode()
        if text.lstrip().startswith('<'):
            raise SystemExit(f'jlcpcb.com refused the search "{keyword}" (HTML) — try again later')
        data = json.loads(text)
        path.write_text(text)
        time.sleep(delay)
    return ((data.get('data') or {}).get('componentPageInfo') or {}).get('list') or []


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--size', type=int, default=100)
    ap.add_argument('--delay', type=float, default=3.0)
    ap.add_argument('--per-category', type=int, default=15,
                    help='at most this many parts of one LCSC subcategory, the most stocked first')
    ap.add_argument('--keywords', type=Path, default=ROOT / 'sources/lcsc-parts/keywords.txt',
                    help='one catalogue search a line; the most stocked real-maker parts of each are added')
    ap.add_argument('--per-keyword', type=int, default=4)
    args = ap.parse_args()

    rows: dict[str, dict] = {}
    for list_name in LISTS:
        first = page(list_name, 1, args.size, args.delay)
        info = (first.get('data') or {}).get('componentPageInfo') or {}
        total = int(info.get('total') or 0)
        pages = (total + args.size - 1) // args.size
        print(f'{list_name}: {total} parts, {pages} page(s)')
        for number in range(1, pages + 1):
            data = first if number == 1 else page(list_name, number, args.size, args.delay)
            for row in ((data.get('data') or {}).get('componentPageInfo') or {}).get('list') or []:
                mpn = row.get('componentModelEn') or ''
                if mpn and key(mpn) not in rows:
                    rows[key(mpn)] = {**row, '_list': list_name}

    if args.keywords and args.keywords.exists():
        words = [w.strip() for w in args.keywords.read_text().splitlines() if w.strip() and not w.startswith('#')]
        added = 0
        for word in words:
            hits = [r for r in search(word, 25, args.delay)
                    if (r.get('componentBrandEn') or '') not in ('', 'JLCPCB Assembly') and (r.get('stockCount') or 0) > 0]
            hits.sort(key=lambda r: -(r.get('stockCount') or 0))
            for row in hits[:args.per_keyword]:
                k = key(row.get('componentModelEn') or '')
                if k and k not in rows:
                    rows[k] = {**row, '_list': 'keyword:' + word}
                    added += 1
        print(f'keywords: {len(words)} searches, {added} more part numbers')

    with sqlite3.connect(ROOT / 'Dist_Repo/v2/lib_search.sqlite') as conn:
        published = {key(n) for (n,) in conn.execute('SELECT name FROM part')}
    collected = {key(json.loads(p.read_text()).get('mpn', '')) for p in KICAD.glob('*.lcsc.json')}

    keep, why = [], Counter()
    for k, row in rows.items():
        top, sub = row.get('secondSortName') or '', row.get('firstSortName') or ''
        if top in SKIP_TOP or SKIP_SUB.search(sub):
            why['generic passive'] += 1
        elif k in published:
            why['already published'] += 1
        elif k in collected:
            why['already collected'] += 1
        elif (row.get('componentBrandEn') or '') == 'JLCPCB Assembly':
            why['assembly placeholder'] += 1
        else:
            keep.append(row)
    keep.sort(key=lambda r: (r.get('secondSortName') or '', r.get('firstSortName') or '', -(r.get('stockCount') or 0)))
    # Variety over volume: the preferred list is hundreds of zener and TVS
    # values on three packages. A few of each subcategory carry the land
    # patterns and the contracts; the rest are one value apart.
    per, capped = Counter(), []
    for r in keep:
        sub = r.get('firstSortName') or '?'
        if per[sub] < args.per_category:
            per[sub] += 1
            capped.append(r)
        else:
            why['over the per-category cap'] += 1
    keep = capped
    OUT.write_text(f'# JLCPCB basic + preferred parts not yet in the library — discover_jlc.py\n'
                   + ''.join(f"{r['componentModelEn']}\t{r.get('componentSpecificationEn') or ''}\n" for r in keep))
    print(f'{len(rows)} distinct part numbers; skipped {dict(why)}; {len(keep)} to collect -> {OUT}')
    for top, n in Counter(r.get('secondSortName') or '?' for r in keep).most_common():
        print(f'  {n:4d}  {top}')


if __name__ == '__main__':
    main()
