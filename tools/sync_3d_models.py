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
given a capacitor body, a QFN-32 given a QFN-28) is the bug this replaces. A
VRML that is one hand-typed Box is a placeholder, not a model: it stays in the
zip, and has_3d says false.

`step_file` is dropped: it named a guessed file in `3dmodels/` for the old web
viewer, a second answer to "what is this part's 3D" that disagreed with the
zip for 2,400 parts. `preview_viewer.html` now reads the model out of the zip.

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
STEP_EXT = ('.step', '.stp')


def is_placeholder(data: bytes) -> bool:
    """A VRML whose only geometry is one Box: a body envelope typed in by hand,
    not a model. Forty curated-maker parts shipped one (an orange box roughly
    the size of the body, 150 bytes) and were badged 3D for it."""
    text = data.decode('latin-1')
    shapes = re.findall(r'geometry\s+(\w+)', text)
    return text.startswith('#VRML') and bool(shapes) and set(shapes) == {'Box'}


def zip_model(z: zipfile.ZipFile, declared: list[str]) -> str:
    """The file in the zip the app would load for the footprint's (model ...):
    the same file name, or for a declared .wrl the .step/.stp of that name —
    `ResolveModelPath` in Model3D/Pcb3D_Viewer.cpp. A model the footprint does
    not name is never loaded however well it fits: 959 zips carried one (picked
    by fab outline, courtyard or name — a ferrite bead given a capacitor body)
    and were badged 3D for it. A placeholder box does not count either."""
    names = {os.path.basename(n): n for n in z.namelist()}
    for rel in declared:
        stem, ext = os.path.splitext(os.path.basename(rel))
        for name in [stem + ext] + ([stem + '.step', stem + '.stp'] if ext.lower() == '.wrl' else []):
            info = z.getinfo(names[name]) if name in names else None
            if info and not (info.file_size <= 4096 and is_placeholder(z.read(info.filename))):
                return info.filename
    return ''


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


def packed_name(declared_rel: str, model: Path) -> str:
    """The name the app will look for: the declared file name, or for a
    declared .wrl the .step of that name. Packing under the upstream file's own
    name lost Espressif's `ESP32-C6-MINI-1.STEP` against a footprint asking for
    `.step` — found on macOS, missing on Linux, and packed twice by the next
    run. '' when the model found cannot sit under a name the app would load."""
    stem, ext = os.path.splitext(os.path.basename(declared_rel))
    ext, found = ext.lower(), model.suffix.lower()
    if ext == found or (ext in STEP_EXT and found in STEP_EXT):
        return os.path.basename(declared_rel)
    if ext == '.wrl' and found in STEP_EXT:
        return stem + '.step'
    return ''


def find_model(declared: list[str], roots: list[Path]) -> tuple[Path, str] | None:
    """The declared model, looked up in kicad-packages3D and in the part's own
    source repo (SparkFun, JLCPCB, Espressif ship theirs beside the footprints,
    declared relative to the repo: `${KIPRJMOD}/3dmodels/...`), and the name to
    pack it under. A path that does not resolve may still be the same file
    under another folder of the SAME repo — accepted only when that basename is
    unique there."""
    for declared_rel in declared:
        rel = re.sub(r'^\$\{?[A-Za-z0-9_]+\}?/?', '', declared_rel)
        found = None
        for root in roots:
            for suffix in MODEL_EXT:
                candidate = (root / rel).with_suffix(suffix)
                if candidate.exists():
                    found = found or candidate
        if not found:
            for root in roots:
                hits = _stems(root).get(Path(rel).stem, [])
                if len(hits) == 1:
                    found = found or hits[0]
        if found and packed_name(rel, found):
            return found, packed_name(rel, found)
    return None


def add_model(path: Path, model: Path, name: str, repos: Path) -> None:
    """Rewrite the zip with the model under `name` and part.json pointing at
    it; a member of the same name in another letter case is replaced."""
    tmp = path.with_suffix('.zip.tmp')
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            if info.filename.lower() == name.lower():
                continue
            data = src.read(info.filename)
            if info.filename == 'part.json':
                m = json.loads(data)
                m['model3d'] = {'file': name, 'format': model.suffix.lower().lstrip('.'),
                                'origin': model.relative_to(repos).parts[0], 'resolved_by': 'declared_by_footprint',
                                'upstream': str(model.relative_to(repos))}
                data = json.dumps(m, ensure_ascii=False, indent=1).encode()
            dst.writestr(info, data)
        dst.write(model, name)
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
    unnamed: list[dict] = []
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
                in_zip = zip_model(z, declared)
                others = [] if in_zip else [n for n in names if n.lower().endswith(MODEL_EXT)]
                placeholder = bool(others) and all(
                    z.getinfo(n).file_size <= 4096 and is_placeholder(z.read(n)) for n in others)
                stray = bool(others) and not placeholder
            # The viewer reads the model out of the zip too, so a second name
            # for "the 3D of this part" has nothing left to answer.
            if e.pop('step_file', None) is not None:
                outcome['step_file_dropped'] += 1
            if in_zip:
                now = True
                outcome['already_in_zip'] += 1
            else:
                # The part's own repo is where a placeholder came from.
                own = source and not placeholder and (args.repos / source).is_dir()
                roots = [packages3d] + ([args.repos / source] if own else [])
                hit = find_model(declared, roots)
                if hit:
                    model, name = hit
                    now = True
                    outcome['packed_from_kicad'] += 1
                    packed.append({'id': e['id'], 'model': str(model.relative_to(args.repos)), 'as': name})
                    if not args.dry_run:
                        add_model(path, model, name, args.repos)
                        e['hash'] = hashlib.sha256(path.read_bytes()).hexdigest()
                else:
                    now = False
                    if placeholder:
                        outcome['placeholder_box_only'] += 1
                    elif stray:
                        outcome['model_the_footprint_does_not_name'] += 1
                        unnamed.append({'id': e['id'], 'declared': [os.path.basename(d) for d in declared],
                                        'in_zip': [os.path.basename(n) for n in others]})
                    elif declared:
                        outcome['declared_but_not_in_kicad'] += 1
                        rel = declared[0]
                        missing_upstream[rel.split('/')[0] if '/' in rel else '(no library)'].append(e['id'])
                    else:
                        outcome['footprint_declares_no_model'] += 1
            if before != now:
                flipped[f'{before}->{now}'] += 1
            e['has_3d'] = now

    total_3d = sum(e['has_3d'] for s in shards.values() for e in s['entries'] if 'has_3d' in e)
    # What earlier runs packed is the provenance of those zips: keep it.
    report_path = ROOT / 'collections/3d/report.json'
    if report_path.exists():
        seen = {p['id'] for p in packed}
        packed = [p for p in json.loads(report_path.read_text()).get('packed', []) if p['id'] not in seen] + packed
    report = {
        'schema': 1, 'outcome': dict(outcome), 'flag_changes': dict(flipped), 'has_3d_after': total_3d,
        'packed': packed,
        'model_the_footprint_does_not_name': unnamed,
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
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
