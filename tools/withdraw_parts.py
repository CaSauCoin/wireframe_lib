#!/usr/bin/env python3
"""Take parts out of the published index whose drawings are wrong, each with the measurement that says so.

Three generators of 2026-09-22..24 (add_popular_modules_packages.py,
add_board_outline_packages.py, add_mechanical_packages.py) drew parts from a
description rather than from a drawing, and the library published them at
tier A, so the planner picks them:

  * connectors on a 2.54 mm grid whatever the series: JST XH (2.50 mm), KF301
    (5.0 mm), Molex Micro-Fit (3.0 mm); JST PH SMD without its two mounting
    pads;
  * breakout modules as a bare header grid — the A4988 carrier's rows 7.62 mm
    apart where Pololu's are 12.7 mm — and two SMD castellated ESP32 modules as
    THT DIPs (ESP32-S3-WROOM-1 with 20 pins; the real one has 41 pads);
  * chips as generic SOT/SOIC/TO-263 shapes, each a second copy of a real part
    the library already carries (KiCad, Espressif, LCSC);
  * board outlines with no cited drawing: the Raspberry Pi HAT's 40-pin header
    down the middle of the board where the HAT spec puts it along the top
    edge, carriers for Pico/BluePill/ESP32 DevKit at invented sizes. WireFrame's
    board templates (AI/Pcb/AI_Board_Templates: rpi-hat, rpi-uhat,
    arduino-uno-shield, fpv-*) are built from cited drawings and are the one
    answer to where a HAT's holes are;
  * two NPTH holes whose symbol has a pin 1 no pad carries;
  * curated-maker's 39 parts, every pad a 1.7 mm through-hole circle whatever
    the package: a SOT-23's three pads overlap, an SMD crystal is drilled.

A withdrawn part leaves the shards, the search index and the contract pack;
its zip stays in parts/ (an installed copy keeps working), and
collections/withdrawn.json records what it was, why, what was measured, and
the real part to use instead where the library has one.

    python3 tools/withdraw_parts.py --plan     # what would go, and why
    python3 tools/withdraw_parts.py            # do it
"""
from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path

import add_lcsc_parts as lcsc

ROOT = lcsc.ROOT
OUT = ROOT / 'Dist_Repo/v2'
RECORD = ROOT / 'collections/withdrawn.json'

BOARDS = ('the outline has no cited drawing (the Raspberry Pi HAT here puts the 40-pin header down the middle; '
          'the HAT spec runs it along the top edge). WireFrame\'s board templates (rpi-hat, rpi-uhat, '
          'arduino-uno-shield, fpv-*) come from cited drawings; use /board or edit_board_stack')
MODULE = 'a breakout module drawn as a bare 2.54 mm header grid, not the module\'s board'
CHIP = 'a generic package drawn from a description, a second copy of a real part the library carries'

