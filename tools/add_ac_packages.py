#!/usr/bin/env python3
"""Restore validated AC/support packages and add explicit generic protection packages.

Uses the sibling WireFrame libforge implementation, existing local part archives,
and the pinned KiCad checkout. No network, upload, or guessed device ratings.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVIEWED_FILE = ROOT/'sources/ac-packages/reviewed-pairings.json'
REVIEWED = json.loads(REVIEWED_FILE.read_text()) if REVIEWED_FILE.exists() else {}
sys.path.insert(0, str(ROOT.parent / 'WireFrame' / 'Tools'))
from libforge import cluster, package, parse, preview, sexp
from libforge.build import PartRecord
from libforge.enrich import EnrichedPart
from libforge.jsonio import dump_index
from libcheck.checks.structural import _strict_parse

FAMILIES = {
    'Converter_ACDC': 'ac_dc', 'Triac_Thyristor': 'triac_scr',
    'Relay': 'relay', 'Relay_SolidState': 'ssr', 'Diode_Bridge': 'bridge',
    'Sensor_Current': 'current_sensor',
}

def family(m):
    lib = m['source']['library']
    text = m['name'] + ' ' + m.get('description', '')
    if lib in FAMILIES:
        return FAMILIES[lib]
    if lib == 'Isolator' and re.search(r'opto|photo|\bMOC|\bTLP|\bH11|\bPC[38]|\b4N|\b6N', text, re.I):
        return 'opto'
    if lib == 'Transformer' and re.search(r'TEZ|Triad_VPP|current|ZMCT|CST', text, re.I):
        return 'transformer'
    if lib == 'Filter' and re.search(r'\b[23]\d\d\s*VAC|suppression capacitor', text, re.I):
        return 'emi_filter'
    if re.search(r'energy meter|energy metering', text, re.I):
        return 'energy_meter'
    if lib == 'Connector' and m['name'].startswith('IEC_60320'):
        return 'ac_inlet'
    if (m.get('footprint') or {}).get('library', '').startswith('TerminalBlock'):
        return 'terminal_block'
    if m['source']['name'] == 'wireframe-ac-packages':
        return m.get('ac_family', 'protection_generic')
    return ''


def legacy_manifest(z, e):
    """Read older existing packages without changing or qualifying their contents."""
    names = z.namelist()
    sf = next(n for n in names if n.endswith('.kicad_sym'))
    ff = next(n for n in names if n.endswith('.kicad_mod'))
    syms = parse.resolve_extends(parse.parse_symbol_text(z.read(sf).decode()))
    sym = next(s for s in syms if s.name == e['name'])
    fp = parse.parse_footprint_text(z.read(ff).decode())
    model = next((n for n in names if n.endswith(('.wrl','.step','.stp'))), '')
    return {'id':e['id'],'name':e['name'],'class':e['class'],
        'description':e.get('description',''),'description_origin':'rules',
        'keywords':e.get('keywords',[]),'datasheet':e.get('datasheet',''),
        'source':{'name':e['source'],'library':e['library'],'rank':110},
        'symbol':{'file':sf,'pin_count':e['pin_count'],'units':sym.unit_count,
            'pins':[{'number':p.number,'name':p.name,'type':p.electrical_type,'unit':p.unit} for p in sym.pins]},
        'footprint':{'file':ff,'name':e['footprint'],'pad_count':e['pad_count'],
            'mount':e['mount'],'pitch_mm':fp.pitch_mm,'descr':fp.descr,'tags':fp.tags},
        'model3d':{'file':model},'quality':{'tier':e['tier'],'score':e['score']}}


def as_part(m, archive, entry=None):
    s, f, q = m['symbol'], m.get('footprint') or {}, m['quality']
    model = m.get('model3d') or {}
    src = m['source']
    r = PartRecord(
        id=m['id'], name=m['name'], source=src['name'], source_rank=src.get('rank', 100),
        library=src['library'], license=src.get('license', ''),
        symbol_path=f"{archive}::{s['file']}",
        footprint_path=f"{archive}::{f['file']}" if f.get('file') else '',
        model_path=f"{archive}::{model['file']}" if model.get('file') else '',
        description=m.get('description', ''), description_origin=m.get('description_origin', 'upstream'),
        keywords=m.get('keywords', []), datasheet=m.get('datasheet', ''),
        reference=m.get('reference_designator', ''), value=m.get('value', m['name']),
        pin_count=s.get('pin_count', 0), named_pins=s.get('named_pins', 0),
        unit_count=s.get('units', 1), pins=s.get('pins', []), fp_filters=m.get('fp_filters', []),
        footprint_name=f.get('name', ''), footprint_library=f.get('library', ''),
        pad_count=f.get('pad_count', 0), mount=f.get('mount', ''), pitch_mm=f.get('pitch_mm'),
        courtyard_mm=f.get('courtyard_mm'), body_mm=f.get('body_mm'),
        footprint_descr=f.get('descr', ''), footprint_tags=f.get('tags', ''),
        footprint_method=f.get('resolved_by', ''), model_format=model.get('format', ''),
        model_origin=model.get('origin', ''), model_method=model.get('resolved_by', ''),
        tier=q['tier'], score=q['score'], flags=q.get('flags', []),
        named_pin_ratio=q.get('named_pin_ratio', 0),
    )
    klass = m['class']
    if entry:
        # The current shards are authoritative for previous curation/edits.
        for key in ('name', 'description', 'keywords', 'datasheet', 'tier', 'score', 'pin_count', 'pad_count', 'mount'):
            if key in entry:
                setattr(r, key, entry[key])
        r.footprint_name = entry.get('footprint', r.footprint_name)
        klass = entry['class']
    ai = m.get('ai', {})
    embedding = ai.get('embedding_text') or ' | '.join([r.name, klass, r.description, ' '.join(r.keywords), r.footprint_name])
    return EnrichedPart(r, klass, m.get('category_path', []), embedding,
                        ai.get('typical_use', []), ai.get('support_components', []))


def normalize_filter(path, archive, manifest):
    """Repair the upstream build's unknown classification for named EMI filters."""
    if manifest['source']['library'] != 'Filter' or manifest['class'] != 'unknown':
        return
    is_capacitor = 'capacitor' in manifest.get('description', '').lower()
    manifest['class'] = 'passive.capacitor' if is_capacitor else 'passive.inductor'
    manifest['category_path'] = ['Passive', 'Capacitor' if is_capacitor else 'Inductor']
    manifest['classification_origin'] = 'wireframe_ac_taxonomy'
    temporary = path.with_suffix('.zip.tmp')
    with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as target:
        for info in archive.infolist():
            payload = json.dumps(manifest, ensure_ascii=False, indent=1).encode() if info.filename == 'part.json' else archive.read(info.filename)
            target.writestr(info, payload)
    temporary.replace(path)


