#!/usr/bin/env python3
"""Add parts fetched from LCSC by exact part number to the published library.

Input: sources/lcsc-parts/kicad/ — written by WireFrame's
`wf-lcsc-collect --out sources/lcsc-parts/kicad --list sources/lcsc-parts/to_collect.txt`,
the same install the app runs when a BOM row is missing from this library
(AI/Library/AI_Lcsc_Source): an EXACT manufacturer part number, the drawing's
own part number checked against it, every symbol pin on a pad of its own
footprint. Each part is a <MPN>.kicad_sym, its <package>_<LCSC>.kicad_mod and
a <MPN>.lcsc.json saying where it came from.

What this tool adds on top, and nothing else:

  * the record is built by libforge's own tree-source path (pair, tier), so an
    LCSC part is judged exactly as every other source is;
  * its description, maker, package and datasheet come from the LCSC catalogue
    entry the collector chose (cached under the library cache), not from the
    symbol, whose only "description" is its part number;
  * its library is named from LCSC's category in KiCad's own vocabulary
    (`Voltage Regulators - Linear` -> `Regulator_Linear`), so libforge's
    classifier files it as it files a KiCad part (`ic.power.ldo`), rather than
    as a bare `ic`;
  * a part already in the library under that part number is skipped, and a
    part whose class cannot be read is deferred, not filed under `unknown`.

Writes the local library exactly as the other add_* tools do — part zips,
previews, the affected class shards, clusters, the search index, the manifest,
LICENSES.md, PROVENANCE.json and collections/lcsc/catalog.json. No network,
no upload. `--plan` prints what would be added and writes nothing.

EasyEDA's terms for redistributing this content must be confirmed before a
PUBLIC release of a library built with it.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import re
import sqlite3
import zipfile
from collections import Counter
from pathlib import Path

import add_ac_packages as common
from libforge import build, classify, enrich, pair, sources
from libcontract import archetypes as contract_archetypes
from libcontract import build as contract_build
from libcontract import pack as contract_pack
from libcontract import subset as contract_subset

ROOT = common.ROOT
SOURCE = ROOT / 'sources/lcsc-parts'
KICAD = SOURCE / 'kicad'
COLLECTION = ROOT / 'collections/lcsc'
SOURCE_NAME = 'wireframe-lcsc-parts'
LICENSE = ('LCSC/EasyEDA component data (symbol, footprint) fetched by exact '
           'manufacturer part number; redistribution terms to be confirmed before '
           'a public release. Per-part provenance in sources/lcsc-parts/PROVENANCE.json')
SEARCH_CACHE = sources.LIBRARY_CACHE_DIR / 'lcsc' / 'search'

# LCSC category -> a library name in KiCad's vocabulary, which libforge.classify
# reads, and the class where classify cannot reach it from a library name (a
# USB receptacle's library says `connector`, its `J` no more; a TVS diode's `D`
# outranks `Power_Protection`, since classify keeps the most specific of its
# signals). Matched against the SUB-category first and the top one only when
# nothing matched: read as one string, "Operational Amplifier | Amplifiers/
# Comparators" was filed as a comparator and "USB Connectors" as a USB chip.
# Order: connectors, then chips and discretes, then the generic words
# ("Switches" ends both "Tactile Switches" and "Analog Switches").
CATEGORY_TO_LIBRARY: list[tuple[str, str, str]] = [
    (r'USB Connector|Type-C', 'Connector_USB', 'connector.usb'),
    (r'SD Card|Memory Card|SIM Card|Card Connector', 'Connector_Card', 'connector.card'),
    (r'Ethernet Connector|Modular Connector|RJ45', 'Connector_RJ', 'connector'),
    (r'Audio Connector|Audio Jack', 'Connector_Audio', 'connector.audio'),
    (r'Power connector|DC Power Connector|Barrel', 'Connector_Power', 'connector.power'),
    (r'Wire To Board', 'Connector_WireToBoard', 'connector.wire_to_board'),
    (r'Terminal Block|Screw Terminal', 'Connector_TerminalBlock', 'connector.terminal_block'),
    (r'Header|Board To Board|FFC|FPC|Connector', 'Connector', 'connector'),

    (r'Low Drop Out|LDO|Linear Regulator', 'Regulator_Linear', ''),
    (r'DC-DC|Switching Regulator|Buck|Boost', 'Regulator_Switching', ''),
    (r'Charge Pump', 'Regulator_SwitchedCapacitor', ''),
    (r'AC-DC Controller|PWM Controller', 'Regulator_Controller', ''),
    (r'Battery Management|Battery Charg', 'Battery_Management', ''),
    (r'Supervisor|Reset IC|Voltage Detector', 'Power_Supervisor', ''),
    (r'Voltage Reference', 'Reference_Voltage', ''),
    (r'Power Distribution Switch|Load Switch|Power Mux|Ideal Diode|ORing', 'Power_Management', ''),
    (r'Microcontroller|MCU', 'MCU_LCSC', ''),
    (r'(WiFi|Bluetooth|LoRa|Zigbee|GPS|GNSS|NFC|RFID|\dG|NB-IoT|Communication|RF) ?\S* ?Modules?', 'RF_Module', ''),
    (r'RF ', 'RF', ''),
    (r'USB', 'Interface_USB', ''),
    (r'Ethernet', 'Interface_Ethernet', ''),
    (r'\bCAN\b', 'Interface_CAN', ''),
    (r'RS232|RS485|RS-485|RS-422|UART', 'Interface_UART', ''),
    (r'I/O Expander', 'Interface_Expansion', ''),
    (r'Digital Isolator|Optoisolator|Optocoupler|Isolator', 'Isolator', ''),
    (r'Level Shifter|Translator', 'Logic_LevelTranslator', ''),
    (r'Analog Switch|Multiplexer', 'Analog_Switch', ''),
    (r'Shift Register|Inverter|Logic Gate|Buffer|Flip Flop|Counter|Decoder|Logic', 'Logic_LCSC', ''),
    (r'Current Sensor', 'Sensor_Current', ''),
    (r'Magnetic|Hall|Position Sensor', 'Sensor_Magnetic', ''),
    (r'Touch', 'Sensor_Touch', ''),
    (r'Sensor|Accelerometer|Gyroscope|IMU', 'Sensor_LCSC', ''),
    (r'EEPROM|FRAM|FLASH|SRAM|eMMC|Memory', 'Memory_LCSC', ''),
    (r'Analog to Digital|\bADC', 'Analog_ADC', ''),
    (r'Digital to Analog|\bDAC', 'Analog_DAC', ''),
    (r'Real Time Clock|Real-time Clock|RTC|Timer', 'Timer_RTC', ''),
    (r'Comparator', 'Comparator', ''),
    (r'Instrumentation', 'Amplifier_Instrumentation', ''),
    (r'Audio Amplifier|Audio Power', 'Amplifier_Audio', ''),
    (r'Op Amp|Operational|FET Input Amplifier|Amplifier', 'Amplifier_Operational', ''),
    (r'Gate Driver', 'Driver_FET', ''),
    (r'Motor', 'Driver_Motor', ''),
    (r'LED Driver|LCD Driver|Digital Tube Driver|Display Driver', 'Driver_LED', ''),
    (r'Darlington|Transistor Array', 'Transistor_Array', ''),
    (r'Thyristor|\bSCR\b|TRIAC', 'Transistor_Thyristor', ''),
    (r'MOSFET', 'Transistor_FET', ''),
    (r'Bipolar|BJT|Transistor', 'Transistor_BJT', ''),
    (r'Bridge Rectifier', 'Diode_Bridge', ''),
    (r'TVS|ESD|Surge', 'Power_Protection', 'protection'),
    (r'Fuse', 'Fuse', 'protection.fuse'),
    (r'Diode', 'Diode', ''),
    (r'OLED|TFT|LCD|Graphic', 'Display_Graphic', ''),
    (r'Segment', 'Display_Character', 'display.led'),
    (r'LED|Light Emitting', 'LED', ''),

    (r'relay', 'Relay', ''),
    (r'Buzzer', 'Buzzer', 'electromechanical.buzzer'),
    (r'Encoder', 'Switch', 'electromechanical.encoder'),
    (r'Switch', 'Switch', ''),
    (r'Inductor|Choke|Coil', 'Inductor', ''),
    (r'Oscillator', 'Oscillator', ''),
    (r'Crystal|Resonator', 'Crystal', ''),
]


def library_for(sub: str, top: str) -> tuple[str, str]:
    """(library, class or '') for an LCSC category; ('', '') when unread."""
    for text in (sub, top):
        for pattern, library, klass in CATEGORY_TO_LIBRARY:
            if text and re.search(pattern, text, re.I):
                return library, klass
    return '', ''


_ROWS: dict[str, dict] = {}


def catalogue_entry(lcsc: str) -> dict:
    """The catalogue row the collector chose, by its LCSC code, from any search
    the collector cached. Not by file name: the cache was named three ways as
    the collector was fixed ("max30102efd+t.json" before "+" was folded, none
    at all for "MCP23017-E/SO" before the slash was), and a part whose row is
    not found loses its category and is filed as a bare `ic`."""
    if not _ROWS:
        for path in sorted(SEARCH_CACHE.glob('*.json')):
            try:
                data = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            for row in ((data.get('data') or {}).get('componentPageInfo') or {}).get('list') or []:
                if row.get('componentCode'):
                    _ROWS.setdefault(row['componentCode'], row)
    return _ROWS.get(lcsc, {})


def published_keys(out: Path) -> set[str]:
    def k(s: str) -> str:
        return re.sub(r'[^a-z0-9]', '', s.lower().rstrip('+'))
    with sqlite3.connect(out / 'lib_search.sqlite') as conn:
        return {k(name) for (name,) in conn.execute('SELECT name FROM part')}


def build_parts() -> tuple[list, list, dict]:
    """libforge's own record for every collected part, with the catalogue's
    facts, and the class the category names where classify cannot read it."""
    src = sources.Source(SOURCE_NAME, KICAD, 55, license=LICENSE,
                         url='https://github.com/CaSauCoin/wireframe_lib/tree/main/sources/lcsc-parts')
    catalog = pair.FootprintCatalog(list(sources.iter_footprints(src)))
    records = build.build_tree_source(src, catalog, pair.ModelCatalog())
    provenance, kept, classes = [], [], {}
    for record in records:
        meta_path = KICAD / f'{record.name}.lcsc.json'
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        row = catalogue_entry(meta.get('lcsc', ''))
        sub, top = row.get('firstSortName') or '', row.get('secondSortName') or ''
        maker = meta.get('manufacturer') or row.get('componentBrandEn') or ''
        package = meta.get('package') or row.get('componentSpecificationEn') or ''
        said = (row.get('describe') or '').replace(' ROHS', '').strip()
        library, klass = library_for(sub, top)
        record.library = library or record.library
        record.id = f'{SOURCE_NAME}/{record.library or "LCSC"}/{record.name}'
        if klass:
            classes[record.id] = klass
        record.description = '. '.join(x for x in [
            f'{meta.get("mpn", record.name)} by {maker}' if maker else meta.get('mpn', record.name),
            f'{sub} ({top})' if sub else '', f'Package {package}' if package else '', said] if x)
        record.description_origin = 'upstream'
        # The catalogue's PDF first; the drawing's own link is what its uploader
        # typed (a product page, once a search for another chip).
        record.datasheet = row.get('dataManualUrl') or meta.get('datasheet') or record.datasheet
        record.keywords = sorted({w for w in [meta.get('mpn', ''), meta.get('lcsc', ''), maker, package,
                                              sub, top, 'LCSC', 'JLCPCB'] if w})
        record.value = meta.get('mpn', record.name)
        kept.append(record)
        provenance.append({**{k: meta.get(k) for k in ('lcsc', 'mpn', 'manufacturer', 'package', 'url',
                                                       'fetched', 'datasheet', 'warnings')},
                           'id': record.id, 'category': f'{top} / {sub}',
                           'symbol': f'sources/lcsc-parts/kicad/{record.name}.kicad_sym',
                           'symbol_sha256': hashlib.sha256(Path(record.symbol_path).read_bytes()).hexdigest(),
                           'footprint': f'sources/lcsc-parts/kicad/{Path(record.footprint_path).name}'
                           if record.footprint_path else '',
                           'footprint_sha256': hashlib.sha256(Path(record.footprint_path).read_bytes()).hexdigest()
                           if record.footprint_path else ''})
    return kept, provenance, classes


# ── Contracts ───────────────────────────────────────────────────────────────
#
# Two layers, as for every part already in the library:
#   1. libcontract's own contract: the symbol's pins, the class archetype
#      (decoupling, pull-ups …) and the pin-name patterns. Built per part with
#      the family libcontract's subset would give it — uncapped, since a cap is
#      about which of many near-identical KiCad symbols to keep, and these are
#      each one part;
#   2. what agy READ in the part's datasheet (wf-contract-research, the app's
#      own /contract research): pin roles, rails with their voltages, clauses —
#      every clause naming the page it came from, every pin checked against the
#      symbol. Laid over layer 1: a cited clause replaces the class default of
#      the same id, a pin read from the datasheet replaces the pattern's guess.
# Nothing a model wrote without a document is merged: an ungrounded proposal
# is capped at "info" in the app and adds nothing a library should ship.

def base_contracts(parts: list) -> list:
    """`parts` are libforge EnrichedParts: the record, and the class enrich gave
    it — which the subset's families match on (a record alone carries none)."""
    families = [dataclasses.replace(f, max_parts=10 ** 9) for f in contract_subset.load_families()]
    rows = [{**p.record.to_json(), 'class': p.klass} for p in parts]
    selection = contract_subset.select(rows, families)
    table = contract_archetypes.load()
    overrides = contract_build.load_overrides()
    out = []
    for family_id, chosen in selection.families.items():
        for record in chosen:
            lib_id = str(record.get('id', ''))
            out.append(contract_build.contract_for(record, selection.archetype_of[lib_id], family_id,
                                                   overrides.get(lib_id), table))
    return out