# id prefix or exact id -> (reason, regex naming the real part to use instead)
WITHDRAW: list[tuple[str, str, str]] = [
    ('wireframe-board-outlines/', BOARDS, ''),
    ('wireframe-curated-maker/Arduino_UNO_R4_', 'the four mounting holes are a symmetric rectangle; the UNO\'s are not '
     '(KiCad Module:Arduino_UNO_R3, the same shield layout: (-4.83, 0), (-3.56, 48.26), (47.24, 5.08), '
     '(47.24, 33.02) from the header) and the header rows are 50.8 mm apart where the UNO\'s are 48.26',
     r'^Arduino_UNO_R3$'),
    ('wireframe-curated-maker/Arduino_Mega_2560', 'the UNO-pattern holes are mirrored top to bottom against KiCad\'s '
     'Arduino_UNO_R3 — a board seen from underneath; a shield laid on it would be mirrored', r'^Arduino_Mega'),
    ('wireframe-curated-maker/Arduino_Due', 'the same mirrored outline as the Mega 2560 entry', r'^Arduino_Due'),
    ('source:curated-maker', 'every pad drawn as a 1.7 mm through-hole circle whatever the package — a SOT-23\'s three '
     'pads 0.95 mm apart overlap, a USB-C receptacle\'s sixteen sit 0.5 mm apart — and the 3D model is a typed box',
     ''),
    ('wireframe-popular-packages/Connectors/Conn_JST_XH_', 'pitch 2.54 mm; JST XH is 2.50 mm', r'^B\dB-XH'),
    ('wireframe-popular-packages/Connectors/Conn_JST_PH_', 'no mounting pads; JST PH SMD has two', r'^S\dB-PH-SM4|^B\dB-PH'),
    ('wireframe-popular-packages/Connectors/Conn_Molex_MicroFit_', 'pitch 2.54 mm; Micro-Fit 3.0 is 3.00 mm', r'Micro-?Fit|43045|43650'),
    ('wireframe-popular-packages/Connectors/Conn_Terminal_Block_KF301_', 'pitch 2.54 mm; KF301 is 5.0 mm', r'KF301|TerminalBlock.*P5\.0'),
    ('wireframe-popular-packages/Connectors/Conn_Terminal_Block_KF128_', 'pitch 2.54 mm; KF128 is 5.08 mm', r'KF128|TerminalBlock.*P5\.08'),
    ('wireframe-popular-packages/Wireless & RF/RF_ESP32_S3_WROOM_1', 'an SMD castellated module drawn as a 20-pin THT DIP; '
     'the ESP32-S3-WROOM-1 has 41 pads', r'^ESP32-S3-WROOM-1$'),
    ('wireframe-popular-packages/Wireless & RF/RF_ESP32_C3_WROOM_02', 'an SMD castellated module drawn as a 12-pin THT DIP; '
     'the ESP32-C3-WROOM-02 has 19 pads', r'^ESP32-C3-WROOM-02$'),
    ('wireframe-popular-packages/Wireless & RF/RF_SX1262_LoRa_Module', MODULE, r'^SX1262'),
    ('wireframe-popular-packages/Wireless & RF/RF_NEO6M_GPS_Module', MODULE, r'NEO-?6M'),
    ('wireframe-popular-packages/Motor Drivers/Driver_A4988_Stepper_Carrier', MODULE + '; rows 7.62 mm apart, '
     'Pololu\'s carrier has them 12.7 mm apart', r'^A4988'),
    ('wireframe-popular-packages/Motor Drivers/Driver_TMC2209_Silent_Carrier', MODULE, r'^TMC2209'),
    ('wireframe-popular-packages/Motor Drivers/Driver_TB6612FNG_Dual_Motor', MODULE, r'^TB6612'),
    ('wireframe-popular-packages/Motor Drivers/Driver_ULN2003A_Darlington', CHIP, r'^ULN2003'),
    ('wireframe-popular-packages/Sensors/', MODULE, ''),
    ('wireframe-popular-packages/Audio/Audio_PAM8403_Stereo_Amp', CHIP, r'PAM8403'),
    ('wireframe-popular-packages/Audio/', MODULE, ''),
    ('wireframe-popular-packages/Power/Power_TP4056_TypeC_Module', MODULE, r'^TP4056'),
    ('wireframe-popular-packages/Power/', CHIP, ''),
    ('wireframe-mechanical-packages/Mechanical/Mechanical_MountingHole_M5_5.3mm_NPTH',
     'the symbol has a pin 1 that no pad carries (an NPTH hole has no pad number)', r'^MountingHole_5\.3mm_M5$'),
    ('wireframe-mechanical-packages/Mechanical/Mechanical_ToolingHole_1.5mm_NPTH',
     'the symbol has a pin 1 that no pad carries (an NPTH hole has no pad number)', r'^MountingHole_1\.5mm$'),
]
# What the generic power-chip rows were copies of, for the "instead" field.
INSTEAD_BY_NAME = {
    'Power_AP2112K_3.3V_LDO': r'^AP2112K-3\.3', 'Power_DW01A_Protection': r'^DW01A',
    'Power_FS8205A_Dual_NMOS': r'^FS8205A', 'Power_LM2596_Regulator_TO263': r'^LM2596S-',
    'Power_MP1584EN_Buck': r'^MP1584', 'Power_MT3608_Boost': r'^MT3608',
    'Power_TP4056_Charger_SOP8': r'^TP4056', 'Power_XL4015_Buck_Regulator_TO263': r'^XL4015',
    'Sensor_BME280_Module': r'^BME280$', 'Sensor_SHT30_Module': r'^SHT3[01]-DIS$',
    'Sensor_IMU_MPU6050_GY521': r'^MPU-6050$', 'Sensor_VL53L0X_ToF': r'^VL53L0',
    'Sensor_BH1750_Light': r'^BH1750', 'Sensor_DS18B20_1Wire': r'^DS18B20$',
    'Audio_MAX98357A_I2S_Amp': r'^MAX98357', 'Audio_PCM5102A_I2S_DAC': r'^PCM510',
}


def rule_for(entry: dict) -> tuple[str, str] | None:
    """An id prefix, or `source:<name>` — curated-maker's ids start with
    wireframe-curated-maker/, like the 55 parts of another generator kept here."""
    for prefix, reason, instead in WITHDRAW:
        if prefix.startswith('source:') and entry.get('source') == prefix[7:] or \
                not prefix.startswith('source:') and entry['id'].startswith(prefix):
            return reason, instead
    return None


