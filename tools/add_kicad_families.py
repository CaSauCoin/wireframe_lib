#!/usr/bin/env python3
"""Pair KiCad's mechanical, switch, audio, power-entry and wire-pad land patterns with the symbol each one carries.

The library held 9 mounting holes, no fiducial, one DIP switch, no SMT
standoff, no battery holder, no audio jack worth the name — while KiCad ships
exact land patterns for all of them, most named for the vendor part they were
drawn from (Würth WA-SMSI 9774050360, Keystone 3002, E-Switch TL3342, CUI
SJ-3523). No supplier sells "a mounting hole", so for these KiCad's libraries
are the reference, not one source among many.

Same rule as add_usb_packages.py and add_card_packages.py:

  * the footprint library and name say which family it is;
  * a family's KiCad symbol is taken only if its pin designators equal the
    footprint's pad designators EXACTLY — every pin on its own pad, every
    numbered pad on a pin (a mounting hole with no numbered pad takes
    `MountingHole`, one with pad 1 takes `MountingHole_Pad`);
  * two symbols with the same pins (SolderJumper_2_Open / _Bridged, Buzzer /
    Speaker) are told apart by the words of the footprint's name;
  * anything else is deferred with the difference spelled out;
  * a land pattern a library part already sits on is left to it.

Unmodified KiCad footprints; 3D only from the footprint's own declared model.
No network, no upload. `--plan` prints the pairings and writes nothing.
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
import add_lcsc_parts as lcsc
from add_usb_packages import designators, make_symbol, model_for

ROOT = common.ROOT
SOURCE = ROOT / 'sources/kicad-families'
COLLECTION = ROOT / 'collections/kicad-families'
SOURCE_NAME = 'wireframe-kicad-families'
LICENSE = 'CC-BY-SA-4.0 WITH KiCad-Libraries-exception'

DIP = [f'SW_DIP_x{n:02d}' for n in range(1, 13)]
AUDIO = ['AudioJack2', 'AudioJack2_Ground', 'AudioJack2_Switch', 'AudioJack2_SwitchT', 'AudioJack2_Ground_Switch',
         'AudioJack2_Ground_SwitchT', 'AudioJack2_Dual_Switch', 'AudioJack2_Dual_Ground_Switch', 'AudioJack3',
         'AudioJack3_Ground', 'AudioJack3_Switch', 'AudioJack3_SwitchT', 'AudioJack3_SwitchTR',
         'AudioJack3_Ground_Switch', 'AudioJack3_Ground_SwitchTR', 'AudioJack3_Dual_Switch',
         'AudioJack3_Dual_Ground_Switch', 'AudioJack4', 'AudioJack4_Ground', 'AudioJack4_SwitchT1',
         'AudioJack4_SwitchTR1', 'AudioJack4_Ground_SwitchTR1', 'AudioJack5', 'AudioJack5_Ground']
SWITCH = ['SW_Push', 'SW_Push_Dual', 'SW_Push_45deg', 'SW_Push_Shielded', 'SW_Push_SPDT', 'SW_Push_DPDT',
          'SW_SPDT', 'SW_Slide_DPDT', 'SW_Push_LED']

# (footprint library, footprint-name regex, symbol library, candidate symbols,
#  class, reference, keywords)
FAMILIES: list[tuple[str, str, str, list[str], str, str, str]] = [
    ('MountingHole', r'', 'Mechanical', ['MountingHole', 'MountingHole_Pad', 'MountingHole_Pad_MP'],
     'mechanical.mounting_hole', 'H', 'mounting hole screw hole M2 M2.5 M3 M4 lỗ ốc lỗ bắt vít'),
    ('Mounting_Wuerth', r'', 'Mechanical', ['MountingHole_Pad', 'MountingHole', 'MountingHole_Pad_MP'],
     'mechanical.standoff', 'H', 'SMT standoff spacer threaded nut Wuerth WA-SMSI WA-SMST trụ đồng'),
    ('Fiducial', r'', 'Mechanical', ['Fiducial'], 'mechanical.fiducial', 'FID', 'fiducial marker pick and place'),
    ('TestPoint', r'', 'Connector', ['TestPoint', 'TestPoint_2Pole'], 'mechanical.testpoint', 'TP',
     'test point probe điểm đo'),
    ('NetTie', r'', 'Device', ['NetTie_2', 'NetTie_3', 'NetTie_4', 'NetTie_3_Tee', 'NetTie_4_Cross'],
     'mechanical.net_tie', 'NT', 'net tie star ground'),
    ('Jumper', r'^SolderJumper', 'Jumper', ['SolderJumper_2_Open', 'SolderJumper_2_Bridged', 'SolderJumper_3_Open',
                                             'SolderJumper_3_Bridged12', 'SolderJumper_3_Bridged123'],
     'mechanical.jumper', 'JP', 'solder jumper bridge'),
    ('Heatsink', r'', 'Mechanical', ['Heatsink', 'Heatsink_Pad', 'Heatsink_Pad_2Pin', 'Heatsink_Pad_3Pin'],
     'mechanical.heatsink', 'HS', 'heatsink tản nhiệt'),
    ('Battery', r'', 'Device', ['Battery_Cell', 'Battery'], 'power.battery', 'BT',
     'battery holder coin cell CR2032 AA AAA 18650 đế pin'),
    ('Buzzer_Beeper', r'', 'Device', ['Buzzer', 'Speaker'], 'electromechanical.buzzer', 'BZ',
     'buzzer beeper magnetic piezo còi'),
    ('Button_Switch_SMD', r'^SW_DIP', 'Switch', DIP, 'electromechanical.switch', 'SW', 'DIP switch SMD công tắc gạt DIP'),
    ('Button_Switch_THT', r'^SW_DIP', 'Switch', DIP, 'electromechanical.switch', 'SW', 'DIP switch THT công tắc gạt DIP'),
    ('Button_Switch_SMD', r'', 'Switch', SWITCH, 'electromechanical.switch', 'SW',
     'tactile push button switch SMD nút nhấn'),
    ('Button_Switch_THT', r'', 'Switch', SWITCH, 'electromechanical.switch', 'SW',
     'tactile push button switch THT nút nhấn'),
    ('Connector_Audio', r'^Jack_3\.5|^Jack_2\.5|^Jack_6\.35', 'Connector_Audio', AUDIO, 'connector.audio', 'J',
     'audio jack 3.5mm 2.5mm 6.35mm TRS TRRS headphone'),
    ('Connector_BarrelJack', r'', 'Connector', ['Barrel_Jack', 'Barrel_Jack_Switch', 'Barrel_Jack_MountingPin',
                                                 'Barrel_Jack_Switch_MountingPin', 'Barrel_Jack_Switch_Pin3Ring'],
     'connector.power', 'J', 'DC barrel jack power input cổng sạc'),
    ('Connector_Wire', r'_1x0[12]_|^SolderWirePad_1x01', 'Connector_Generic', ['Conn_01x01', 'Conn_01x02'],
     'connector.wire', 'J', 'solder wire pad wire joint mối nối dây hàn'),
]
# A symbol two families share and the words that say it is meant.
PREFER = {'Battery': r'_[2-9]x', 'Speaker': r'Speaker', 'SolderJumper_2_Bridged': r'Bridged',
          'SolderJumper_3_Bridged12': r'Bridged12', 'SolderJumper_3_Bridged123': r'Bridged123',
          'SolderJumper_2_Open': r'Open', 'SolderJumper_3_Open': r'Open'}


def pick(fp_name: str, pads: set[str], candidates: list[str], symbols: dict[str, set[str]]) -> tuple[str, str]:
    """(symbol, '') on an exact match, else ('', reason). Pure."""
    exact = [s for s in candidates if s in symbols and symbols[s] == pads]
    if len(exact) > 1:
        named = [s for s in exact if s in PREFER and re.search(PREFER[s], fp_name, re.I)]
        if len(named) > 1:   # Bridged123 also says Bridged
            named = sorted(named, key=lambda s: -len(PREFER[s]))[:1]
        exact = named or [s for s in exact if s not in PREFER] or exact[:1]
    if exact:
        return exact[0], ''
    present = [s for s in candidates if s in symbols]
    if not present:
        return '', 'KiCad has no symbol for this family'
    closest = min(present, key=lambda s: len(symbols[s] ^ pads))
    return '', (f'closest {closest}: pads without a pin {sorted(pads - symbols[closest])[:6]}, '
                f'pins without a pad {sorted(symbols[closest] - pads)[:6]}')


def symbols_of(repos: Path, lib: str, names: list[str]) -> tuple[Path, dict]:
    symdir = repos / f'kicad-symbols/{lib}.kicad_symdir'
    records = []
    for name in names:
        path = symdir / f'{name}.kicad_sym'
        if path.exists():
            text = path.read_text()
            base = re.search(r'\(extends\s+"([^"]+)"\)', text)
            if base and (symdir / f'{base[1]}.kicad_sym').exists():
                records += common.parse.parse_symbol_file(symdir / f'{base[1]}.kicad_sym', lib)
            records += common.parse.parse_symbol_file(path, lib)
    symbols = {s.name: s for s in common.parse.resolve_extends(records)}
    return symdir, {n: s for n, s in symbols.items() if n in names}


def plan(repos: Path, taken: set[str]) -> tuple[list, list]:
    """Every footprint of every family: (family index, footprint, symbol) or deferred."""
    pairs, deferred, seen = [], [], set()
    for index, (fp_lib, pattern, sym_lib, candidates, *_rest) in enumerate(FAMILIES):
        symdir, symbols = symbols_of(repos, sym_lib, candidates)
        sets = {n: designators(p.number for p in s.pins) for n, s in symbols.items()}
        for fp_path in sorted((repos / f'kicad-footprints/{fp_lib}.pretty').glob('*.kicad_mod')):
            name = fp_path.stem
            if name in seen or (pattern and not re.search(pattern, name)):
                continue
            seen.add(name)
            if name in taken:
                continue
            fp = common.parse.parse_footprint_file(fp_path, fp_lib)
            symbol, reason = pick(name, designators(fp.all_designators), candidates, sets)
            if reason:
                deferred.append({'footprint': f'{fp_lib}:{name}', 'reason': reason})
            else:
                pairs.append((index, fp_path, fp, symdir, symbols[symbol]))
    return pairs, deferred


def build(repos: Path, out: Path, pairs: list) -> tuple[list, dict, list]:
    packages3d = repos / 'kicad-packages3D'
    parts, provenance = [], []
    for index, fp_path, fp, symdir, sym in pairs:
        fp_lib, _, sym_lib, _, klass, ref, words = FAMILIES[index]
        name = fp.name
        kicad_desc = sym.properties.get('Description', '').strip().rstrip('.')
        desc = (f'{fp.descr.strip().rstrip(".") or kicad_desc}. Symbol {sym_lib}:{sym.name} on KiCad\'s '
                f'{fp_lib}:{name}, paired by exact pin/pad designators.')
        keywords = sorted({*words.split(), sym.name, fp_lib, *(fp.tags.split() if fp.tags else []),
                           'smd' if fp.mount == 'smd' else 'tht'})
        properties = {'Value': name, 'Footprint': f'{fp_lib}:{name}', 'Description': desc,
                      'ki_keywords': ' '.join(keywords), 'Reference': ref}
        try:
            text = make_symbol(symdir, sym.name, name, properties)
        except ValueError as error:
            print('  skipped', name, error)
            continue
        dest_sym = SOURCE / 'symbols' / f'{name}.kicad_sym'
        dest_fp = SOURCE / f'{fp_lib}.pretty' / fp_path.name
        dest_sym.parent.mkdir(parents=True, exist_ok=True)
        dest_fp.parent.mkdir(parents=True, exist_ok=True)
        dest_sym.write_text(text)
        dest_fp.write_bytes(fp_path.read_bytes())
        model = model_for(fp_path.read_text(), packages3d)
        url = re.search(r'https?://[^\s)",]+', fp.descr or '')
        r = common.PartRecord(
            id=f'{SOURCE_NAME}/{fp_lib}/{name}', name=name, source=SOURCE_NAME,
            source_rank=100, library=fp_lib, license=LICENSE,
            symbol_path=str(dest_sym), footprint_path=str(dest_fp),
            model_path=str(model) if model else '', model_format=model.suffix.lstrip('.') if model else '',
            model_origin='kicad-packages3D' if model else '', model_method='declared_by_footprint' if model else '',
            description=desc, description_origin='rules', keywords=keywords,
            datasheet=url[0] if url else sym.properties.get('Datasheet', ''),
            reference=ref, value=name, pin_count=fp.pad_count,
            named_pins=sum(p.name not in {'', '~'} for p in sym.pins),
            pins=[{'number': p.number, 'name': p.name, 'type': p.electrical_type, 'unit': p.unit} for p in sym.pins],
            footprint_name=name, footprint_library=fp_lib, pad_count=fp.pad_count,
            mount=fp.mount, pitch_mm=fp.pitch_mm, courtyard_mm=fp.courtyard, body_mm=fp.body,
            footprint_descr=fp.descr, footprint_tags=fp.tags, footprint_method='explicit_generic',
            tier='A', score=90, flags=['kicad_symbol_paired_by_designators'], named_pin_ratio=1.0)
        root = klass.split('.')[0]
        parts.append(common.EnrichedPart(r, klass, [root.capitalize(), *klass.split('.')[1:]],
                                         desc + ' ' + ' '.join(keywords), [], []))
        provenance.append({'id': r.id, 'symbol': f'kicad-symbols/{sym_lib}.kicad_symdir/{sym.name}.kicad_sym',
                           'footprint': f'kicad-footprints/{fp_lib}.pretty/{fp_path.name}',
                           'model': str(model.relative_to(packages3d)) if model else '',
                           'source_footprint_sha256': hashlib.sha256(fp_path.read_bytes()).hexdigest(),
                           'generated_symbol_sha256': hashlib.sha256(text.encode()).hexdigest()})

    images, _ = common.preview.render(parts, out, workers=6, progress=print)
    missing = [p.record.name for p in parts
               if not all(images.get(common.package.part_slug(p), {}).get(k) for k in ('sym', 'fp'))]
    if missing:
        raise SystemExit(f'previews missing for {len(missing)}: {missing[:5]}; nothing was indexed')
    common.package.write_part_zips(parts, out, include_3d=True, previews=images, progress=print)
    for p in parts:
        with zipfile.ZipFile(out / 'parts' / (common.package.part_slug(p) + '.zip')) as z:
            error = common.validate(z, json.loads(z.read('part.json')), allow_pinless=True)
            if error:
                raise SystemExit(f'{p.record.name}: {error}')
    return parts, images, provenance


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--repos', type=Path, default=Path.home() / '.wireframe/library_cache/repos')
    ap.add_argument('--out', type=Path, default=ROOT / 'Dist_Repo/v2')
    ap.add_argument('--plan', action='store_true', help='print the pairings; write nothing')
    args = ap.parse_args()
    out = args.out
    manifest = json.loads((out / 'lib_index.json').read_text())
    entries, shard_of = {}, {}
    for f in sorted((out / 'shards').glob('*.json')):
        for e in json.loads(f.read_text())['entries']:
            entries[e['id']] = e
            shard_of[e['id']] = f.stem
    # A land pattern a part of the library already sits on stays with it —
    # unless that part is one of ours, which a rerun rebuilds.
    taken = {e.get('footprint') for e in entries.values() if e.get('source') != SOURCE_NAME}

    pairs, deferred = plan(args.repos, taken)
    by_family = Counter(FAMILIES[i][4] for i, *_ in pairs)
    print(f'{len(pairs)} paired, {len(deferred)} deferred: {dict(by_family)}')
    if args.plan:
        for i, fp_path, fp, _, sym in pairs[:400]:
            print(f'  {FAMILIES[i][0]:20s} {fp.name[:60]:60s} {sym.name}')
        for d in deferred[:60]:
            print('  ~', d['footprint'][:70], '->', d['reason'][:90])
        return

    parts, images, provenance = build(args.repos, out, pairs)
    before = len(entries)
    touched = set()
    for p in parts:
        slug = common.package.part_slug(p)
        path = out / 'parts' / f'{slug}.zip'
        with zipfile.ZipFile(path) as z:
            m = json.loads(z.read('part.json'))
            models = {slug} if (m.get('model3d') or {}).get('file') in z.namelist() else set()
        entries[p.record.id] = common.package.index_entry(p, manifest['base_url'], slug,
                                                          hashlib.sha256(path.read_bytes()).hexdigest(),
                                                          dict(images.get(slug, {})), manifest['parts_base_url'],
                                                          models)
        shard_of[p.record.id] = p.klass.split('.')[0]
        touched.add(shard_of[p.record.id])
    meant = len(entries)
    lcsc.update_indexes(out, entries, manifest, touched, shard_of)
    written = sum(len(json.loads(f.read_text())['entries']) for f in (out / 'shards').glob('*.json'))
    if written != meant:
        raise SystemExit(f'the shards hold {written} entries where {meant} were meant')
    print('contracts:', lcsc.add_contracts(out, parts, None))

    manifest = json.loads((out / 'lib_index.json').read_text())
    if not any(s['name'] == SOURCE_NAME for s in manifest['sources']):
        manifest['sources'].append({'name': SOURCE_NAME, 'license': LICENSE,
                                    'url': 'https://github.com/CaSauCoin/wireframe_lib/tree/main/sources/kicad-families',
                                    'rank': 100, 'commit': '', 'provenance': 'sources/kicad-families/PROVENANCE.json'})
        (out / 'lib_index.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        with (out / 'LICENSES.md').open('a') as f:
            f.write('\n## WireFrame KiCad families\n\nKiCad mechanical, switch, audio, power-entry, battery, buzzer '
                    'and wire-pad symbols bound to unmodified KiCad footprints by identical pin/pad designators; 3D '
                    'from kicad-packages3D where the footprint declares one. CC-BY-SA-4.0 WITH '
                    'KiCad-Libraries-exception; see sources/kicad-families/PROVENANCE.json.\n')
    commits = {n: subprocess.check_output(['git', '-C', str(args.repos / n), 'rev-parse', 'HEAD'], text=True).strip()
               for n in ('kicad-symbols', 'kicad-footprints', 'kicad-packages3D')}
    SOURCE.mkdir(parents=True, exist_ok=True)
    (SOURCE / 'PROVENANCE.json').write_text(json.dumps({
        'schema': 1, 'license': LICENSE, 'upstream_commits': commits,
        'policy': 'KiCad symbols bound to KiCad footprints only when pin and pad designators are identical; '
                  '3D only from the footprint\'s declared model.',
        'parts': provenance, 'deferred': deferred}, indent=2, ensure_ascii=False) + '\n')
    COLLECTION.mkdir(parents=True, exist_ok=True)
    report = {'schema': 1, 'before': before, 'after': len(entries), 'paired': len(parts),
              'with_3d': sum(bool(p.record.model_path) for p in parts), 'by_class': dict(by_family),
              'deferred': len(deferred)}
    (COLLECTION / 'catalog.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