def overlay(entry: dict, read: dict, datasheet: str) -> dict:
    """A pack entry with what the datasheet said laid over it."""
    merged = dict(entry)
    pins = {p['number']: dict(p) for p in entry.get('pins', [])}
    for p in read.get('pins', []):
        mine = pins.setdefault(p['number'], {'number': p['number'], 'name': p.get('name', '')})
        for key in ('role', 'domain', 'required', 'pull', 'polarity'):
            if p.get(key):
                mine[key] = p[key]
    merged['pins'] = sorted(pins.values(), key=lambda p: (not p['number'].isdigit(),
                                                          int(p['number']) if p['number'].isdigit() else 0,
                                                          p['number']))
    for field in ('companions', 'rules'):
        by_id = {c.get('id'): c for c in entry.get(field, [])}
        for c in read.get(field, []):
            if c.get('citation'):
                by_id[c.get('id')] = c
        merged[field] = list(by_id.values())
    if read.get('domains'):
        # Ground needs no page; dropping it left every GND pin naming a domain
        # the contract did not have.
        merged['domains'] = [d for d in read['domains'] if d.get('citation') or d.get('kind') == 'ground']
    if read.get('archetype') and read['archetype'].count('.') > entry.get('archetype', '').count('.'):
        merged['archetype'] = read['archetype']
    merged['authored_by'] = read.get('authored_by', '')
    merged['datasheet_url'] = datasheet
    return merged


