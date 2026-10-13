#!/usr/bin/env python3
"""Audit every part the shards list: pins against pads, the land pattern itself, and its 3D model.

Read-only: opens each part zip exactly as the app installs it and writes one
JSON report. Nothing in the library is changed.

    python3 tools/audit_parts.py --report reports/audit-parts.json
    python3 tools/audit_parts.py --report /tmp/a.json --only kicad-symbols/74xx

What each finding means, cheapest to most expensive to get wrong:

  pin_without_pad     a symbol pin whose number no pad carries — its net
                      reaches no copper (Conn_02x05_Row_Letter_First's a1..b5
                      on a header numbered 1..10; 74LS20's VCC on DIP-12)
  pad_without_pin     a numbered copper pad no pin names: an NC pin (fine on an
                      IC) or a contact the symbol cannot reach (not fine on a
                      connector or a discrete)
  pads_short          two pads with different numbers overlap on one copper
                      layer and their pins do not carry the same signal
                      (KiCad's Pulse_PA2002NL puts pads 4 and 6 at one spot)
  duplicate_pin_number one number drawn twice, apart, with different names
  model_*             the 3D state as the app sees it: `ok` only when the zip
                      holds the file the footprint names; `model_misplaced`
                      when that model's feet do not land on the pads

KiCad 10 stacked pin numbers (`[1,15,38-39]`) are expanded the way
`KicadSymbolParser::stackedPinNumbers` expands them, and a KiCad 5 pad number
(`(pad 1 thru_hole …)`, unquoted) is not read as the pad's type.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB.parent / 'WireFrame' / 'Tools'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from libforge import sexp  # noqa: E402

import model_fit  # noqa: E402

MODEL_EXT = ('.step', '.stp', '.wrl')
MECH = {'mp', 'sh', 'shield', ''}


# ---------------------------------------------------------------- symbol
def stacked_numbers(number: str) -> list[str]:
    """KiCad 10 stacked pins, '[1,15,38-39]' -> pads; mirrors KicadSymbolParser::stackedPinNumbers."""
    if len(number) < 3 or number[0] != '[' or number[-1] != ']':
        return [number]
    out = []
    for item in number[1:-1].split(','):
        item = item.strip()
        m = re.fullmatch(r'(\d{1,6})-(\d{1,6})', item)
        if m and int(m.group(1)) <= int(m.group(2)) and int(m.group(2)) - int(m.group(1)) < 1000:
            out += [str(n) for n in range(int(m.group(1)), int(m.group(2)) + 1)]
        elif item:
            out.append(item)
    return out or [number]


def read_symbol(text: str, want: str):
    root = sexp.loads(text)
    syms = {sexp.arg(s, 0): s for s in sexp.children(root, 'symbol')}
    if not syms:
        return None, []
    bare = want.split(':')[-1]
    name = bare if bare in syms else next(iter(syms))
    node, seen = syms[name], {name}
    # follow extends to the pin-carrying parent
    while sexp.value_of(node, 'extends') and not list(sexp.descendants(node, 'pin')):
        parent = sexp.value_of(node, 'extends')
        if parent in seen or parent not in syms:
            break
        seen.add(parent)
        node = syms[parent]
    base = sexp.arg(node, 0)
    pins = []
    subs = list(sexp.children(node, 'symbol')) or [node]
    for sub in subs:
        sub_name = sexp.arg(sub, 0)
        tail = sub_name[len(base) + 1:].split('_') if sub_name.startswith(base + '_') else ['1', '1']
        try:
            unit, style = int(tail[0]), int(tail[1]) if len(tail) > 1 else 1
        except ValueError:
            unit, style = 1, 1
        if style > 1:
            continue
        for pin in sexp.children(sub, 'pin'):
            toks = sexp.bare_tokens(pin)
            at = sexp.floats(sexp.child(pin, 'at') or [], 3) or [0, 0, 0]
            for number in stacked_numbers(sexp.value_of(pin, 'number')):
                pins.append({'number': number, 'name': sexp.value_of(pin, 'name'),
                             'type': toks[0] if toks else '', 'unit': unit,
                             'at': (round(at[0], 3), round(at[1], 3)),
                             'hidden': sexp.flag(pin, 'hide')})
    props = {sexp.arg(p, 0): sexp.arg(p, 1) for p in sexp.children(syms[name], 'property')}
    return {'name': name, 'props': props}, pins


# ---------------------------------------------------------------- footprint
def _poly_rect(cx, cy, w, h, rot):
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    pts = []
    for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
        # KiCad pad rotation is counter-clockwise on screen with y down
        pts.append((cx + dx * c + dy * s, cy - dx * s + dy * c))
    return pts


def _poly_circle(cx, cy, r, n=16):
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def _hull(points):
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _area(poly):
    return abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
                   for i in range(len(poly)))) / 2 if len(poly) >= 3 else 0.0


def _clip(subject, clipper):
    """Sutherland-Hodgman; both convex. Returns intersection polygon."""
    def ccw(poly):
        s = sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
                for i in range(len(poly)))
        return poly if s > 0 else poly[::-1]
    out = ccw(subject)
    clip = ccw(clipper)
    for i in range(len(clip)):
        a, b = clip[i], clip[(i + 1) % len(clip)]
        inp, out = out, []
        if not inp:
            break

        def inside(p):
            return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) >= -1e-9

        def inter(p, q):
            x1, y1, x2, y2 = a[0], a[1], b[0], b[1]
            x3, y3, x4, y4 = p[0], p[1], q[0], q[1]
            den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
            if abs(den) < 1e-12:
                return q
            t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
            return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
        for j in range(len(inp)):
            p, q = inp[j], inp[(j + 1) % len(inp)]
            if inside(q):
                if not inside(p):
                    out.append(inter(p, q))
                out.append(q)
            elif inside(p):
                out.append(inter(p, q))
    return out


def read_footprint(text: str):
    root = sexp.loads(text)
    pads = []
    for pad in sexp.descendants(root, 'pad'):
        toks = sexp.bare_tokens(pad)
        if toks and len(pad) > 1 and toks[0] == pad[1] and not sexp.is_quoted(pad[1]):
            toks = toks[1:]          # KiCad 5 writes the pad number unquoted
        ptype = toks[0] if toks else ''
        shape = toks[1] if len(toks) > 1 else ''
        at = sexp.floats(sexp.child(pad, 'at') or [], 3) or None
        if at is None:
            a2 = sexp.floats(sexp.child(pad, 'at') or [], 2)
            at = (a2 or [0, 0]) + [0]
        size = sexp.floats(sexp.child(pad, 'size') or [], 2) or [0, 0]
        layers = [str(x) for x in (sexp.child(pad, 'layers') or [])[1:]]
        drill_node = sexp.child(pad, 'drill')
        drill = None
        if drill_node is not None:
            nums = [float(t) for t in drill_node[1:] if isinstance(t, str) and re.fullmatch(r'-?[\d.]+', t)]
            if nums:
                drill = (nums[0], nums[1] if len(nums) > 1 else nums[0])
        cx, cy, rot = at[0], at[1], at[2]
        w, h = size
        if shape == 'circle':
            poly = _poly_circle(cx, cy, w / 2)
        elif shape == 'oval' and abs(w - h) > 1e-6:
            # a stadium: two half circles on the long axis, in the pad's frame
            r, half = min(w, h) / 2, (max(w, h) - min(w, h)) / 2
            local = [(half + r * math.cos(t), r * math.sin(t))
                     for t in (math.radians(a) for a in range(-90, 91, 15))]
            local += [(-half + r * math.cos(t), r * math.sin(t))
                      for t in (math.radians(a) for a in range(90, 271, 15))]
            if h > w:
                local = [(y, x) for x, y in local]
            c, sn = math.cos(math.radians(rot)), math.sin(math.radians(rot))
            poly = _hull([(cx + x * c + y * sn, cy - x * sn + y * c) for x, y in local])
        elif shape == 'custom':
            pts = []
            prim = sexp.child(pad, 'primitives')
            if prim is not None:
                for xy in sexp.descendants(prim, 'xy'):
                    f = sexp.floats(xy, 2)
                    if f:
                        # primitives are relative to the pad, rotated with it
                        c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
                        pts.append((cx + f[0] * c + f[1] * s, cy - f[0] * s + f[1] * c))
            pts += _poly_rect(cx, cy, w, h, rot)
            poly = _hull(pts)
        else:
            poly = _poly_rect(cx, cy, w, h, rot)
        pads.append({'number': sexp.arg(pad, 0), 'type': ptype, 'shape': shape, 'at': (cx, cy, rot),
                     'size': (w, h), 'layers': layers, 'drill': drill, 'poly': poly})
    models = []
    for m in sexp.descendants(root, 'model'):
        path = sexp.arg(m, 0)

        def vec(name):
            node = sexp.child(m, name)
            if node is None:
                return None
            xyz = sexp.child(node, 'xyz')
            return sexp.floats(xyz, 3) if xyz is not None else None
        models.append({'path': path, 'offset': vec('offset') or vec('at') or [0, 0, 0],
                       'offset_is_at': sexp.child(m, 'offset') is None and sexp.child(m, 'at') is not None,
                       'scale': vec('scale') or [1, 1, 1], 'rotate': vec('rotate') or [0, 0, 0],
                       'hidden': sexp.flag(m, 'hide')})
    ext = {}
    for layer in ('F.CrtYd', 'F.Fab', 'F.SilkS', 'B.CrtYd'):
        xs, ys = [], []
        for kind in ('fp_line', 'fp_rect', 'fp_poly', 'fp_circle', 'fp_arc'):
            for g in sexp.descendants(root, kind):
                if sexp.value_of(g, 'layer') != layer:
                    continue
                for key in ('start', 'end', 'mid'):
                    p = sexp.xy(g, key)
                    if p:
                        xs.append(p[0]); ys.append(p[1])
                if kind == 'fp_circle':
                    c, e = sexp.xy(g, 'center'), sexp.xy(g, 'end')
                    if c and e:
                        r = math.hypot(e[0] - c[0], e[1] - c[1])
                        xs += [c[0] - r, c[0] + r]; ys += [c[1] - r, c[1] + r]
                pts = sexp.child(g, 'pts')
                if pts is not None:
                    for q in sexp.children(pts, 'xy'):
                        f = sexp.floats(q, 2)
                        if f:
                            xs.append(f[0]); ys.append(f[1])
        if xs:
            ext[layer] = (min(xs), min(ys), max(xs), max(ys))
    attr = sexp.child(root, 'attr')
    return {'name': sexp.arg(root, 0), 'pads': pads, 'models': models, 'extents': ext,
            'attr': sexp.bare_tokens(attr) if attr is not None else [],
            'net_tie': sexp.child(root, 'net_tie_pad_groups') is not None}


USB_C_SHARED = [{'A1', 'B12'}, {'A12', 'B1'}, {'A4', 'B9'}, {'A9', 'B4'}]


def copper_layers(pad):
    out = set()
    for layer in pad['layers']:
        if layer in ('*.Cu', 'F&B.Cu'):
            out |= {'F.Cu', 'B.Cu', 'In.Cu'}
        elif layer.endswith('.Cu'):
            out.add(layer)
    if pad['type'] == 'thru_hole' and out:
        out |= {'F.Cu', 'B.Cu', 'In.Cu'}
    return out


# ---------------------------------------------------------------- name facts
NAME_COUNT = re.compile(
    r'^(?:[A-Za-z]+_)?((?:H|W|V|U|X|T|L|M|S|Power|HV|E)?(?:SOIC|SOP|SSOP|TSSOP|HTSSOP|MSOP|VSSOP|TSOP|QSOP|QFN|DFN|LQFP|TQFP|HTQFP|'
    r'QFP|LFCSP|SON|DIP|SOT-23|SOT|TO-220|TO-247|TO-263|TO-252|TO-92|TSOT-23|SC-70|SC-74|SOD|DIL|PDIP|CDIP|SDIP|PLCC|BGA|LGA|WLCSP|'
    r'TO-3P|TO-126|HSOP|PowerPAK|DSBGA|LLP|MLF|MLP|SIP|ZIP))-(\d+)(?:-(\d+)EP)?(?=[_-]|$)', re.I)
GRID = re.compile(r'(?:PinHeader|PinSocket|IDC-Header|Header|Socket|Conn|JST|Molex|TE|Samtec|Hirose|Wurth)[A-Za-z0-9_-]*?_(\d{1,2})x(\d{1,3})(?:-(\d+)MP)?[_-]', re.I)
PITCH = re.compile(r'_P(\d+(?:\.\d+)?)mm', re.I)


def name_facts(fp_name: str):
    facts = {}
    m = NAME_COUNT.match(fp_name)
    if m and not re.match(r'^(SOT|SOD)-\d{3}', fp_name.split('_', 1)[-1] if '_' in fp_name[:4] else fp_name):
        fam, n, ep = m.group(1), int(m.group(2)), m.group(3)
        # SOT-23, SOT-223, SOD-123 are package NAMES, not counts.
        if fam.upper() in ('SOT', 'SOD') or (fam.upper() == 'SOT-23' and n > 8):
            pass
        else:
            facts['count'] = n
            facts['ep'] = int(ep) if ep else 0
            facts['count_from'] = m.group(0)
    g = GRID.search(fp_name)
    if g and 'count' not in facts:
        facts['count'] = int(g.group(1)) * int(g.group(2))
        facts['ep'] = 0
        facts['count_from'] = g.group(0)
    p = PITCH.search(fp_name)
    if p:
        facts['pitch'] = float(p.group(1))
    return facts


def pitch_candidates(pads):
    pts = [(p['at'][0], p['at'][1]) for p in pads if p['number'] and p['number'].lower() not in MECH
           and p['type'] != 'np_thru_hole']
    gaps = set()
    for axis in (0, 1):
        coords = sorted({round(q[axis], 3) for q in pts})
        for a, b in zip(coords, coords[1:]):
            gaps.add(round(b - a, 3))
    # also nearest-neighbour distances (diagonal staggered rows)
    for i, a in enumerate(pts[:300]):
        best = min((math.hypot(a[0] - b[0], a[1] - b[1]) for j, b in enumerate(pts) if j != i), default=None)
        if best:
            gaps.add(round(best, 3))
    return gaps


# ---------------------------------------------------------------- 3D
def is_placeholder(data: bytes) -> bool:
    text = data[:8192].decode('latin-1')
    shapes = re.findall(r'geometry\s+(\w+)', text)
    return text.startswith('#VRML') and len(data) <= 4096 and bool(shapes) and set(shapes) == {'Box'}


def resolve_model(names, declared):
    by_base = {os.path.basename(n): n for n in names}
    by_lower = {os.path.basename(n).lower(): n for n in names}
    stem, ext = os.path.splitext(os.path.basename(declared))
    tries = [stem + ext] + ([stem + '.step', stem + '.stp'] if ext.lower() == '.wrl' else [])
    for t in tries:
        if t in by_base:
            return by_base[t], 'exact'
    for t in tries:
        if t.lower() in by_lower:
            return by_lower[t.lower()], 'case'
    return None, ''


# ---------------------------------------------------------------- audit
def audit(entry: dict, parts_dir: str, want_bbox: bool):
    slug = entry.get('slug', '')
    out = {'id': entry.get('id'), 'slug': slug, 'source': entry.get('source'), 'class': entry.get('class'),
           'tier': entry.get('tier'), 'name': entry.get('name'), 'footprint': entry.get('footprint'),
           'has_3d_flag': bool(entry.get('has_3d')), 'findings': []}
    F = out['findings']

    def add(code, level, msg, **kw):
        F.append({'code': code, 'level': level, 'msg': msg, **kw})
    path = os.path.join(parts_dir, slug + '.zip')
    if not os.path.exists(path):
        add('no_zip', 'error', 'zip missing')
        return out
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        add('bad_zip', 'error', 'zip unreadable')
        return out
    names = z.namelist()
    try:
        manifest = json.loads(z.read('part.json')) if 'part.json' in names else {}
    except ValueError:
        manifest = {}
    fpm, m3d = manifest.get('footprint'), manifest.get('model3d')
    out['resolved_by'] = fpm.get('resolved_by', '') if isinstance(fpm, dict) else ''
    out['model_resolved_by'] = m3d.get('resolved_by', '') if isinstance(m3d, dict) else ''
    sym_files = [n for n in names if n.endswith('.kicad_sym')]
    fp_files = [n for n in names if n.endswith('.kicad_mod')]
    sym = pins = fp = None
    if sym_files:
        try:
            sym, pins = read_symbol(z.read(sym_files[0]).decode('utf-8', 'replace'), entry.get('name', ''))
        except Exception as e:  # noqa: BLE001
            add('symbol_unparsable', 'error', str(e)[:120])
    else:
        add('no_symbol', 'error', 'zip has no .kicad_sym')
    if fp_files:
        try:
            fp = read_footprint(z.read(fp_files[0]).decode('utf-8', 'replace'))
        except Exception as e:  # noqa: BLE001
            add('footprint_unparsable', 'error', str(e)[:120])
    else:
        add('no_footprint', 'error' if entry.get('footprint') else 'info', 'zip has no .kicad_mod')
    out['fp_name'] = fp['name'] if fp else ''

    # ---------------- pins vs pads
    sym_nums = {}
    if pins is not None and fp is not None:
        for p in pins:
            if p['number']:
                sym_nums.setdefault(p['number'], []).append(p)
        pad_nums = {p['number'] for p in fp['pads'] if p['number']}
        elec_pads = {p['number'] for p in fp['pads'] if p['number'] and p['number'].lower() not in MECH
                     and p['type'] != 'np_thru_hole' and copper_layers(p)}
        no_pad = sorted(n for n in sym_nums if n not in pad_nums and n.lower() not in MECH)
        no_pin = sorted(n for n in elec_pads if n not in sym_nums and not n.upper().startswith('NC'))
        out['pins'] = len(sym_nums)
        out['pads'] = len(elec_pads)
        if no_pad:
            add('pin_without_pad', 'error', f'{len(no_pad)} symbol pin(s) have no pad: {no_pad[:12]}',
                pins=no_pad[:40])
        klass = entry.get('class') or ''
        if no_pin:
            # An NC pin is ordinary on an IC and a transformer (KiCad's TL431
            # in DIP-8 names 3 of 8); it is a defect only beside a pin that has
            # no pad, which `pin_without_pad` already reports as an error.
            add('pad_without_pin', 'warn', f'{len(no_pin)} pad(s) have no symbol pin: {no_pin[:12]}', pads=no_pin[:40])
        if not sym_nums:
            pinless = (entry.get('class') or '').startswith('mechanical')   # a mounting hole, a fiducial
            add('symbol_has_no_pins', 'info' if pinless else 'error', 'symbol has no numbered pins')
        # duplicate pin numbers that are not stacked
        for num, group in sym_nums.items():
            if len(group) > 1:
                same_unit = defaultdict(list)
                for g in group:
                    same_unit[g['unit']].append(g)
                for unit, gs in same_unit.items():
                    if len(gs) > 1 and len({g['at'] for g in gs}) > 1 and len({g['name'] for g in gs}) > 1:
                        add('duplicate_pin_number', 'error',
                            f'pin {num} appears {len(gs)}x in unit {unit} with names {sorted({g["name"] for g in gs})}')
                        break

    # ---------------- footprint geometry
    if fp is not None:
        pads = fp['pads']
        ep_like = 0
        for p in pads:
            w, h = p['size']
            if (w <= 0 or h <= 0) and p['shape'] != 'custom':
                add('pad_zero_size', 'error', f'pad {p["number"]!r} has size {w}x{h}')
            if p['type'] == 'thru_hole':
                if not p['drill']:
                    add('tht_no_drill', 'error', f'THT pad {p["number"]!r} has no drill')
                elif p['shape'] != 'custom' and (p['drill'][0] >= w - 1e-6 and p['drill'][1] >= h - 1e-6) and w > 0:
                    # a thermal via inside an exposed pad of the same number is
                    # a DFM question (no ring), not an unconnected terminal
                    via = any(q is not p and q['number'] == p['number'] and q['size'][0] * q['size'][1] > w * h
                              for q in pads)
                    add('no_annular_ring', 'warn' if via else 'error',
                        f'pad {p["number"]!r} drill {p["drill"]} >= pad {w}x{h}' + (' (thermal via)' if via else ''))
            if p['type'] == 'smd' and p['drill']:
                pass
        # overlapping copper of different numbers
        name = fp['name'] or ''
        intentional = fp['net_tie'] or re.search(r'NetTie|Bridged|Jumper.*Closed|SolderJumper.*_Bridged', name, re.I)
        numbered = [p for p in pads if p['number'] and p['number'].lower() not in MECH and copper_layers(p)
                    and len(p['poly']) >= 3]
        overlaps = []
        if not intentional and len(numbered) < 1500:
            boxes = []
            for p in numbered:
                xs = [q[0] for q in p['poly']]; ys = [q[1] for q in p['poly']]
                boxes.append((min(xs), min(ys), max(xs), max(ys)))
            order = sorted(range(len(numbered)), key=lambda i: boxes[i][0])
            for ii, i in enumerate(order):
                a, ba = numbered[i], boxes[i]
                for j in order[ii + 1:]:
                    bb = boxes[j]
                    if bb[0] > ba[2]:
                        break
                    b = numbered[j]
                    if a['number'] == b['number'] or bb[1] > ba[3] or bb[3] < ba[1]:
                        continue
                    if not (copper_layers(a) & copper_layers(b)):
                        continue
                    na = {q['name'].upper() for q in sym_nums.get(a['number'], [])} if pins else set()
                    nb = {q['name'].upper() for q in sym_nums.get(b['number'], [])} if pins else set()
                    if na & nb - {'', '~'}:
                        continue      # same signal on both (USB-C A1/B12 GND): one copper on purpose
                    if {a['number'], b['number']} in USB_C_SHARED:
                        continue      # USB-C's mirrored GND/VBUS contacts share a pad by the standard
                    inter = _clip(a['poly'], b['poly'])
                    ar = _area(inter)
                    if ar > 1e-3:
                        overlaps.append((a['number'], b['number'], round(ar, 3),
                                         a['shape'] == 'custom' or b['shape'] == 'custom'))
                        if len(overlaps) > 20:
                            break
                if len(overlaps) > 20:
                    break
        if overlaps:
            custom = all(o[3] for o in overlaps)
            add('pads_short', 'warn' if custom else 'error',
                f'{len(overlaps)} pair(s) of differently numbered pads overlap on copper: '
                + ', '.join(f'{x}/{y} ({ar} mm2)' for x, y, ar, _ in overlaps[:6]), pairs=overlaps[:20])
        # scale sanity
        cen = [(p['at'][0], p['at'][1]) for p in pads if p['number'] and p['type'] != 'np_thru_hole']
        if len({p['number'] for p in pads if p['number'] and p['type'] != 'np_thru_hole'}) >= 2:
            span = max(max(c[0] for c in cen) - min(c[0] for c in cen), max(c[1] for c in cen) - min(c[1] for c in cen))
            out['pad_span'] = round(span, 3)
            if span < 0.25:
                add('scale_too_small', 'error', f'all pads within {span:.3f} mm (scale bug?)')
            if span > 400:
                add('scale_too_large', 'error', f'pads span {span:.1f} mm')
        # name facts
        facts = {} if (entry.get('class') or '').startswith('mechanical') else name_facts(name)
        if 'count' in facts:
            elec_unique = {p['number'] for p in pads if p['number'] and p['number'].lower() not in MECH
                           and p['type'] != 'np_thru_hole' and copper_layers(p)}
            want = facts['count'] + facts['ep']
            got = len(elec_unique)
            if got not in (facts['count'], want) and not (facts['ep'] and got in (facts['count'] + 1,)):
                add('name_count_mismatch', 'warn',
                    f'name says {facts["count_from"]!r} -> {want} contacts, footprint has {got} numbered pads')
        if 'pitch' in facts and len(cen) >= 2:
            gaps = pitch_candidates(pads)
            P = facts['pitch']
            tol = max(0.02, P * 0.02)
            if not any(abs(g - P) <= tol for g in gaps):
                near = sorted(gaps, key=lambda g: abs(g - P))[:3]
                add('name_pitch_mismatch', 'warn', f'name says P{P}mm, measured spacings nearest: {near}')

    # ---------------- 3D
    declared = [m for m in (fp['models'] if fp else []) if m['path']]
    model_files = [n for n in names if n.lower().endswith(MODEL_EXT)]
    status = 'none'
    chosen = None
    for m in declared:
        hit, how = resolve_model(names, m['path'])
        if hit:
            chosen = (hit, m, how)
            break
    if chosen:
        data = z.read(chosen[0])
        if is_placeholder(data):
            status = 'placeholder'
        else:
            status = 'ok' if chosen[2] == 'exact' else 'case_mismatch'
    elif declared and model_files:
        status = 'stray'           # zip has a model the footprint does not name
    elif declared:
        status = 'declared_missing'
    elif model_files:
        status = 'undeclared_in_zip'
    else:
        status = 'no_model'
    out['model_status'] = status
    out['declared'] = [m['path'] for m in declared]
    out['model_files'] = model_files
    if status != 'ok':
        add('model_' + status, 'warn', f'3D: {status}; declared={[os.path.basename(m["path"]) for m in declared][:3]} '
            f'zip={model_files[:3]}')
    if status == 'ok' and fp is not None and want_bbox:
        name, m = chosen[0], chosen[1]
        points = model_fit.model_points(z.read(name), os.path.splitext(name)[1].lower())
        if not points:
            add('model_unreadable', 'error', f'3D {name} has no geometry points')
        else:
            offset = [v * 25.4 for v in m['offset']] if m.get('offset_is_at') else m['offset']
            placed = model_fit.place(points, offset, m['rotate'], m['scale'])
            cov, bare = model_fit.coverage(placed, fp['pads'])
            off = model_fit.stray(placed, fp['pads'])
            e = model_fit.extent(placed)
            out['model_fit'] = {'coverage': None if cov is None else round(cov, 3),
                                'stray': None if off is None else round(off, 3),
                                'box': [round(v, 2) for v in e]}
            if cov is not None and cov < 0.6 and (off is None or off > 0.5):
                add('model_misplaced', 'warn',
                    f'3D feet land on {cov:.0%} of the pads and {off or 0:.0%} of them on bare board; '
                    f'bare pads {bare[:8]}')
            if e[5] <= 0.05:
                add('model_below_board', 'warn', f'3D top at z={e[5]:.2f} mm')
    return out


def _run(args):
    entry, parts_dir, want_bbox = args
    try:
        return audit(entry, parts_dir, want_bbox)
    except Exception as e:  # noqa: BLE001
        return {'id': entry.get('id'), 'slug': entry.get('slug'), 'source': entry.get('source'),
                'class': entry.get('class'), 'findings': [{'code': 'audit_crash', 'level': 'error', 'msg': repr(e)[:200]}]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=Path, default=LIB / 'Dist_Repo/v2')
    ap.add_argument('--report', type=Path, required=True)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--only', default='')
    ap.add_argument('--no-bbox', action='store_true')
    ap.add_argument('--compact', action='store_true', help='keep only parts with a finding, one line each')
    a = ap.parse_args()
    entries = []
    for f in sorted((a.out / 'shards').glob('*.json')):
        for e in json.loads(f.read_text())['entries']:
            e['_shard'] = f.stem
            entries.append(e)
    if a.only:
        entries = [e for e in entries if a.only in e.get('id', '') or a.only in e.get('slug', '')]
    if a.limit:
        entries = entries[:a.limit]
    parts = str(a.out / 'parts')
    with ProcessPoolExecutor() as ex:
        results = list(ex.map(_run, [(e, parts, not a.no_bbox) for e in entries], chunksize=16))
    for r, e in zip(results, entries):
        r['shard'] = e['_shard']
    summary = Counter()
    by_source = defaultdict(Counter)
    for r in results:
        for c in {f['code'] + ':' + f['level'] for f in r['findings']}:
            summary[c] += 1
            by_source[r.get('source')][c] += 1
    if a.compact:
        results = [{k: r.get(k) for k in ('id', 'source', 'class', 'tier', 'fp_name', 'resolved_by', 'model_status',
                                          'model_fit', 'findings') if r.get(k) is not None}
                   for r in results if r['findings']]
    a.report.write_text(json.dumps({'total': len(entries), 'summary': dict(summary.most_common()),
                                    'by_source': {k: dict(v.most_common()) for k, v in by_source.items()},
                                    'parts': results}, ensure_ascii=False, indent=None if a.compact else 1))
    print('parts', len(entries))
    for k, v in summary.most_common():
        print(f'{v:6d}  {k}')


if __name__ == '__main__':
    main()
