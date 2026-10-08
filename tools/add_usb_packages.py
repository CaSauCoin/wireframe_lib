#!/usr/bin/env python3
"""Pair every KiCad USB land pattern with the USB symbol whose contacts it carries.

Why this exists. `add_interface_packages.py` published the 75 footprints of
`Connector_USB.pretty` with *numbered* contact symbols (pins "1".."5", "A1".."B12",
all passive). That is honest about what it does not know, but it leaves a USB
connector that nothing downstream can read: no pin is called VBUS, D+ or CC1, so
the `connector.usb` contract (`vbus_protection`, `pair_present`, `shield_tie`)
can never fire, and the planner cannot wire a USB port by name. Meanwhile the
symbols that DO name the contacts — KiCad's own `Connector:USB_B_Micro`,
`USB_C_Receptacle_USB2.0_16P`, `USB3_A`, ... — were deferred as "footprint chosen
by filter; needs device-specific review", because each one fits a whole family.

The review that deferral asks for is mechanical here, and this tool does it:

  * the footprint's NAME says which USB family it is (Micro-B, Mini-B, C
    receptacle, A plug, ...), which narrows the candidates to that family;
  * among those, a symbol is taken only if its pin designators equal the
    footprint's pad designators EXACTLY (shield `SH` included). KiCad numbers
    USB pads by the USB-IF contact numbers, so equal designator sets mean every
    VBUS/D+/D-/CC pin lands on its own pad.

Anything that does not match exactly is deferred with the difference spelled out
(an extra `6` shell pad, a plug footprint with both D+/D- pairs) — never forced.

3D: a model is packed only when the footprint's own `(model ...)` file exists in
the local kicad-packages3D checkout. `has_3d` then follows the zip, not a name.

No network, no upload. Writes the local library exactly as the other add_* tools.
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

ROOT = common.ROOT
SOURCE = ROOT / 'sources/usb-packages'
COLLECTION = ROOT / 'collections/usb'
SOURCE_NAME = 'wireframe-usb-packages'
LIBRARY = 'Connector_USB'
LICENSE = 'CC-BY-SA-4.0 WITH KiCad-Libraries-exception'

# Footprint-name family -> KiCad symbols it may take, most specific first.
# Order matters only for readability: the exact designator test picks at most
# one symbol per family in practice, and `pair()` refuses when two would fit.
FAMILIES: list[tuple[str, str, list[str]]] = [
    (r'^USB3_A_.*Stacked', 'usb3_a_stacked', ['USB3_A_Stacked']),
    (r'^USB3_A_.*Plug', 'usb3_a_plug', ['USB3_A']),
    (r'^USB3_A_', 'usb3_a', ['USB3_A']),
    (r'^USB3_Micro-B', 'usb3_micro_b', ['USB3_B_Micro']),
    (r'^USB3_B_', 'usb3_b', ['USB3_B']),
    (r'^USB_A_.*Stacked', 'usb_a_stacked', ['USB_A_Stacked', 'USB3_A_Stacked']),
    (r'^USB_A_', 'usb_a', ['USB_A', 'USB3_A']),
    (r'^USB_B_', 'usb_b', ['USB_B', 'USB3_B']),
    (r'^USB_Micro-AB', 'usb_micro_ab', ['USB_OTG']),
    (r'^USB_Micro-B', 'usb_micro_b', ['USB_B_Micro', 'USB3_B_Micro']),
    (r'^USB_Mini-B', 'usb_mini_b', ['USB_B_Mini']),
    (r'^USB_C_Plug', 'usb_c_plug', ['USB_C_Plug', 'USB_C_Plug_USB2.0']),
    (r'^USB_C_Receptacle', 'usb_c_receptacle',
     ['USB_C_Receptacle', 'USB_C_Receptacle_USB2.0_16P', 'USB_C_Receptacle_USB2.0_14P',
      'USB_C_Receptacle_PowerOnly_24P', 'USB_C_Receptacle_PowerOnly_6P']),
]

KEYWORDS = {
    'usb3_a_stacked': 'USB3 USB-A type-A stacked receptacle superspeed',
    'usb3_a_plug': 'USB3 USB-A type-A plug male superspeed',
    'usb3_a': 'USB3 USB-A type-A receptacle superspeed',
    'usb3_micro_b': 'USB3 micro-B receptacle superspeed',
    'usb3_b': 'USB3 USB-B type-B receptacle superspeed',
    'usb_a_stacked': 'USB-A type-A stacked dual receptacle host',
    'usb_a': 'USB-A type-A host',
    'usb_b': 'USB-B type-B receptacle device',
    'usb_micro_ab': 'micro-AB micro-USB OTG receptacle ID',
    'usb_micro_b': 'micro-B micro-USB receptacle device',
    'usb_mini_b': 'mini-B mini-USB receptacle device',
    'usb_c_plug': 'USB-C type-C plug male',
    'usb_c_receptacle': 'USB-C type-C receptacle female',
}


def family_of(fp_name: str) -> tuple[str, list[str]] | None:
    for pattern, family, symbols in FAMILIES:
        if re.search(pattern, fp_name):
            return family, symbols
    return None


def designators(pins) -> set[str]:
    return {p for p in pins if p}


def pair(fp_name: str, pads: set[str], symbols: dict[str, set[str]]) -> tuple[str, str, str]:
    """(family, symbol, '') on an exact match, else (family, '', reason).

    Pure: takes designator sets, so the rule can be checked without any file.
    """
    found = family_of(fp_name)
    if not found:
        return '', '', 'footprint name names no USB family'
    family, candidates = found
    exact = [s for s in candidates if s in symbols and symbols[s] == pads]
    if len(exact) == 1:
        return family, exact[0], ''
    if len(exact) > 1:
        return family, '', f'ambiguous: {exact} all match'
    closest = min((s for s in candidates if s in symbols),
                  key=lambda s: len(symbols[s] ^ pads), default='')
    if not closest:
        return family, '', 'no candidate symbol in kicad-symbols'
    extra, missing = sorted(pads - symbols[closest]), sorted(symbols[closest] - pads)
    return family, '', (f'closest {closest}: pads without a pin {extra}, '
                        f'pins without a pad {missing}')


def _set_property(text: str, key: str, value: str) -> str:
    pattern = r'(\(property\s+"' + re.escape(key) + r'"\s+)"(?:\\.|[^"\\])*"'
    text, n = re.subn(pattern, lambda m: m[1] + json.dumps(value), text, count=1)
    if n != 1:
        raise ValueError(f'missing property {key}')
    return text


def _property(text: str, key: str) -> str | None:
    m = re.search(r'\(property\s+"' + re.escape(key) + r'"\s+"((?:\\.|[^"\\])*)"', text)
    return json.loads(f'"{m[1]}"') if m else None


def make_symbol(symdir: Path, symbol: str, name: str, properties: dict[str, str]) -> str:
    """KiCad's symbol renamed to `name`, properties set, as ONE standalone symbol.

    `USB_B_Mini` is `(extends "USB_B_Micro")`. Shipping the base alongside would
    put a second `USB_B_Micro` into every project pool that installs a Mini-B,
    so the derived symbol is flattened: the base's graphics and pins, the
    derived symbol's own properties (filters, datasheet) on top."""
    text = (symdir / f'{symbol}.kicad_sym').read_text()
    base = re.search(r'\(extends\s+"([^"]+)"\)', text)
    if base:
        derived = text
        text = (symdir / f'{base[1]}.kicad_sym').read_text()
        if '(extends' in text:
            raise ValueError(f'{symbol}: two-level extends is not handled')
        for key in ('Datasheet', 'ki_fp_filters'):
            value = _property(derived, key)
            if value is not None and _property(text, key) is not None:
                text = _set_property(text, key, value)
        symbol = base[1]
    # Units are `<symbol>_<unit>_<style>`. Match exactly that: the new name often
    # STARTS with the old one (`USB_A` -> `USB_A_Connfly_DS1095`), so a plain
    # prefix replace renames the top symbol twice.
    text = re.sub(r'\(symbol "' + re.escape(symbol) + r'(_\d+_\d+)?"',
                  lambda m: f'(symbol "{name}{m[1] or ""}"', text)
    for key, value in properties.items():
        text = _set_property(text, key, value)
    return text