def researched_by_name(path: Path | None) -> dict[str, dict]:
    """Researched contracts by part name. The lib_id names the library too,
    and the library is read from LCSC's category — which this tool maps, and
    has re-mapped (op amps were once filed under Comparator): a contract read
    from a datasheet must not be lost, or paid for again, over that."""
    if not path or not path.exists():
        return {}
    return {lib_id.rsplit('/', 1)[-1]: c for lib_id, c in json.loads(path.read_text()).get('parts', {}).items()}


def flags_after(flags: list[str], entry: dict, read: bool) -> list[str]:
    """The base contract's flags, less what the datasheet answered."""
    volts = any(d.get(k) is not None for d in entry.get('domains', []) for k in ('v_min', 'v_max', 'v_nom'))
    return [f for f in flags if not (volts and f == 'no_supply_voltages')] + (['datasheet_read'] if read else [])


def cited(read: dict | None) -> bool:
    return bool(read) and any(x.get('citation') for x in read.get('companions', []) + read.get('rules', [])
                              + read.get('domains', []))


def read_only_entry(read: dict, klass: str, datasheet: str) -> dict:
    """A pack entry from the datasheet alone, for a part no libcontract family
    covers (a crystal named X322516MLB4SI, a TVS named SMF15CA — the families
    match KiCad's names). Only what names its page."""
    entry = overlay({'name': read.get('name', ''), 'class': klass, 'archetype': read.get('archetype', klass),
                     'pins': [], 'companions': [], 'rules': []}, read, datasheet)
    entry['companions'] = [c for c in entry['companions'] if c.get('citation')]
    entry['rules'] = [r for r in entry['rules'] if r.get('citation')]
    return entry


