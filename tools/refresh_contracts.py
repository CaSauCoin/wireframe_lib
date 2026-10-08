#!/usr/bin/env python3
"""Rebuild the contracts of every part of one source already in the library.

For when the contract rules changed after the parts went in — libcontract
gained a family, or a datasheet research round finished. The parts are read
back from their own zips, the class contract is built the way add_lcsc_parts
builds it, and a datasheet-read contract is laid over it where one exists.

    python3 tools/refresh_contracts.py --source wireframe-kicad-families
    python3 tools/refresh_contracts.py --source wireframe-lcsc-parts \
        --contracts ~/.wireframe/library_cache/lcsc/research/contracts/local_contracts.json
"""
from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

import add_ac_packages as common
import add_lcsc_parts as lcsc

OUT = lcsc.ROOT / 'Dist_Repo/v2'


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--source', required=True)
    ap.add_argument('--contracts', type=Path, help="wf-contract-research's local_contracts.json")
    args = ap.parse_args()
    parts = []
    for f in sorted((OUT / 'shards').glob('*.json')):
        for e in json.loads(f.read_text())['entries']:
            if e.get('source') != args.source:
                continue
            path = OUT / 'parts' / f"{e['slug']}.zip"
            with zipfile.ZipFile(path) as z:
                m = json.loads(z.read('part.json'))
            part = common.as_part(m, path, e)
            part.klass = e['class']
            parts.append(part)
    print(f'{len(parts)} parts of {args.source}; contracts:', lcsc.add_contracts(OUT, parts, args.contracts))


if __name__ == '__main__':
    main()