def model_for(fp_text: str, packages3d: Path) -> Path | None:
    """The footprint's own declared model, if kicad-packages3D really has it."""
    for declared in re.findall(r'\(model\s+"?([^"\s)]+)', fp_text):
        rel = re.sub(r'^\$\{[^}]+\}/?', '', declared)
        for suffix in ('.step', '.stp', '.wrl'):
            candidate = (packages3d / rel).with_suffix(suffix)
            if candidate.exists():
                return candidate
    return None


def build(repos: Path, out: Path) -> tuple[list, list, dict]:
    symdir = repos / 'kicad-symbols/Connector.kicad_symdir'
    pretty = repos / 'kicad-footprints/Connector_USB.pretty'
    packages3d = repos / 'kicad-packages3D'
    records = []
    for path in symdir.glob('USB*.kicad_sym'):
        records += common.parse.parse_symbol_file(path, 'Connector')
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
        keywords = ['usb', 'connector', family, symbol, *KEYWORDS[family].split(),
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
            tier='A', score=90, flags=['kicad_usb_symbol_paired_by_designators'],
            named_pin_ratio=1.0)
        parts.append(common.EnrichedPart(r, 'connector.usb', ['Connector', 'USB'],
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
        'policy': 'KiCad USB symbols bound to KiCad USB footprints only when pin and pad '
                  'designators are identical; 3D only from the footprint\'s declared model.',
        'parts': provenance, 'deferred': deferred}, indent=2) + '\n')
    return parts, deferred, {p.record.id: images.get(common.package.part_slug(p), {}) for p in parts}