def add_contracts(out: Path, parts: list, researched_file: Path | None) -> dict:
    cdir = out / 'contracts'
    manifest = json.loads((cdir / 'contracts.json').read_text())
    pack: dict[str, dict] = {}
    for f in sorted((cdir / 'shards').glob('*.json')):
        pack.update(json.loads(f.read_text())['parts'])
    researched = researched_by_name(researched_file)
    datasheet_of = {p.record.id: p.record.datasheet for p in parts}

    contracts = base_contracts(parts)
    stats = Counter()
    index_rows = []
    for c in contracts:
        entry = contract_pack._part(c)
        read = researched.get(c.lib_id.rsplit('/', 1)[-1])
        if cited(read):
            entry = overlay(entry, read, datasheet_of.get(c.lib_id, ''))
            stats['datasheet'] += 1
        else:
            stats['base'] += 1
        pack[c.lib_id] = entry
        data = c.to_json()
        (cdir / 'parts').mkdir(exist_ok=True)
        (cdir / 'parts' / f'{c.slug}.json').write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
        index_rows.append({'lib_id': c.lib_id, 'slug': c.slug, 'name': c.name, 'family': c.family,
                           'archetype': entry.get('archetype', c.archetype), 'class': c.part_class,
                           'pin_count': len(entry.get('pins', [])), 'companions': len(entry.get('companions', [])),
                           'rules': len(entry.get('rules', [])), 'enforceable': len(c.enforceable()),
                           'flags': flags_after(c.flags, entry, cited(read)), 'coverage': c.coverage,
                           'hash': data['hash']})

    covered = {c.lib_id for c in contracts}
    for p in parts:
        read = researched.get(p.record.id.rsplit('/', 1)[-1])
        if p.record.id in covered or not cited(read):
            continue
        entry = read_only_entry(read, p.klass, p.record.datasheet)
        pack[p.record.id] = entry
        stats['datasheet_only'] += 1
        text = json.dumps(entry, sort_keys=True, ensure_ascii=False)
        index_rows.append({'lib_id': p.record.id, 'slug': common.package.part_slug(p), 'name': p.record.name,
                           'family': '', 'archetype': entry.get('archetype', p.klass), 'class': p.klass,
                           'pin_count': len(entry.get('pins', [])), 'companions': len(entry['companions']),
                           'rules': len(entry['rules']),
                           'enforceable': sum(1 for x in entry['companions'] + entry['rules']
                                              if x.get('severity') in ('warning', 'error')),
                           'flags': flags_after([], entry, True), 'coverage': {},
                           'hash': 'sha256:' + hashlib.sha256(text.encode()).hexdigest()})

    # The shards again, by libcontract's own grouping (class root, 750 a shard).
    grouped: dict[str, list] = {}
    for lib_id in sorted(pack):
        grouped.setdefault(contract_pack._shard_name(pack[lib_id].get('class', '')), []).append(lib_id)
    shard_dir = cdir / 'shards'
    written, listing = set(), []
    size = contract_pack.SHARD_SIZE
    for name in sorted(grouped):
        ids = grouped[name]
        chunks = [ids[i:i + size] for i in range(0, len(ids), size)] or [[]]
        for number, chunk in enumerate(chunks):
            label = name if len(chunks) == 1 else f'{name}-{number:02d}'
            members = {i: pack[i] for i in chunk}
            contract_pack._compact({'shard': label, 'count': len(members), 'parts': members},
                                   shard_dir / f'{label}.json')
            written.add(f'{label}.json')
            listing.append({'name': label, 'file': f'shards/{label}.json', 'count': len(members)})
    for stale in shard_dir.glob('*.json'):
        if stale.name not in written:
            stale.unlink()
    for row in index_rows:
        manifest['by_name'].setdefault(row['name'].upper(), row['lib_id'])
    manifest['shards'] = listing
    manifest['counts'] = {'parts': len(pack),
                          'clauses': sum(len(p.get('companions', [])) + len(p.get('rules', [])) for p in pack.values()),
                          'pins': sum(len(p.get('pins', [])) for p in pack.values())}
    manifest['generated_at'] = common.package._now()
    contract_pack._compact(manifest, cdir / 'contracts.json')

    index = json.loads((cdir / 'contract_index.json').read_text())
    known = {row['lib_id'] for row in index['parts']}
    index['parts'] = [row for row in index['parts'] if row['lib_id'] not in {r['lib_id'] for r in index_rows}] + index_rows
    index['counts'] = {'parts': len(index['parts']),
                       'families': len({r['family'] for r in index['parts']}),
                       'archetypes': len({r['archetype'] for r in index['parts']})}
    (cdir / 'contract_index.json').write_text(json.dumps(index, indent=2, ensure_ascii=False) + '\n')
    stats['new'] = sum(1 for r in index_rows if r['lib_id'] not in known)
    return dict(stats)