def measured(out: Path, entry: dict) -> dict:
    """What the zip actually holds: pads, their kinds, the pitch, the box."""
    path = out / 'parts' / f"{entry['slug']}.zip"
    if not path.exists():
        return {}
    with zipfile.ZipFile(path) as z:
        fp = next((n for n in z.namelist() if n.endswith('.kicad_mod')), '')
        text = z.read(fp).decode('utf-8', 'replace') if fp else ''
    pads = re.findall(r'\(pad\s+"?([^"\s]*)"?\s+(\w+)\s+\w+\s+\(at ([-\d.]+) ([-\d.]+)', text)
    pts = [(float(x), float(y)) for n, _, x, y in pads if n]
    steps = sorted({round(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** .5, 2) for a, b in zip(pts, pts[1:])})
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return {'pads': len(pads), 'kinds': dict(Counter(k for _, k, _, _ in pads)), 'pitches_mm': steps[:4],
            'pad_span_mm': [round(max(xs) - min(xs), 2), round(max(ys) - min(ys), 2)] if pts else []}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--plan', action='store_true', help='print what would be withdrawn; write nothing')
    args = ap.parse_args()
    out = OUT
    manifest = json.loads((out / 'lib_index.json').read_text())
    entries, shard_of = {}, {}
    for f in sorted((out / 'shards').glob('*.json')):
        for e in json.loads(f.read_text())['entries']:
            entries[e['id']] = e
            shard_of[e['id']] = f.stem

    gone = []
    for entry_id, e in entries.items():
        rule = rule_for(e)
        if not rule:
            continue
        reason, instead_pattern = rule
        instead_pattern = instead_pattern or INSTEAD_BY_NAME.get(e['name'], '')
        instead = sorted(x['id'] for x in entries.values()
                         if instead_pattern and x['id'] != entry_id and not rule_for(x)
                         and re.search(instead_pattern, x['name']))[:5]
        gone.append({'id': entry_id, 'name': e['name'], 'class': e.get('class', ''), 'shard': shard_of[entry_id],
                     'slug': e['slug'], 'reason': reason, 'measured': measured(out, e), 'instead': instead})

    for g in gone:
        print(f"  - {g['name'][:40]:40s} {g['reason'][:70]:70s} instead: {', '.join(i.split('/')[-1] for i in g['instead'][:2]) or '-'}")
    print(f'{len(gone)} to withdraw of {len(entries)}: {dict(Counter(g["id"].split("/")[0] for g in gone))}')
    if args.plan or not gone:
        return

    for g in gone:
        del entries[g['id']]
    before = len(entries)
    lcsc.update_indexes(out, entries, manifest, {g['shard'] for g in gone}, shard_of)
    written = sum(len(json.loads(f.read_text())['entries']) for f in (out / 'shards').glob('*.json'))
    if written != before:
        raise SystemExit(f'the shards hold {written} entries where {before} were meant')

    # The contract pack: a withdrawn part has nothing to check.
    cdir = out / 'contracts'
    ids = {g['id'] for g in gone}
    for f in sorted((cdir / 'shards').glob('*.json')):
        shard = json.loads(f.read_text())
        kept = {k: v for k, v in shard['parts'].items() if k not in ids}
        if len(kept) != len(shard['parts']):
            shard['parts'], shard['count'] = kept, len(kept)
            lcsc.contract_pack._compact(shard, f)
    pack_manifest = json.loads((cdir / 'contracts.json').read_text())
    pack_manifest['by_name'] = {k: v for k, v in pack_manifest['by_name'].items() if v not in ids}
    pack: dict[str, dict] = {}
    for s in pack_manifest['shards']:
        members = json.loads((cdir / s['file']).read_text())['parts']
        s['count'] = len(members)
        pack.update(members)
    pack_manifest['counts'] = {
        'parts': len(pack),
        'clauses': sum(len(p.get('companions', [])) + len(p.get('rules', [])) for p in pack.values()),
        'pins': sum(len(p.get('pins', [])) for p in pack.values())}
    lcsc.contract_pack._compact(pack_manifest, cdir / 'contracts.json')
    index = json.loads((cdir / 'contract_index.json').read_text())
    index['parts'] = [r for r in index['parts'] if r['lib_id'] not in ids]
    index['counts']['parts'] = len(index['parts'])
    (cdir / 'contract_index.json').write_text(json.dumps(index, indent=2, ensure_ascii=False) + '\n')

    record = json.loads(RECORD.read_text()) if RECORD.exists() else {'schema': 1, 'withdrawn': []}
    known = {w['id'] for w in record['withdrawn']}
    record['withdrawn'] += [{**g, 'date': date.today().isoformat()} for g in gone if g['id'] not in known]
    RECORD.write_text(json.dumps(record, indent=2, ensure_ascii=False) + '\n')
    print(f'withdrawn {len(gone)}; {before} parts remain; record in {RECORD.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
