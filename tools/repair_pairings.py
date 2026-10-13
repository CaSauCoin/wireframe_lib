#!/usr/bin/env python3
"""Re-pair the published parts whose symbol pins have no pad, with libforge's corrected rule.

libforge chose a land pattern by COUNT: enough pads, fewest first. It never
asked whether the pads carry the symbol's pin NUMBERS. Measured on the library
of 2026-10-13 (`tools/audit_parts.py`):

  * 190 `Conn_02xNN_Row_Letter_*` connectors (pins a1..bN) on headers, FFC and
    Micro-Fit lands numbered 1..2N — equal counts, not one pin on copper;
  * 13 74xx parts on DIP-12/DIP-10: they draw 12 pins numbered up to 14 (two
    NC pins left out), so VCC (14) had no pad;
  * 74xx1G06 (5 pins) on a 3-lead SOT-89 whose tab overlaps pin 2;
  * 4-pin crystals on 2-pad lands, tantalums numbered +/- on pads 1/2, barrel
    jacks numbered GND/PWR on pads 1..3, ISL83491 on SOIC-16W-12 …

The rule is fixed in libforge (`pair.FootprintCatalog._best`, `quality.
pairing_is_credible`, `quality.assess`'s `pins_without_pads`). This tool runs
that same code over the parts already published, and rebuilds a part only when
the answer changes:

  * an INFERRED pairing (fp_filter / name_key / declared_name) the new rule
    refuses: it gets the land the new rule picks (DIP-14, SOT-23-5 …) — or none,
    and then the tier libforge gives a part without one (G when the package is
    the designer's to choose and the symbol says which family, C otherwise);
  * a DECLARED pairing with a pin no pad carries (upstream's own defect: EA
    eDIP320's pin 78, TSC2007's D1-D3, Pulse PA2002NL's pin 8): tier C, flag
    `pins_without_pads` — still published and installable, no longer offered
    to the planner;
  * `--overlap ID…`: a land whose differently-numbered pads short (measured by
    audit_parts.py `pads_short`): tier C, flag `pads_overlap`.

The current description, keywords, datasheet and class are kept; only the
footprint, its 3D model, the tier and the flags follow the new pairing.
Every change is recorded in collections/repairs/pairings.json with what was
measured before and after.

    python3 tools/repair_pairings.py --plan
    python3 tools/repair_pairings.py --overlap ID ...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from collections import Counter
from pathlib import Path

import add_ac_packages as common
import add_lcsc_parts as lcsc
from libforge import build, classify, enrich, pair, parse, quality, sources

ROOT = common.ROOT
OUT = ROOT / 'Dist_Repo/v2'
RECORD = ROOT / 'collections/repairs/pairings.json'
INFERRED = {'fp_filter', 'name_key', 'declared_name'}


def zip_pair(path: Path, name: str):
    """The symbol and footprint as the zip ships them, read by libforge."""
    with zipfile.ZipFile(path) as z:
        m = json.loads(z.read('part.json'))
        names = z.namelist()
        sym_file = next((n for n in names if n.endswith('.kicad_sym')), '')
        fp_file = next((n for n in names if n.endswith('.kicad_mod')), '')
        symbols = parse.resolve_extends(parse.parse_symbol_text(z.read(sym_file).decode('utf-8', 'replace'))) \
            if sym_file else []
        fp = parse.parse_footprint_text(z.read(fp_file).decode('utf-8', 'replace')) if fp_file else None
    bare = build.bare_name(name)
    sym = next((s for s in symbols if build.bare_name(s.name) == bare), symbols[0] if symbols else None)
    return m, sym, fp


def verdict(sym, fp, method: str) -> str:
    """Why the shipped pairing is wrong, or '' if it is not."""
    if sym is None or fp is None or not fp.pad_count:
        return ''
    missing = sorted(sym.electrical_numbers - set(fp.all_designators))
    if method in INFERRED:
        if not quality.pairing_is_credible(sym, pair.FootprintMatch(fp, method, True)):
            return (f'pins {missing[:8]} have no pad' if missing else
                    f'{len(sym.electrical_numbers)} pins on {fp.pad_count} pads')
        return ''
    return f'pins {missing[:8]} have no pad (declared by upstream)' if missing else ''


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--plan', action='store_true', help='print what would change; write nothing')
    ap.add_argument('--overlap', nargs='*', default=[], metavar='ID',
                    help='part ids whose land shorts two pads (from audit_parts.py pads_short): tier C')
    args = ap.parse_args()

    manifest = json.loads((OUT / 'lib_index.json').read_text())
    entries, shard_of = {}, {}
    for f in sorted((OUT / 'shards').glob('*.json')):
        for e in json.loads(f.read_text())['entries']:
            entries[e['id']] = e
            shard_of[e['id']] = f.stem

    by_source = {s.name: s for s in sources.default_sources()}
    wrong: dict[str, dict] = {}
    for e in entries.values():
        if e.get('source') not in by_source:
            continue
        path = OUT / 'parts' / f"{e['slug']}.zip"
        if not path.exists():
            continue
        m, sym, fp = zip_pair(path, e['name'])
        fpm = m.get('footprint')
        method = fpm.get('resolved_by', '') if isinstance(fpm, dict) else ''
        why = verdict(sym, fp, method)
        if why or e['id'] in args.overlap:
            wrong[e['id']] = {'method': method, 'footprint': (fp.name if fp else ''), 'why': why or 'pads overlap',
                              'symbol_path': (m.get('source') or {}).get('symbol_path', '')
                              if isinstance(m.get('source'), dict) else ''}
    print(f'{len(wrong)} published parts whose pairing the corrected rule refuses: '
          f'{dict(Counter(w["method"] for w in wrong.values()))}')

    # The same catalogue libforge builds: every tree source's land patterns and
    # every packages3D model, so a symbol may land where a build would land it.
    say = print
    footprints, models = [], pair.ModelCatalog()
    for source in by_source.values():
        if not source.exists:
            continue
        if source.kind == 'packages3d':
            for filename, model in sources.iter_models(source):
                models.add(filename, model)
        elif source.kind == 'tree':
            footprints.extend(sources.iter_footprints(source))
    catalog = pair.FootprintCatalog(footprints)
    say(f'catalogue: {len(catalog)} footprints, {len(models)} models')

    wanted = Counter(i.split('/')[0] for i in wrong)
    rebuilt, record = [], []
    for source_name in wanted:
        source = by_source[source_name]
        for symbol in sources.iter_symbols(source):
            part_id = f'{source.name}/{symbol.library}/{build.bare_name(symbol.name)}'
            if part_id not in wrong:
                continue
            e = entries[part_id]
            match = catalog.resolve(symbol)
            model = models.resolve(match.footprint) if match else None
            r = build._make_record(symbol, source, match, model)
            if part_id in args.overlap and r.footprint_name == wrong[part_id]['footprint']:
                r.tier, r.flags = 'C', sorted(set(r.flags) | {'pads_overlap'})
                r.score = max(0, r.score - 45)
            # curation stays; the package, the tier and the flags follow the pairing
            r.description, r.keywords, r.datasheet = e.get('description', r.description), \
                e.get('keywords', r.keywords), e.get('datasheet', r.datasheet)
            r.description_origin = 'upstream' if r.description else r.description_origin
            record.append({'id': part_id, 'why': wrong[part_id]['why'],
                           'before': {'footprint': wrong[part_id]['footprint'], 'method': wrong[part_id]['method'],
                                      'tier': e.get('tier')},
                           'after': {'footprint': r.footprint_name, 'method': r.footprint_method, 'tier': r.tier,
                                     'flags': [f for f in r.flags if f in {'pins_without_pads', 'pairing_rejected',
                                                                         'pads_overlap', 'pad_shortfall'}]}})
            rebuilt.append((r, e))
    missing = set(wrong) - {r.id for r, _ in rebuilt}
    if missing:
        print(f'{len(missing)} could not be re-read from their source (left as they are): {sorted(missing)[:5]}')
    outcome = Counter((x['after']['footprint'] != x['before']['footprint'], x['after']['tier']) for x in record)
    print('rebuilt:', {f'{"new land" if k[0] else "same land"} tier {k[1]}': v for k, v in outcome.items()})
    for x in record[:60]:
        print(f"  {x['id'][:62]:62s} {x['before']['footprint'][:34]:34s} -> {x['after']['footprint'][:34] or '(none)':34s} "
              f"{x['before']['tier']}->{x['after']['tier']}  {x['why'][:40]}")
    if args.plan or not rebuilt:
        return

    parts = enrich.enrich([r for r, _ in rebuilt], use_ai=False)
    for p, (_, e) in zip(parts, rebuilt):
        p.klass = e.get('class') or p.klass
        p.category_path = classify.category_path(p.klass)
    # The renderer keeps an image that already exists; these show the old land.
    stale = ROOT / 'collections/repairs/stale_previews'
    stale.mkdir(parents=True, exist_ok=True)
    for p in parts:
        slug = common.package.part_slug(p)
        for kind in ('fp', 'sym'):
            img = OUT / 'previews' / f'{slug}_{kind}.png'
            if img.exists():
                shutil.move(img, stale / img.name)
    images, _ = common.preview.render(parts, OUT, workers=6, progress=print)
    common.package.write_part_zips(parts, OUT, include_3d=True, previews=images, progress=print)
    touched = set()
    for p in parts:
        slug = common.package.part_slug(p)
        archive = OUT / 'parts' / f'{slug}.zip'
        with zipfile.ZipFile(archive) as z:
            mm = json.loads(z.read('part.json'))
            has_model = {slug} if (mm.get('model3d') or {}).get('file') in z.namelist() else set()
        old = entries[p.record.id]
        new = common.package.index_entry(p, manifest['base_url'], slug,
                                         hashlib.sha256(archive.read_bytes()).hexdigest(),
                                         images.get(slug, {}), manifest['parts_base_url'], has_model)
        for keep in ('bundle_url', 'bundle_path'):
            if keep in old and keep not in new:
                new[keep] = old[keep]
        entries[p.record.id] = new
        touched.add(shard_of[p.record.id])
    lcsc.update_indexes(OUT, entries, manifest, touched, shard_of)
    RECORD.parent.mkdir(parents=True, exist_ok=True)
    previous = json.loads(RECORD.read_text())['repairs'] if RECORD.exists() else []
    done = {x['id'] for x in record}
    RECORD.write_text(json.dumps({'schema': 1, 'rule': 'libforge pairing by pin NUMBER (pair._best, '
                                  'quality.pairing_is_credible, quality.assess pins_without_pads)',
                                  'repairs': [x for x in previous if x['id'] not in done] + record},
                                 ensure_ascii=False, indent=1) + '\n')
    shutil.rmtree(stale, ignore_errors=True)
    print(f'rebuilt {len(parts)} parts; record in {RECORD.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