def other_sources(out: Path, entries: dict) -> list[dict]:
    """USB connectors already packaged by libforge but never indexed: their
    library names are LCSC numbers (`JLCPCB-Kicad-Library__2931474__...`), which
    no prefix filter reached. Same validation as every other addition."""
    found = []
    for path in sorted((out / 'parts').glob('*.zip')):
        stem = path.stem
        if stem.startswith(SOURCE_NAME) or not re.search(r'usb', stem, re.I):
            continue
        with zipfile.ZipFile(path) as z:
            if 'part.json' not in z.namelist():
                continue
            m = json.loads(z.read('part.json'))
            if m['id'] in entries or not m['class'].startswith('connector'):
                continue
            text = ' '.join([m['name'], (m.get('footprint') or {}).get('name', '')])
            if not re.search(r'USB', text, re.I) or common.validate(z, m):
                continue
            found.append((path, z.read('part.json')))
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--repos', type=Path, default=Path.home() / '.wireframe/library_cache/repos')
    ap.add_argument('--out', type=Path, default=ROOT / 'Dist_Repo/v2')
    args = ap.parse_args()
    out = args.out
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
        img = {k: v for k, v in images[p.record.id].items()}
        entry = common.package.index_entry(p, base, slug, hashlib.sha256(path.read_bytes()).hexdigest(),
                                           img, parts_base, models)
        if p.record.id not in entries:
            added.append(entry)
        entries[p.record.id] = entry

    for path, raw in other_sources(out, entries):
        m = json.loads(raw)
        with zipfile.ZipFile(path) as z:
            part = common.as_part(m, path)
            slug = common.package.part_slug(part)
            img = {}
            for kind, field in (('sym', 'symbol'), ('fp', 'footprint')):
                member = (m.get('previews') or {}).get(field)
                if member and member in z.namelist():
                    dest = out / 'previews' / f'{slug}_{kind}.png'
                    if not dest.exists():
                        dest.write_bytes(z.read(member))
                    img[kind] = f'previews/{slug}_{kind}.png'
            models = {slug} if (m.get('model3d') or {}).get('file') in z.namelist() else set()
        entry = common.package.index_entry(part, base, slug, hashlib.sha256(path.read_bytes()).hexdigest(),
                                           img, parts_base, models)
        entries[m['id']] = entry
        added.append(entry)

    # The numbered-contact packages stay downloadable (projects may reference
    # them) but leave the planner: a semantic twin with the same land pattern
    # now exists, and two rows for one connector is how the worse one gets picked.
    by_fp = {p.record.footprint_name: p.record.id for p in parts}
    superseded = []
    for e in entries.values():
        if e.get('source') == 'wireframe-interface-packages' and e.get('footprint') in by_fp:
            e['tier'] = 'C'
            e['superseded_by'] = by_fp[e['footprint']]
            superseded.append(e['id'])

    update_indexes(out, entries, manifest, added)
    manifest = json.loads((out / 'lib_index.json').read_text())
    if not any(s['name'] == SOURCE_NAME for s in manifest['sources']):
        manifest['sources'].append({'name': SOURCE_NAME, 'license': LICENSE,
            'url': 'https://github.com/CaSauCoin/wireframe_lib/tree/main/sources/usb-packages',
            'rank': 100, 'commit': '', 'provenance': 'sources/usb-packages/PROVENANCE.json'})
        (out / 'lib_index.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        with (out / 'LICENSES.md').open('a') as f:
            f.write('\n## WireFrame USB connector packages\n\nKiCad `Connector` USB symbols bound to unmodified '
                    'KiCad `Connector_USB` footprints by identical pin/pad designators; 3D models from '
                    'kicad-packages3D where the footprint declares one. CC-BY-SA-4.0 WITH '
                    'KiCad-Libraries-exception; see sources/usb-packages/PROVENANCE.json.\n')

    COLLECTION.mkdir(parents=True, exist_ok=True)
    fams = {p['id']: p['family'] for p in json.loads((SOURCE / 'PROVENANCE.json').read_text())['parts']}
    report = {
        'schema': 1, 'before': before, 'after': len(entries), 'added': len(added),
        'paired': len(parts), 'with_3d': sum(bool(p.record.model_path) for p in parts),
        'by_family': dict(Counter(fams.values())),
        'other_sources': [e['id'] for e in added if e.get('source') != SOURCE_NAME],
        'superseded': superseded, 'deferred': deferred,
        'not_in_any_source': [
            'USB 3.x Type-B / Micro-B receptacles beyond Connfly DS1104 (KiCad ships no USB3_B footprint)',
            'USB-A plugs as PCB-edge fingers (no KiCad footprint)',
            'USB-C 2-pin power-only receptacles (no KiCad symbol or footprint)',
            'USB-C plug with USB2.0 contacts only (USB_C_Plug_USB2.0 has no exact KiCad footprint)'],
    }
    (COLLECTION / 'catalog.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ('before', 'after', 'added', 'paired', 'with_3d', 'by_family')}, indent=2))
    print('Deferred:', len(deferred), '| superseded numbered packages:', len(superseded))
    for d in deferred:
        print('  -', d['footprint'], '->', d['reason'])


if __name__ == '__main__':
    main()
