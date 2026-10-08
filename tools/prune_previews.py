#!/usr/bin/env python3
"""Delete preview images no shard entry points at.

`previews/` rides the git channel: the app shows `preview_sym`/`preview_fp`
from raw.githubusercontent, so every image a part uses must be committed. The
ones no part uses were never cleaned up — the 63k catalogue the 2026-09-18
rebuild replaced left 100,642 of them (1.33 GB, four times the 20,264 in use),
and a superseded entry (add_card_packages, add_usb_packages) leaves its two.

    python3 tools/prune_previews.py            # count only
    python3 tools/prune_previews.py --delete   # remove them from the tree

Only files under previews/ that no `preview_sym`/`preview_fp` in any shard
names are touched; a referenced image that is missing is reported, not made.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'Dist_Repo' / 'v2'


def referenced(out: Path) -> set[str]:
    names: set[str] = set()
    for path in sorted((out / 'shards').glob('*.json')):
        for entry in json.loads(path.read_text())['entries']:
            for key in ('preview_sym', 'preview_fp'):
                if entry.get(key):
                    names.add(entry[key].rsplit('/', 1)[-1])
    return names


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--out', type=Path, default=ROOT)
    ap.add_argument('--delete', action='store_true', help='remove the unreferenced images')
    args = ap.parse_args()
    used = referenced(args.out)
    files = {p.name: p for p in (args.out / 'previews').iterdir() if p.is_file()}
    orphans = sorted(set(files) - used)
    missing = sorted(used - set(files))
    size = sum(files[n].stat().st_size for n in orphans)
    print(f'{len(files)} images, {len(used)} referenced, {len(orphans)} unreferenced ({size / 1e6:.0f} MB), '
          f'{len(missing)} referenced but missing')
    for name in missing[:20]:
        print('  missing:', name)
    if args.delete:
        for name in orphans:
            files[name].unlink()
        print(f'deleted {len(orphans)}')


if __name__ == '__main__':
    main()