def validate(z, m, exact=True):
    if z.testzip():
        return 'archive CRC failure'
    f = m.get('footprint') or {}
    if m['quality']['tier'] not in {'A', 'B'} or not f.get('file'):
        return 'no complete symbol + footprint package'
    review = REVIEWED.get(m['id'])
    reviewed = bool(review and review['footprint'] == f.get('name')
                    and review['footprint_sha256'] == hashlib.sha256(z.read(f['file'])).hexdigest()
                    and review['symbol_sha256'] == hashlib.sha256(z.read(m['symbol']['file'])).hexdigest())
    if exact and not reviewed and f.get('resolved_by') not in {'declared_exact', 'explicit_generic'}:
        return 'footprint chosen by filter; needs device-specific review'
    if not m['source'].get('license'):
        return 'missing source license'
    texts = {}
    for kind, part in [('symbol', m['symbol']), ('footprint', f)]:
        name = part.get('file')
        if not name or name not in z.namelist():
            return f'missing {kind} file'
        texts[kind] = z.read(name).decode('utf-8-sig')
        error = _strict_parse(texts[kind])
        if error:
            return f'{kind} parse: {error}'
    symbols = parse.resolve_extends(parse.parse_symbol_text(texts['symbol']))
    sym = next((s for s in symbols if s.name == m['name']), None)
    fp = parse.parse_footprint_text(texts['footprint'])
    if not sym or not fp:
        return 'expected symbol/footprint not found'
    pins = {p.number for p in sym.pins if p.number and p.number.lower() not in parse.MECHANICAL_DESIGNATORS}
    pads = set(fp.electrical_designators)
    if not pins or pins != pads:
        return f'pin/pad designators differ: pins={sorted(pins)}, pads={sorted(pads)}'
    if len(pins) != m['symbol']['pin_count'] or len(pads) != f['pad_count']:
        return 'manifest pin/pad count differs from files'
    return ''