def update_indexes(out: Path, entries: dict, manifest: dict, touched_shards: set[str],
                   shard_of: dict[str, str]) -> None:
    """The class shards that gained parts, then everything derived from all parts.

    An entry stays in the shard it was read from. Regrouping every entry by its
    class root dropped 19 of them: wireframe-popular-packages files carrier
    boards under classes like `sensor.imu` and `rf.module.lora` in the `module`
    and `ic` shards, and no shard is named `sensor` or `rf`."""
    base = manifest['base_url']
    all_parts = []
    for e in entries.values():
        path = out / 'parts' / (e['slug'] + '.zip')
        with zipfile.ZipFile(path) as z:
            m = json.loads(z.read('part.json')) if 'part.json' in z.namelist() else {}
            if not all(k in m for k in ('symbol', 'quality')):
                m = common.legacy_manifest(z, e)
        all_parts.append(common.as_part(m, path, e))
    for name in sorted(touched_shards):
        path = out / 'shards' / f'{name}.json'
        shard = json.loads(path.read_text())
        shard['entries'] = [e for e in entries.values() if shard_of[e['id']] == name]
        shard['generated_at'] = common.package._now()
        path.write_text(json.dumps(shard, ensure_ascii=False, indent=2))
    # Every count from the shards themselves, not only the ones touched here:
    # earlier additions left five of them stale (ic said 2,409 of 2,566).
    for s in manifest['shards']:
        path = out / s['file']
        shard = json.loads(path.read_text())
        if shard.get('count') != len(shard['entries']):
            shard['count'] = len(shard['entries'])
            path.write_text(json.dumps(shard, ensure_ascii=False, indent=2))
        s['count'] = shard['count']
    clusters = common.cluster.cluster_parts(all_parts)
    counts = common.cluster.write_clusters(clusters, out)
    common.package.write_search_index(all_parts, out / 'lib_search.sqlite', base, clusters,
                                      packaged_models={e['slug'] for e in entries.values() if e.get('has_3d')})
    with sqlite3.connect(out / 'lib_search.sqlite') as conn:
        conn.executemany('UPDATE part SET slug=?,download_url=? WHERE id=?',
                         [(e['slug'], e['download_url'], e['id']) for e in entries.values() if e.get('download_url')])
    visible = [p for p in all_parts if p.record.tier in {'A', 'B', 'G'}]
    manifest['generated_at'] = common.package._now()
    manifest['counts'] = {
        'total': len(entries), 'planner_visible': len(visible),
        'by_tier': dict(Counter(p.record.tier for p in all_parts)),
        'by_source': dict(Counter(p.record.source for p in all_parts)),
        'with_description': sum(bool(p.record.description) for p in visible),
        'with_footprint': sum(bool(p.record.footprint_name) for p in visible),
        'with_3d': sum(bool(e.get('has_3d')) for e in entries.values() if e['tier'] in {'A', 'B', 'G'}),
        'description_origin': dict(Counter(p.record.description_origin for p in visible))}
    manifest['clusters'] = {'index': 'clusters/index.json', 'count': len(clusters), 'by_class': counts}
    if not any(s['name'] == SOURCE_NAME for s in manifest['sources']):
        manifest['sources'].append({'name': SOURCE_NAME, 'license': LICENSE,
                                    'url': 'https://github.com/CaSauCoin/wireframe_lib/tree/main/sources/lcsc-parts',
                                    'rank': 55, 'commit': '', 'provenance': 'sources/lcsc-parts/PROVENANCE.json'})
        with (out / 'LICENSES.md').open('a') as f:
            f.write('\n## WireFrame LCSC parts\n\nSymbols and footprints served by LCSC/EasyEDA for an EXACT '
                    'manufacturer part number, each checked against that number and its own pads; see '
                    'sources/lcsc-parts/PROVENANCE.json for the LCSC code, maker and URL of every part. '
                    'Redistribution terms of this content are to be confirmed before a public release.\n')
    (out / 'lib_index.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--plan', action='store_true', help='print what would be added; write nothing')
    ap.add_argument('--contracts', type=Path, metavar='FILE',
                    help="wf-contract-research's local_contracts.json: datasheet-read contracts to lay over libcontract's")
    ap.add_argument('--emit-research', type=Path, metavar='FILE',
                    help='write the part list wf-contract-research reads (lib_id, symbol, datasheet, context) and stop; '
                         'parts --contracts already holds are left out')
    ap.add_argument('--uncovered', action='store_true',
                    help='with --emit-research: list the parts no libcontract family covers, of any class '
                         '(a crystal, a TVS, a buzzer by its maker\'s name), instead of the chips')
    ap.add_argument('--contracts-only', action='store_true',
                    help='lay --contracts over the LCSC parts already in the library and stop (research that finished '
                         'after the parts were added)')
    args = ap.parse_args()
    out = ROOT / 'Dist_Repo/v2'
    manifest = json.loads((out / 'lib_index.json').read_text())
    entries, shard_of = {}, {}
    for f in sorted((out / 'shards').glob('*.json')):
        for e in json.loads(f.read_text())['entries']:
            entries[e['id']] = e
            shard_of[e['id']] = f.stem
    shard_names = {f.stem for f in (out / 'shards').glob('*.json')}
    have = published_keys(out)

    records, provenance, classes = build_parts()
    done = researched_by_name(args.contracts)
    parts = enrich.enrich(records, use_ai=False)
    for p in parts:
        if p.record.id in classes:
            p.klass = classes[p.record.id]
            p.category_path = classify.category_path(p.klass)
    adding, skipped, deferred = [], [], []
    for p in parts:
        key = re.sub(r'[^a-z0-9]', '', p.record.name.lower().rstrip('+'))
        shard = p.klass.split('.')[0]
        if key in have or p.record.id in entries:
            skipped.append({'name': p.record.name, 'why': 'already in the library'})
        elif shard not in shard_names:
            deferred.append({'name': p.record.name, 'class': p.klass,
                             'why': f'class "{p.klass}" has no shard; filed nowhere rather than as unknown'})
        elif p.record.tier not in {'A', 'B'}:
            deferred.append({'name': p.record.name, 'class': p.klass, 'why': f'tier {p.record.tier}: {p.record.flags}'})
        else:
            adding.append(p)

    if args.emit_research:
        # The ids the library will carry, so a researched contract lands on the
        # part it was written for. Context is what the catalogue says the part
        # IS: the document a search finds is sometimes the chip inside a module.
        # Researched where the electrical requirements live — chips, modules,
        # power stages, displays. A diode, a TVS or a connector gets the class
        # contract every part of its kind in the library has; a datasheet read
        # adds little to it and costs a model call.
        researchable = ('ic', 'module', 'power', 'display')
        pending = adding + [p for p in parts if p.record.id in entries]
        if args.uncovered:
            covered = {c.lib_id for c in base_contracts(pending)}
            wanted = [p for p in pending if p.record.id not in covered]
        else:
            wanted = [p for p in pending if p.klass.split('.')[0] in researchable]
        listing = [{'lib_id': p.record.id, 'name': p.record.name, 'symbol': p.record.symbol_path,
                    'datasheet': p.record.datasheet, 'context': p.record.description}
                   for p in wanted if p.record.name not in done]
        args.emit_research.write_text(json.dumps(listing, indent=1, ensure_ascii=False) + '\n')
        print(f'{len(listing)} parts listed for research in {args.emit_research}')
        return
    if args.contracts_only:
        present = [p for p in parts if p.record.id in entries]
        print(f'{len(present)} LCSC parts in the library; contracts:', add_contracts(out, present, args.contracts))
        return
    print(f'{len(parts)} collected: {len(adding)} to add, {len(skipped)} already present, {len(deferred)} deferred')
    for p in adding:
        print(f'  + {p.record.name:22s} {p.klass:24s} tier {p.record.tier} {p.record.library:22s} '
              f'{p.record.description[:70]}')
    for d in deferred:
        print(f'  ~ {d["name"]:22s} {d["why"]}')
    if args.plan or not adding:
        return

    images, _ = common.preview.render(adding, out, workers=4, progress=print)
    missing = [p.record.name for p in adding
               if not all(images.get(common.package.part_slug(p), {}).get(k) for k in ('sym', 'fp'))]
    if missing:
        raise SystemExit(f'previews missing for {missing}; nothing was indexed')
    common.package.write_part_zips(adding, out, include_3d=False, previews=images, progress=print)
    touched = set()
    for p in adding:
        slug = common.package.part_slug(p)
        archive = out / 'parts' / f'{slug}.zip'
        entry = common.package.index_entry(p, manifest['base_url'], slug,
                                           hashlib.sha256(archive.read_bytes()).hexdigest(),
                                           images.get(slug, {}), manifest['parts_base_url'], set())
        entries[p.record.id] = entry
        shard_of[p.record.id] = p.klass.split('.')[0]
        touched.add(shard_of[p.record.id])
    before = sum(1 for _ in entries)
    update_indexes(out, entries, manifest, touched, shard_of)
    written = sum(len(json.loads(f.read_text())['entries']) for f in (out / 'shards').glob('*.json'))
    if written != before:
        raise SystemExit(f'the shards hold {written} entries where {before} were meant: refusing to go on')
    contract_stats = add_contracts(out, adding, args.contracts)
    print('contracts:', contract_stats)

    added_ids = {p.record.id for p in adding}
    (SOURCE / 'PROVENANCE.json').write_text(json.dumps({
        'schema': 1, 'license': LICENSE,
        'policy': 'Exact manufacturer part number only; the drawing\'s own part number checked; every '
                  'symbol pin on a pad of its own footprint. Collected with wf-lcsc-collect.',
        'parts': [x for x in provenance if x['id'] in added_ids]}, indent=2, ensure_ascii=False) + '\n')
    COLLECTION.mkdir(parents=True, exist_ok=True)
    (COLLECTION / 'catalog.json').write_text(json.dumps({
        'schema': 1, 'added': len(adding), 'after': len(entries),
        'by_class': dict(Counter(p.klass for p in adding)),
        'additions': [{'id': p.record.id, 'name': p.record.name, 'class': p.klass,
                       'slug': common.package.part_slug(p)} for p in adding],
        'skipped': skipped, 'deferred': deferred}, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'added': len(adding), 'after': len(entries),
                      'by_class': dict(Counter(p.klass for p in adding))}, indent=2))


if __name__ == '__main__':
    main()
