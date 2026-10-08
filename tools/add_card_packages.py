#!/usr/bin/env python3
"""Pair every KiCad card-socket land pattern with the card symbol whose contacts it carries.

The library carried five card sockets out of KiCad's twenty, one of them wrong:
`Micro_SD_Card_Det_Hirose_DM3AT` sat on the DM3D land pattern. A microSD
socket the planner names correctly then had nothing to bind to — the E2E run of
2026-10-07 fabricated a 1x9 pin header for one.

Same rule as add_usb_packages.py, whose helpers this uses:

  * the footprint's NAME says which card family it is (microSD with or without
    card-detect, full-size SD, the SD card's own edge, micro/nano SIM);
  * among that family's KiCad symbols, one is taken only if its pin
    designators equal the footprint's pad designators EXACTLY (shield
    included), so every DAT/CMD/CLK/VDD and detect pin lands on its own pad;
  * two symbols with the same pins (`Micro_SD_Card_Det_Hirose_DM3AT` is
    `Micro_SD_Card_Det2` renamed) are told apart by the vendor the symbol is
    named for: the Hirose one goes to the Hirose DM3AT land, the generic one to
    every other;
  * anything else is deferred with the difference spelled out — CompactFlash
    and the microSD+SIM combo have no KiCad symbol, Hirose DM1AA adds CP/SW/WP
    pads, two nanoSIM holders add a switch pad.

3D only from the footprint's own declared model. No network, no upload.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import zipfile
from collections import Counter
from pathlib import Path

import add_ac_packages as common
from add_interface_packages import update_indexes
from add_usb_packages import designators, make_symbol, model_for

ROOT = common.ROOT
SOURCE = ROOT / 'sources/card-packages'
COLLECTION = ROOT / 'collections/cards'
SOURCE_NAME = 'wireframe-card-packages'
LIBRARY = 'Connector_Card'
LICENSE = 'CC-BY-SA-4.0 WITH KiCad-Libraries-exception'

# Footprint-name family -> KiCad symbols it may take.
FAMILIES: list[tuple[str, str, list[str]]] = [
    (r'^microSD_', 'microsd', ['Micro_SD_Card', 'Micro_SD_Card_Det1', 'Micro_SD_Card_Det2',
                               'Micro_SD_Card_Det_Hirose_DM3AT']),
    (r'^SD_Card_Device', 'sd_card_edge', ['SD_Card_Device']),
    (r'^SD_', 'sd', ['SD_Card_Receptacle']),
    (r'SIM', 'sim', ['SIM_Card', 'SIM_Card_Shielded', 'JAE_SIM_Card_SF72S006']),
    (r'^CF-Card', 'compactflash', []),
]
KEYWORDS = {
    'microsd': 'microSD micro-SD TF card socket SDHC SDXC memory card holder',
    'sd': 'SD card socket full-size SDHC memory card holder',
    'sd_card_edge': 'SD card edge device side contacts',
    'sim': 'SIM card holder socket nano-SIM micro-SIM cellular',
}
# A symbol named for one vendor's socket, and the footprints it is for.
VENDOR_SYMBOLS = {'Micro_SD_Card_Det_Hirose_DM3AT': r'Hirose_DM3AT'}


def pair(fp_name: str, pads: set[str], symbols: dict[str, set[str]]) -> tuple[str, str, str]:
    """(family, symbol, '') on an exact match, else (family, '', reason). Pure."""
    family, candidates = next(((f, s) for pat, f, s in FAMILIES if re.search(pat, fp_name)), ('', []))
    if not family:
        return '', '', 'footprint name names no card family'
    exact = [s for s in candidates if s in symbols and symbols[s] == pads]
    if len(exact) > 1:
        named = [s for s in exact if s in VENDOR_SYMBOLS and re.search(VENDOR_SYMBOLS[s], fp_name)]
        exact = named or [s for s in exact if s not in VENDOR_SYMBOLS]
    if len(exact) == 1:
        return family, exact[0], ''
    if len(exact) > 1:
        return family, '', f'ambiguous: {exact} all match'
    present = [s for s in candidates if s in symbols]
    if not present:
        return family, '', 'KiCad has no symbol for this card family'
    closest = min(present, key=lambda s: len(symbols[s] ^ pads))
    extra, missing = sorted(pads - symbols[closest]), sorted(symbols[closest] - pads)
    return family, '', f'closest {closest}: pads without a pin {extra}, pins without a pad {missing}'


def build(repos: Path, out: Path) -> tuple[list, list, dict]:
    symdir = repos / 'kicad-symbols/Connector.kicad_symdir'
    pretty = repos / f'kicad-footprints/{LIBRARY}.pretty'
    packages3d = repos / 'kicad-packages3D'
    wanted = {s for _, _, names in FAMILIES for s in names}
    records = []
    for name in sorted(wanted):
        path = symdir / f'{name}.kicad_sym'
        if path.exists():
            records += common.parse.parse_symbol_file(path, 'Connector')
    base = symdir / 'Micro_SD_Card_Det2.kicad_sym'   # the Hirose symbol extends it
    if base.exists() and 'Micro_SD_Card_Det2' not in wanted:
        records += common.parse.parse_symbol_file(base, 'Connector')
    symbols = {s.name: s for s in common.parse.resolve_extends(records)}
    sym_sets = {n: designators(p.number for p in s.pins) for n, s in symbols.items()}

    parts, deferred, provenance = [], [], []
    for fp_path in sorted(pretty.glob('*.kicad_mod')):
        fp = common.parse.parse_footprint_file(fp_path, LIBRARY)
        pads = designators(fp.all_designators)
        family, symbol, reason = pair(fp.name, pads, sym_sets)
        if reason:
            deferred.append({'footprint': fp.name, 'family': family, 'reason': reason})
            continue
        sym = symbols[symbol]
        name = fp.name
        kicad_desc = sym.properties.get('Description', '').strip().rstrip('.')
        desc = (f'{kicad_desc}; {fp.descr}. Symbol Connector:{symbol} paired by exact '
                f'pin/pad designators ({len(pads)} contacts incl. shield).')
        keywords = ['card', 'connector', family, symbol, *KEYWORDS[family].split(),
                    'smd' if fp.mount == 'smd' else 'tht', fp.name]
        properties = {'Value': name, 'Footprint': f'{LIBRARY}:{fp.name}',
                      'Description': desc, 'ki_keywords': ' '.join(keywords)}
        text = make_symbol(symdir, symbol, name, properties)
        dest_sym = SOURCE / 'symbols' / f'{name}.kicad_sym'
        dest_fp = SOURCE / f'{LIBRARY}.pretty' / fp_path.name
        dest_sym.parent.mkdir(parents=True, exist_ok=True)
        dest_fp.parent.mkdir(parents=True, exist_ok=True)
        dest_sym.write_text(text)
        dest_fp.write_bytes(fp_path.read_bytes())
        model = model_for(fp_path.read_text(), packages3d)
        url = re.search(r'https?://[^\s)",]+', fp.descr)
        r = common.PartRecord(
            id=f'{SOURCE_NAME}/{LIBRARY}/{name}', name=name, source=SOURCE_NAME,
            source_rank=100, library=LIBRARY, license=LICENSE,
            symbol_path=str(dest_sym), footprint_path=str(dest_fp),
            model_path=str(model) if model else '',
            model_format=model.suffix.lstrip('.') if model else '',
            model_origin='kicad-packages3D' if model else '',
            model_method='declared_by_footprint' if model else '',
            description=desc, description_origin='rules', keywords=keywords,
            datasheet=url[0] if url else sym.properties.get('Datasheet', ''),
            reference='J', value=name, pin_count=fp.pad_count,
            named_pins=sum(p.name not in {'', '~'} for p in sym.pins),
            pins=[{'number': p.number, 'name': p.name, 'type': p.electrical_type, 'unit': p.unit}
                  for p in sym.pins],
            footprint_name=fp.name, footprint_library=LIBRARY, pad_count=fp.pad_count,
            mount=fp.mount, pitch_mm=fp.pitch_mm, courtyard_mm=fp.courtyard, body_mm=fp.body,
            footprint_descr=fp.descr, footprint_tags=fp.tags, footprint_method='explicit_generic',
            tier='A', score=90, flags=['kicad_card_symbol_paired_by_designators'],
            named_pin_ratio=1.0)
        parts.append(common.EnrichedPart(r, 'connector.card', ['Connector', 'Card'],
                                         desc + ' ' + ' '.join(keywords), [], []))
        provenance.append({
            'id': r.id, 'family': family, 'symbol': f'kicad-symbols/Connector.kicad_symdir/{symbol}.kicad_sym',
            'footprint': f'kicad-footprints/{LIBRARY}.pretty/{fp_path.name}',
            'model': str(model.relative_to(packages3d)) if model else '',
            'source_footprint_sha256': hashlib.sha256(fp_path.read_bytes()).hexdigest(),
            'generated_symbol_sha256': hashlib.sha256(text.encode()).hexdigest()})

    images, _ = common.preview.render(parts, out, workers=4, progress=print)
    missing = [p.record.name for p in parts
               if not all(images.get(common.package.part_slug(p), {}).get(k) for k in ('sym', 'fp'))]
    if missing:
        raise ValueError(f'missing previews: {missing[:5]}')
    common.package.write_part_zips(parts, out, include_3d=True, previews=images, progress=print)
    for p in parts:
        with zipfile.ZipFile(out / 'parts' / (common.package.part_slug(p) + '.zip')) as z:
            error = common.validate(z, json.loads(z.read('part.json')))
            if error:
                raise ValueError(f'{p.record.name}: {error}')
    commits = {n: subprocess.check_output(['git', '-C', str(repos / n), 'rev-parse', 'HEAD'], text=True).strip()
               for n in ('kicad-symbols', 'kicad-footprints', 'kicad-packages3D')}
    (SOURCE / 'PROVENANCE.json').write_text(json.dumps({
        'schema': 1, 'license': LICENSE, 'upstream_commits': commits,
        'policy': 'KiCad card symbols bound to KiCad Connector_Card footprints only when pin and pad '
                  'designators are identical; 3D only from the footprint\'s declared model.',
        'parts': provenance, 'deferred': deferred}, indent=2) + '\n')
    return parts, deferred, {p.record.id: images.get(common.package.part_slug(p), {}) for p in parts}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--repos', type=Path, default=Path.home() / '.wireframe/library_cache/repos')
    ap.add_argument('--out', type=Path, default=ROOT / 'Dist_Repo/v2')
    ap.add_argument('--plan', action='store_true', help='print the pairings; write nothing')
    args = ap.parse_args()
    out = args.out

    if args.plan:
        symdir = args.repos / 'kicad-symbols/Connector.kicad_symdir'
        records = []
        for name in {s for _, _, names in FAMILIES for s in names} | {'Micro_SD_Card_Det2'}:
            if (symdir / f'{name}.kicad_sym').exists():
                records += common.parse.parse_symbol_file(symdir / f'{name}.kicad_sym', 'Connector')
        sets = {s.name: designators(p.number for p in s.pins) for s in common.parse.resolve_extends(records)}
        for fp_path in sorted((args.repos / f'kicad-footprints/{LIBRARY}.pretty').glob('*.kicad_mod')):
            fp = common.parse.parse_footprint_file(fp_path, LIBRARY)
            family, symbol, reason = pair(fp.name, designators(fp.all_designators), sets)
            print(f'{fp.name:44s} {family:13s} {symbol or "-":32s} {reason}')
        return

    manifest = json.loads((out / 'lib_index.json').read_text())
    base, parts_base = manifest['base_url'], manifest['parts_base_url']
    entries = {e['id']: e for f in sorted((out / 'shards').glob('*.json'))
               for e in json.loads(f.read_text())['entries']}
    before = len(entries)

    parts, deferred, images = build(args.repos, out)
    added = []
    for p in parts:
        slug = common.package.part_slug(p)
        path = out / 'parts' / f'{slug}.zip'
        with zipfile.ZipFile(path) as z:
            m = json.loads(z.read('part.json'))
            models = {slug} if (m.get('model3d') or {}).get('file') in z.namelist() else set()
        entry = common.package.index_entry(p, base, slug, hashlib.sha256(path.read_bytes()).hexdigest(),
                                           dict(images[p.record.id]), parts_base, models)
        if p.record.id not in entries:
            added.append(entry)
        entries[p.record.id] = entry

    # A card symbol already in the library on a land pattern this pass binds
    # exactly — KiCad's own Micro_SD_Card_Det_Hirose_DM3AT on the DM3D land —
    # stays downloadable and leaves the planner when its pairing is not the
    # exact one: two rows for one socket is how the wrong one gets picked.
    exact = {(p.record.footprint_name, re.sub(r'^.*Symbol Connector:(\S+) .*$', r'\1', p.record.description))
             for p in parts}
    by_fp = {p.record.footprint_name: p.record.id for p in parts}
    superseded = []
    for e in entries.values():
        if e.get('source') == SOURCE_NAME or e.get('footprint') not in by_fp:
            continue
        if not e.get('class', '').startswith('connector'):
            continue
        if (e['footprint'], e.get('name')) not in exact:
            e['tier'] = 'C'
            e['superseded_by'] = by_fp[e['footprint']]
            superseded.append(e['id'])

    update_indexes(out, entries, manifest, added)
    manifest = json.loads((out / 'lib_index.json').read_text())
    if not any(s['name'] == SOURCE_NAME for s in manifest['sources']):
        manifest['sources'].append({'name': SOURCE_NAME, 'license': LICENSE,
            'url': 'https://github.com/CaSauCoin/wireframe_lib/tree/main/sources/card-packages',
            'rank': 100, 'commit': '', 'provenance': 'sources/card-packages/PROVENANCE.json'})
        (out / 'lib_index.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        with (out / 'LICENSES.md').open('a') as f:
            f.write('\n## WireFrame card socket packages\n\nKiCad `Connector` microSD, SD and SIM symbols bound '
                    'to unmodified KiCad `Connector_Card` footprints by identical pin/pad designators; 3D models '
                    'from kicad-packages3D where the footprint declares one. CC-BY-SA-4.0 WITH '
                    'KiCad-Libraries-exception; see sources/card-packages/PROVENANCE.json.\n')

    COLLECTION.mkdir(parents=True, exist_ok=True)
    fams = {p['id']: p['family'] for p in json.loads((SOURCE / 'PROVENANCE.json').read_text())['parts']}
    report = {'schema': 1, 'before': before, 'after': len(entries), 'added': len(added),
              'paired': len(parts), 'with_3d': sum(bool(p.record.model_path) for p in parts),
              'by_family': dict(Counter(fams.values())), 'superseded': superseded, 'deferred': deferred}
    (COLLECTION / 'catalog.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ('before', 'after', 'added', 'paired', 'with_3d', 'by_family')},
                     indent=2))
    print('Deferred:', len(deferred), '| superseded:', superseded)
    for d in deferred:
        print('  -', d['footprint'], '->', d['reason'])


if __name__ == '__main__':
    main()
