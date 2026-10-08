#!/usr/bin/env python3
"""Make `has_3d` mean what the app gets: a model file inside the part zip.

The shards say `has_3d: true` for parts whose zip holds no model at all. The
heuristic 3D passes (`auto_match_3d_packages_and_fix_viewer.py`,
`comprehensive_3d_audit_and_fix.py`, ...) set the flag whenever a *name* matched
a model list, and the model they found went to `3dmodels/` for the web viewer —
never into the zip the app installs. Audit of 2026-10-08: 1,806 rows flagged with
a model nowhere, 417 with a viewer-only model. The app reads `has_3d` for its 3D
badge (`Repo_Manager.cpp`), so every one of those promised a model the install
does not deliver.

What this pass does, per shard entry:

  1. the zip already holds a .step/.stp/.wrl          -> has_3d true
  2. the zip's footprint declares `(model ...)` and that file exists in the local
     kicad-packages3D checkout or the part's own source repo -> pack it, has_3d true
  3. otherwise                                         -> has_3d false

Only the footprint's OWN declared model is trusted. A family guess (an inductor
given a capacitor body, a QFN-32 given a QFN-28) is the bug this replaces.
`step_file` (web viewer only) is left alone.

The report (`collections/3d/report.json`) lists every declared model that
kicad-packages3D does not have, grouped by `.3dshapes` library — those need the
KiCad CadQuery generator or a manufacturer STEP, not a rename.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_EXT = ('.step', '.stp', '.wrl')


def zip_model(names: list[str]) -> str:
    return next((n for n in names if n.lower().endswith(MODEL_EXT)), '')


def declared_models(fp_text: str) -> list[str]:
    return [re.sub(r'^\$\{[^}]+\}/?', '', m) for m in re.findall(r'\(model\s+"?([^"\s)]+)', fp_text)]


_STEMS: dict[Path, dict[str, list[Path]]] = {}


def _stems(root: Path) -> dict[str, list[Path]]:
    """basename stem -> files, per repo; built once."""
    if root not in _STEMS:
        index: dict[str, list[Path]] = defaultdict(list)
        for dirpath, _dirs, files in os.walk(root):
            if '/.git' in dirpath:
                continue
            for f in files:
                if f.lower().endswith(MODEL_EXT):
                    index[os.path.splitext(f)[0]].append(Path(dirpath) / f)
        _STEMS[root] = index
    return _STEMS[root]


def find_model(declared: list[str], roots: list[Path]) -> Path | None:
    """The declared model, looked up in kicad-packages3D and in the part's own
    source repo (SparkFun, JLCPCB, Espressif ship theirs beside the footprints,
    declared relative to the repo: `${KIPRJMOD}/3dmodels/...`). A path that does
    not resolve may still be the same file under another folder of the SAME
    repo — accepted only when that basename is unique there."""
    for rel in declared:
        rel = re.sub(r'^\$\{?[A-Za-z0-9_]+\}?/?', '', rel)
        for root in roots:
            for suffix in MODEL_EXT:
                candidate = (root / rel).with_suffix(suffix)
                if candidate.exists():
                    return candidate
        stem = Path(rel).stem
        for root in roots:
            hits = _stems(root).get(stem, [])
            if len(hits) == 1:
                return hits[0]
    return None


def add_model(path: Path, model: Path, repos: Path) -> None:
    """Rewrite the zip with the model added and part.json pointing at it."""
    tmp = path.with_suffix('.zip.tmp')
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == 'part.json':
                m = json.loads(data)
                m['model3d'] = {'file': model.name, 'format': model.suffix.lstrip('.'),
                                'origin': model.relative_to(repos).parts[0], 'resolved_by': 'declared_by_footprint',
                                'upstream': str(model.relative_to(repos))}
                data = json.dumps(m, ensure_ascii=False, indent=1).encode()
            dst.writestr(info, data)
        dst.write(model, model.name)
    tmp.replace(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', type=Path, default=ROOT / 'Dist_Repo/v2')
    ap.add_argument('--repos', type=Path, default=Path.home() / '.wireframe/library_cache/repos')
    ap.add_argument('--dry-run', action='store_true', help='report only; write nothing')
    args = ap.parse_args()
    out, packages3d = args.out, args.repos / 'kicad-packages3D'
    if not packages3d.is_dir():
        raise SystemExit(f'kicad-packages3D not found at {packages3d}')

    outcome = Counter()
    flipped = Counter()
    missing_upstream: dict[str, list[str]] = defaultdict(list)
    packed: list[dict] = []
    shards = {f: json.loads(f.read_text()) for f in sorted((out / 'shards').glob('*.json'))}
    for shard_path, shard in shards.items():
        for e in shard['entries']:
            path = out / 'parts' / f"{e.get('slug', '')}.zip"
            before = bool(e.get('has_3d'))
            if not e.get('slug') or not path.exists():
                outcome['no_zip'] += 1
                continue
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                fp = next((n for n in names if n.endswith('.kicad_mod')), '')
                declared = declared_models(z.read(fp).decode('utf-8', 'replace')) if fp else []
                source = e.get('source', '')
            if zip_model(names):
                now = True
                outcome['already_in_zip'] += 1
            else:
                roots = [packages3d] + ([args.repos / source] if source and (args.repos / source).is_dir() else [])
                model = find_model(declared, roots)
                if model:
                    now = True
                    outcome['packed_from_kicad'] += 1
                    packed.append({'id': e['id'], 'model': str(model.relative_to(args.repos))})
                    if not args.dry_run:
                        add_model(path, model, args.repos)
                        e['hash'] = hashlib.sha256(path.read_bytes()).hexdigest()
                else:
                    now = False
                    if declared:
                        outcome['declared_but_not_in_kicad'] += 1
                        rel = declared[0]
                        missing_upstream[rel.split('/')[0] if '/' in rel else '(no library)'].append(e['id'])
                    else:
                        outcome['footprint_declares_no_model'] += 1
            if before != now:
                flipped[f'{before}->{now}'] += 1
            e['has_3d'] = now

    total_3d = sum(e['has_3d'] for s in shards.values() for e in s['entries'] if 'has_3d' in e)
    report = {
        'schema': 1, 'outcome': dict(outcome), 'flag_changes': dict(flipped), 'has_3d_after': total_3d,
        'packed': packed,
        'missing_upstream_by_library': {k: len(v) for k, v in sorted(missing_upstream.items(), key=lambda kv: -len(kv[1]))},
        'missing_upstream': dict(missing_upstream),
        'note': 'missing_upstream = the footprint names a model kicad-packages3D does not contain '
                '(checked against the repo and an installed KiCad). Needs the CadQuery generator or a '
                'manufacturer STEP with a redistributable licence.',
    }
    print(json.dumps({k: report[k] for k in ('outcome', 'flag_changes', 'has_3d_after')}, indent=2))
    print('missing upstream, top libraries:', list(report['missing_upstream_by_library'].items())[:12])
    if args.dry_run:
        return

    for shard_path, shard in shards.items():
        shard_path.write_text(json.dumps(shard, ensure_ascii=False, indent=2))
    truth = {e['id']: int(bool(e.get('has_3d'))) for s in shards.values() for e in s['entries'] if 'id' in e}
    with sqlite3.connect(out / 'lib_search.sqlite') as conn:
        conn.executemany('UPDATE part SET has_3d=? WHERE id=?', [(v, k) for k, v in truth.items()])
    manifest_path = out / 'lib_index.json'
    manifest = json.loads(manifest_path.read_text())
    visible = [e for s in shards.values() for e in s['entries'] if e.get('tier') in {'A', 'B', 'G'}]
    manifest.setdefault('counts', {})['with_3d'] = sum(bool(e.get('has_3d')) for e in visible)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    (ROOT / 'collections/3d').mkdir(parents=True, exist_ok=True)
    (ROOT / 'collections/3d/report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