def generic_parts(repos, out):
    """Bind generic KiCad protection symbols to every compatible native land pattern.

    These are package templates, never manufacturer-qualified electrical parts.
    No voltage, fuse current, breaking capacity, or approval is inferred.
    """
    source_root = ROOT / 'sources' / 'ac-packages'
    items = []
    for lib, glob, symbol, group, klass in [
        ('Varistor', '*.kicad_mod', 'Varistor', 'mov_package', 'protection'),
        ('Fuse', '*5x20*.kicad_mod', 'Fuse', 'fuse_package', 'protection.fuse'),
        ('Fuse', '*6.3x32*.kicad_mod', 'Fuse', 'fuse_package', 'protection.fuse'),
        ('Fuse', '*5x15*.kicad_mod', 'Fuse', 'fuse_package', 'protection.fuse'),
        ('Fuse', 'GDT_*.kicad_mod', 'GDT_3Pin', 'gdt_package', 'protection'),
    ]:
        for fp_path in sorted((repos / 'kicad-footprints' / (lib + '.pretty')).glob(glob)):
            if any(item[0] == fp_path for item in items):
                continue
            items.append((fp_path, symbol, group, klass))
    parts, provenance, groups = [], [], {}
    for fp_path, symbol, group, klass in items:
        fp = parse.parse_footprint_file(fp_path)
        original = repos / 'kicad-symbols' / 'Device.kicad_symdir' / (symbol + '.kicad_sym')
        text = original.read_text()
        sym = parse.parse_symbol_text(text)[0]
        if {p.number for p in sym.pins} != set(fp.electrical_designators):
            raise ValueError(f'generic pin/pad mismatch: {fp_path}')
        name = f'Generic_{symbol}__{fp.name}'
        desc = (f'Generic {symbol} package template; {fp.name}. '
                'Electrical ratings and mains suitability are unspecified; choose and verify the actual device separately.')
        text = text.replace('"' + symbol + '"', '"' + name + '"').replace('"' + symbol + '_', '"' + name + '_')
        properties = {'Value': name, 'Footprint': f'{fp.library}:{fp.name}',
                      'Description': desc, 'ki_keywords': f'{symbol} {group} generic package template ratings unspecified'}
        for key, value in properties.items():
            pattern = r'(\(property\s+"' + re.escape(key) + r'"\s+)"(?:\\.|[^"\\])*"'
            text, n = re.subn(pattern, lambda match: match[1] + json.dumps(value), text, count=1)
            if n != 1:
                raise ValueError(f'missing property {key}: {original}')
        dest_sym = source_root / 'symbols' / (name + '.kicad_sym')
        dest_fp = source_root / (fp.library + '.pretty') / fp_path.name
        dest_sym.parent.mkdir(parents=True, exist_ok=True)
        dest_fp.parent.mkdir(parents=True, exist_ok=True)
        dest_sym.write_text(text)
        dest_fp.write_bytes(fp_path.read_bytes())
        r = PartRecord(id=f'wireframe-ac-packages/AC_Protection/{name}', name=name,
            source='wireframe-ac-packages', source_rank=100, library='AC_Protection',
            symbol_path=str(dest_sym), footprint_path=str(dest_fp),
            license='CC-BY-SA-4.0 WITH KiCad-Libraries-exception',
            description=desc, description_origin='rules', keywords=properties['ki_keywords'].split(),
            reference=sym.properties.get('Reference', ''), value=name,
            pin_count=len(fp.electrical_designators), named_pins=sum(p.name not in {'', '~'} for p in sym.pins),
            pins=[{'number': p.number, 'name': p.name, 'type': p.electrical_type, 'unit': p.unit} for p in sym.pins],
            footprint_name=fp.name, footprint_library=fp.library, pad_count=fp.pad_count,
            mount=fp.mount, pitch_mm=fp.pitch_mm, courtyard_mm=fp.courtyard, body_mm=fp.body,
            footprint_descr=fp.descr, footprint_tags=fp.tags, footprint_method='explicit_generic',
            tier='B', score=70, flags=['generic_package_ratings_unspecified'])
        p = EnrichedPart(r, klass, ['Protection'], desc + ' ' + properties['ki_keywords'], [], [])
        parts.append(p)
        groups[r.id] = group
        provenance.append({'id': r.id, 'symbol': f'kicad-symbols/Device.kicad_symdir/{symbol}.kicad_sym',
            'footprint': f'kicad-footprints/{fp.library}.pretty/{fp_path.name}',
            'source_symbol_sha256': hashlib.sha256(original.read_bytes()).hexdigest(),
            'source_footprint_sha256': hashlib.sha256(fp_path.read_bytes()).hexdigest(),
            'generated_symbol_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'family': group})
    images, stats = preview.render(parts, out, workers=4, progress=print)
    if len(images) != len(parts):
        raise ValueError(f'Incomplete generic previews: {len(images)}/{len(parts)}')
    package.write_part_zips(parts, out, include_3d=False, previews=images, progress=print)
    for p in parts:
        path = out / 'parts' / (package.part_slug(p) + '.zip')
        with zipfile.ZipFile(path) as z:
            m = json.loads(z.read('part.json'))
            error = validate(z, m)
            if error:
                raise ValueError(f'{p.record.name}: {error}')
    manifest = json.loads((out / 'lib_index.json').read_text())
    commits = {name: subprocess.check_output(['git','-C',str(repos/name),'rev-parse','HEAD'], text=True).strip()
               for name in ('kicad-symbols','kicad-footprints')}
    (source_root / 'PROVENANCE.json').write_text(json.dumps({
        'schema': 1, 'license': 'CC-BY-SA-4.0 WITH KiCad-Libraries-exception',
        'upstream_commits': commits,
        'policy': 'Explicit generic package templates; no component ratings or certification inferred.',
        'parts': provenance}, ensure_ascii=False, indent=2) + '\n')
    return groups


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'Dist_Repo/v2')
    parser.add_argument('--repos', type=Path, default=Path.home() / '.wireframe/library_cache/repos')
    parser.add_argument('--generic', action='store_true', help='build reproducible generic protection packages first')
    args = parser.parse_args()
    out = args.out
    manifest = json.loads((out / 'lib_index.json').read_text())
    base = manifest['base_url']; parts_base = manifest['parts_base_url']
    shards = {f.stem: json.loads(f.read_text()) for f in sorted((out/'shards').glob('*.json'))}
    entries = {e['id']: e for s in shards.values() for e in s['entries']}
    before = len(entries)
    previous_path = ROOT/'collections/ac/catalog.json'
    previous = json.loads(previous_path.read_text()) if previous_path.exists() else {}
    groups = generic_parts(args.repos, out) if args.generic else {}
    provenance_path = ROOT/'sources/ac-packages/PROVENANCE.json'
    if provenance_path.exists():
        groups.update({p['id']:p['family'] for p in json.loads(provenance_path.read_text())['parts']})
    parts, metadata, selected, skipped, additions = {}, {}, [], [], []
    for e in entries.values():
        path = out/'parts'/(e['slug']+'.zip')
        with zipfile.ZipFile(path) as z:
            m = json.loads(z.read('part.json')) if 'part.json' in z.namelist() else {}
            if not all(k in m for k in ('symbol', 'quality')):
                m = legacy_manifest(z, e)
        if m['id'] != e['id']:
            raise ValueError(f'archive identity mismatch: {path}')
        parts[e['id']] = as_part(m, path, e)
        metadata[e['id']] = m
    # Limit archive reads to relevant library families and sources.
    libraries = set(FAMILIES) | {'Isolator','Transformer','Filter','Sensor','Sensor_Energy','Connector','AC_Protection',
                                'dk_Terminal-Blocks-Wire-to-Board'}
    paths = [p for p in sorted((out/'parts').glob('*.zip'))
             if len(p.stem.split('__')) > 2 and p.stem.split('__')[1] in libraries]
    for path in paths:
        with zipfile.ZipFile(path) as z:
            m = json.loads(z.read('part.json'))
            group = groups.get(m['id'], family(m))
            if not group:
                continue
            if m['id'] in entries:
                if m['source']['name'] == 'wireframe-ac-packages':
                    entries[m['id']]['hash'] = hashlib.sha256(path.read_bytes()).hexdigest()
                selected.append({'id': m['id'], 'family': group, 'status': 'existing'})
                continue
            normalize_filter(path, z, m)
            reason = validate(z, m)
            if reason:
                skipped.append({'id': m['id'], 'family': group, 'reason': reason})
                continue
            p = as_part(m, path)
            slug = package.part_slug(p)
            if slug != path.stem:
                raise ValueError(f'archive slug differs: {path}')
            images = {}
            for kind, field in [('sym','symbol'),('fp','footprint')]:
                image_name = (m.get('previews') or {}).get(field)
                if image_name and image_name in z.namelist():
                    dest = out/'previews'/f'{slug}_{kind}.png'
                    if not dest.exists():
                        dest.write_bytes(z.read(image_name))
                    images[kind] = f'previews/{slug}_{kind}.png'
            models = {slug} if (m.get('model3d') or {}).get('file') in z.namelist() else set()
            entry = package.index_entry(p, base, slug, hashlib.sha256(path.read_bytes()).hexdigest(), images, parts_base, models)
            entries[m['id']] = entry
            parts[m['id']] = p
            metadata[m['id']] = m
            additions.append({'id': m['id'], 'family': group, 'slug': slug})
            selected.append({'id': m['id'], 'family': group, 'status': 'added'})
    # Preserve pre-existing shard rows; append validated additions.
    now = package._now()
    for item in additions:
        e = entries[item['id']]
        name = e['class'].split('.')[0]
        if name not in shards:
            shards[name] = {'shard':name,'entries':[]}
        shards[name]['entries'].append(e)
    for name, shard in shards.items():
        if len(shard['entries']) != shard.get('count') or (args.generic and any(e['source']=='wireframe-ac-packages' for e in shard['entries'])):
            shard['count'] = len(shard['entries']); shard['generated_at'] = now
            target = out/'shards'/f'{name}.json'
            formatted = target.exists() and '\n' in target.read_text()
            target.write_text(json.dumps(shard, indent=2) if formatted else dump_index(shard))
    all_parts = list(parts.values())
    clusters = cluster.cluster_parts(all_parts, progress=print)
    cluster_counts = cluster.write_clusters(clusters, out, progress=print)
    models = {e['slug'] for e in entries.values() if e.get('has_3d')}
    package.write_search_index(all_parts, out/'lib_search.sqlite', base, clusters, packaged_models=models, progress=print)
    with sqlite3.connect(out/'lib_search.sqlite') as conn:
        conn.executemany('UPDATE part SET slug=?, download_url=? WHERE id=?',
                         [(e['slug'],e['download_url'],e['id']) for e in entries.values()])
    visible = [e for e in entries.values() if e['tier'] in {'A','B','G'}]
    manifest['generated_at'] = now
    manifest['counts'] = {'total':len(entries),'planner_visible':len(visible),
        'by_tier':dict(Counter(e['tier'] for e in entries.values())),
        'by_source':dict(Counter(e['source'] for e in entries.values())),
        'with_description':sum(bool(e.get('description')) for e in visible),
        'with_footprint':sum(bool(e.get('footprint')) for e in visible),
        'with_3d':sum(bool(e.get('has_3d')) for e in visible),
        'description_origin':dict(Counter(parts[e['id']].record.description_origin for e in visible))}
    manifest['shards'] = [{'name':n,'count':len(s['entries']),'file':f'shards/{n}.json'} for n,s in sorted(shards.items())]
    manifest['clusters'] = {'index':'clusters/index.json','count':len(clusters),'by_class':cluster_counts}
    if any(e['source']=='wireframe-ac-packages' for e in entries.values()) and not any(s['name']=='wireframe-ac-packages' for s in manifest['sources']):
        manifest['sources'].append({'name':'wireframe-ac-packages','license':'CC-BY-SA-4.0 WITH KiCad-Libraries-exception',
            'url':'https://github.com/CaSauCoin/wireframe_lib/tree/main/sources/ac-packages','rank':100,'commit':'',
            'provenance':'sources/ac-packages/PROVENANCE.json'})
        licenses = out/'LICENSES.md'
        with licenses.open('a') as stream:
            stream.write('\n## WireFrame AC generic packages\n\nKiCad-derived generic protection symbols and unmodified footprints; '
                         'CC-BY-SA-4.0 WITH KiCad-Libraries-exception. See `sources/ac-packages/PROVENANCE.json` for upstream commits and hashes. '
                         'No electrical rating or mains certification is implied.\n')
    (out/'lib_index.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    compat_path = out/'compat/lib_index.json'
    compat = json.loads(compat_path.read_text()); compat_ids={e['id'] for e in compat['libraries']}
    for item in additions:
        e=entries[item['id']]
        if e['slug'] not in compat_ids:
            compat['libraries'].append({'id':e['slug'],'name':e['name'],'category':e['class'],
                'download_url':e['download_url'],'hash':e['hash'],'preview_sym':e['preview_sym'],'preview_fp':e['preview_fp'],
                'components':[{'type':'sym'},{'type':'fp'}]+([{'type':'3d'}] if e['has_3d'] else [])})
    generic_entries = {e['slug']:e for e in entries.values() if e['source']=='wireframe-ac-packages'}
    for row in compat['libraries']:
        matched = generic_entries.get(row['id']) if args.generic else None
        if matched:
            row['hash'] = matched['hash']
    compat['generated_at']=now
    compat_path.write_text(json.dumps(compat, indent=2) if '\n' in compat_path.read_text() else dump_index(compat))
    collection=ROOT/'collections/ac'; collection.mkdir(parents=True,exist_ok=True)
    additions = list({a['id']:a for a in previous.get('additions', []) + additions}.values())
    initial_before = previous.get('before', before)
    baseline_commit = previous.get('baseline_commit') or subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'], text=True).strip()
    added_ids = {a['id'] for a in additions}
    for item in selected:
        if item['id'] in added_ids:
            item['status'] = 'added'
    report={'schema':1,'baseline_commit':baseline_commit,'scope':'All matching local packages; new device entries require an exact declared or documented reviewed footprint and matching pin/pad designators.',
        'before':initial_before,'after':len(entries),'added':len(additions),
        'by_family':dict(Counter(a['family'] for a in additions)),
        'additions':additions,'selected':selected,'deferred':skipped,
        'limitations':['Generic packages have no inferred voltage/current/certification.',
            'NTC inrush limiters, standalone X/Y safety capacitors, contactors and circuit breakers need exact manufacturer sources.',
            'This operation updates the local library; no release is uploaded.']}
    (collection/'catalog.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['before','after','added','by_family']},indent=2))
    print('Deferred:',len(skipped))

if __name__=='__main__':
    main()
