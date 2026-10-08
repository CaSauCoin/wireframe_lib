#!/usr/bin/env python3
"""How many parts of each kind the library holds — the list a board designer reaches for, counted.

Each kind is a class prefix and/or a pattern over name, description, keywords
and footprint, so the count is reproducible and a gap is a number, not an
impression. `--against REF` compares with the index of another git revision.

    python3 tools/coverage_report.py                 # counts now
    python3 tools/coverage_report.py --against HEAD~3
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARDS = ROOT / 'Dist_Repo/v2/shards'

# (group, kind, class regex or '', text regex or '')
KINDS: list[tuple[str, str, str, str]] = [
    ('Mechanical', 'mounting hole', r'^mechanical\.mounting_hole', r''),
    ('Mechanical', 'SMT standoff / nut / spacer', r'^mechanical\.standoff', r''),
    ('Mechanical', 'fiducial', r'^mechanical\.fiducial', r''),
    ('Mechanical', 'test point', r'^mechanical\.testpoint', r''),
    ('Mechanical', 'solder jumper / net tie', r'^mechanical\.(jumper|net_tie)', r''),
    ('Mechanical', 'heatsink', r'^mechanical\.heatsink', r''),
    ('Mechanical', 'shield can / clip', r'^mechanical\.shield', r''),
    ('Mechanical', 'wire solder pad (wire joint)', r'^connector\.wire', r''),
    ('Memory / SoC', 'SRAM / PSRAM', r'^ic\.memory', r'\bSRAM\b|PSRAM|APS6404|IS6[12]|23LC'),
    ('Memory / SoC', 'DDR / LPDDR / SDRAM', r'^ic\.memory', r'DDR|SDRAM|\bDRAM'),
    ('Memory / SoC', 'eMMC / NAND', r'^ic\.memory', r'eMMC|NAND'),
    ('Memory / SoC', 'SPI NOR flash / EEPROM / FRAM', r'^ic\.memory', r'NOR|W25Q|EEPROM|24C|FRAM|FM2[45]'),
    ('Memory / SoC', 'application SoC / MPU', r'^ic\.(mcu|cpu)', r'Allwinner|Rockchip|RK3\d|T113|V3s|F1C|i\.?MX|STM32MP|SSD20|RV110|SG200|AM335'),
    ('Memory / SoC', 'SoC PMIC', r'^ic\.power', r'AXP\d|RK8\d\d|PMIC'),
    ('Display', 'OLED', r'^display', r'OLED|SSD13|SH110'),
    ('Display', 'TFT / LCD graphic', r'^display', r'TFT|LCD|ST77|ILI9|GC9A01'),
    ('Display', 'round display', r'^display', r'round|circular|GC9A01'),
    ('Display', 'e-paper', r'^display', r'e-?paper|EPD'),
    ('Display', '7-segment, 1 digit', r'^display', r'7.?seg|segment.*1.?digit|single.?digit'),
    ('Display', '7-segment, 2-4 digit', r'^display', r'(2|3|4).?digit|dual|quad|clock'),
    ('Display', 'LED dot matrix / bar', r'^display', r'matrix|bar.?graph|dot'),
    ('LED', 'RGB / addressable', r'', r'RGB|WS281|SK68|APA10|SK98'),
    ('Audio', 'speaker', r'^electromechanical\.speaker', r''),
    ('Audio', 'buzzer', r'^electromechanical\.buzzer', r''),
    ('Audio', 'microphone', r'', r'microphone|\bMEMS mic|electret'),
    ('Audio', 'audio jack', r'^connector\.audio', r''),
    ('Audio', 'audio amp / codec / DAC', r'^ic\.analog\.audio', r''),
    ('Buttons', 'tactile 2-pin', r'^electromechanical\.switch', r'SW_Push\b|tactile|SPST'),
    ('Buttons', 'DIP switch', r'^electromechanical\.switch', r'DIP'),
    ('Buttons', 'slide / toggle / rocker', r'^electromechanical\.switch', r'slide|toggle|rocker|SPDT|DPDT'),
    ('Ports', 'HDMI (A / mini / micro)', r'^connector', r'HDMI'),
    ('Ports', 'USB-C', r'^connector', r'USB.?C|Type.?C'),
    ('Ports', 'micro USB', r'^connector', r'micro.?USB|USB_Micro'),
    ('Ports', 'DC barrel jack', r'^connector', r'barrel|DC.?jack|DC-0\d\d'),
    ('Ports', 'battery holder', r'^power\.battery', r''),
    ('Ports', 'card socket (SD / SIM)', r'^connector\.card', r''),
    ('Ports', 'RJ45', r'^connector|^ic\.interface\.ethernet', r'RJ45|RJ-45|8P8C'),
    ('Ports', 'terminal block', r'^connector', r'terminal'),
    ('Modules', 'dev board / carrier', r'^module\.(devboard|compute)', r''),
    ('Modules', 'wireless module', r'^module\.wireless', r''),
]


def load(ref: str | None) -> list[dict]:
    if not ref:
        return [e for f in sorted(SHARDS.glob('*.json')) for e in json.loads(f.read_text())['entries']]
    out = []
    names = subprocess.run(['git', '-C', str(ROOT), 'ls-tree', '--name-only', ref, 'Dist_Repo/v2/shards/'],
                           capture_output=True, text=True).stdout.split()
    for name in names:
        text = subprocess.run(['git', '-C', str(ROOT), 'show', f'{ref}:{name}'], capture_output=True, text=True).stdout
        out += json.loads(text)['entries']
    return out


def count(entries: list[dict]) -> list[int]:
    out = []
    for _, _, klass, pattern in KINDS:
        k, p = re.compile(klass) if klass else None, re.compile(pattern, re.I) if pattern else None
        out.append(sum(1 for e in entries
                       if (not k or k.search(e.get('class', '')))
                       and (not p or p.search(' '.join([e.get('name', ''), e.get('description', ''),
                                                        ' '.join(e.get('keywords') or []), e.get('footprint', '')])))))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--against', help='a git revision of wireframe_lib to compare with')
    ap.add_argument('--tsv', action='store_true')
    args = ap.parse_args()
    now = count(load(None))
    then = count(load(args.against)) if args.against else None
    group = ''
    for i, (g, kind, _, _) in enumerate(KINDS):
        if args.tsv:
            print('\t'.join([g, kind, *(str(then[i]),) * bool(then), str(now[i])]))
            continue
        if g != group:
            print(f'\n{g}')
            group = g
        before = f'{then[i]:5d} -> ' if then else ''
        flag = '  <- none' if now[i] == 0 else ('  <- few' if now[i] < 5 else '')
        print(f'  {kind:34s} {before}{now[i]:5d}{flag}')


if __name__ == '__main__':
    main()
