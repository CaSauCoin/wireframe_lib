"""Does a 3D model sit on its footprint? Measured, not assumed.

KiCad places a model by: translate(offset) * rotZ(-rz) * rotY(-ry) * rotX(-rx) * scale,
in a Y-UP frame (board Y down = -3D Y). STEP is millimetres; VRML is 0.1 inch.

Two measures:
  * coverage: of the footprint's copper pads, how many have a model point near
    the board plane inside them (leads sit on pads; a model turned 180 degrees
    leaves the lone pin of a SOT-23 bare);
  * box: the model's XY extent against the footprint's body/courtyard.
"""
from __future__ import annotations

import math
import re

STEP_PT = re.compile(rb"CARTESIAN_POINT\s*\(\s*'[^']*'\s*,\s*\(\s*([-\d.Ee+]+)\s*,\s*([-\d.Ee+]+)\s*,\s*([-\d.Ee+]+)\s*\)")
WRL_PTS = re.compile(rb'point\s*\[([^\]]*)\]')
NUM = re.compile(rb'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?')


def step_scale(data: bytes) -> float:
    head = data[:400000].upper()
    if b'CONVERSION_BASED_UNIT' in head and b"'INCH'" in head:
        return 25.4
    if b'.CENTI.' in head:
        return 10.0
    if b'SI_UNIT(.MILLI.,.METRE.)' in head.replace(b' ', b'') or b'.MILLI.' in head:
        return 1.0
    if b'SI_UNIT($,.METRE.)' in head.replace(b' ', b''):
        return 1000.0
    return 1.0


ENTITY = re.compile(rb'#(\d+)\s*=\s*([A-Z0-9_]+)\s*\(([^;]*)\)\s*;')
REF = re.compile(rb'#(\d+)')


def _circle_points(data: bytes, scale: float, per_circle: int = 12) -> list[tuple[float, float, float]]:
    """Points ON each CIRCLE. A revolved body — a standoff, a round pin, a
    can — is circles and cylinders, whose only CARTESIAN_POINTs are their
    axes' origins: a 16 mm standoff read as a line at x=0..3, y=0."""
    ents = {}
    for m in ENTITY.finditer(data):
        if m.group(2) in (b'CIRCLE', b'AXIS2_PLACEMENT_3D', b'CARTESIAN_POINT', b'DIRECTION'):
            ents[int(m.group(1))] = (m.group(2), m.group(3))

    def nums(body):
        inner = body[body.find(b'(', body.find(b',')) + 1:]
        return [float(x) for x in NUM.findall(inner)[:3]]

    def vec(i, kind):
        e = ents.get(i)
        return nums(e[1]) if e and e[0] == kind else None
    out = []
    for kind, body in list(ents.values()):
        if kind != b'CIRCLE':
            continue
        refs = [int(r) for r in REF.findall(body)]
        radius = NUM.findall(body.split(b',')[-1])
        if not refs or not radius:
            continue
        axis = ents.get(refs[0])
        if not axis or axis[0] != b'AXIS2_PLACEMENT_3D':
            continue
        a = [int(r) for r in REF.findall(axis[1])]
        if len(a) < 2:
            continue
        c = vec(a[0], b'CARTESIAN_POINT')
        z = vec(a[1], b'DIRECTION')
        x = vec(a[2], b'DIRECTION') if len(a) > 2 else None
        if not c or not z or len(c) < 3 or len(z) < 3:
            continue
        if not x or len(x) < 3:
            x = [1.0, 0.0, 0.0] if abs(z[0]) < 0.9 else [0.0, 1.0, 0.0]
        y = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]]
        r = float(radius[0])
        for k in range(per_circle):
            t = 2 * math.pi * k / per_circle
            ct, st = math.cos(t) * r, math.sin(t) * r
            out.append(tuple((c[i] + ct * x[i] + st * y[i]) * scale for i in range(3)))
    return out


def model_points(data: bytes, ext: str, limit: int = 400000) -> list[tuple[float, float, float]]:
    pts = []
    if ext in ('.step', '.stp'):
        s = step_scale(data)
        for m in STEP_PT.finditer(data):
            try:
                pts.append((float(m.group(1)) * s, float(m.group(2)) * s, float(m.group(3)) * s))
            except ValueError:
                continue
            if len(pts) >= limit:
                break
        pts += _circle_points(data, s)
    else:
        for blk in WRL_PTS.finditer(data):
            vals = [float(x) for x in NUM.findall(blk.group(1))]
            for i in range(0, len(vals) - 2, 3):
                pts.append((vals[i] * 2.54, vals[i + 1] * 2.54, vals[i + 2] * 2.54))
            if len(pts) >= limit:
                break
    return pts


def place(points, offset=(0, 0, 0), rotate=(0, 0, 0), scale=(1, 1, 1)):
    """Model points -> board frame (x right, y DOWN, z up), KiCad's order."""
    rx, ry, rz = (math.radians(-a) for a in rotate)
    cx, sx_ = math.cos(rx), math.sin(rx)
    cy, sy_ = math.cos(ry), math.sin(ry)
    cz, sz_ = math.cos(rz), math.sin(rz)
    out = []
    for x, y, z in points:
        x, y, z = x * scale[0], y * scale[1], z * scale[2]
        y, z = y * cx - z * sx_, y * sx_ + z * cx          # about X
        x, z = x * cy + z * sy_, -x * sy_ + z * cy         # about Y
        x, y = x * cz - y * sz_, x * sz_ + y * cz          # about Z
        x, y, z = x + offset[0], y + offset[1], z + offset[2]
        out.append((x, -y, z))
    return out


def pad_boxes(pads):
    """[(number, x0, y0, x1, y1)] from audit_parts.read_footprint pads (copper, numbered or not)."""
    boxes = []
    for p in pads:
        if not p.get('poly'):
            continue
        if not any(str(l).endswith('.Cu') for l in p.get('layers', [])) and p.get('type') != 'thru_hole':
            continue
        if p.get('type') == 'np_thru_hole':
            continue
        xs = [q[0] for q in p['poly']]
        ys = [q[1] for q in p['poly']]
        boxes.append((p['number'], min(xs), min(ys), max(xs), max(ys), p.get('type')))
    # A thermal via or a paste window inside a bigger pad of the same number
    # (an exposed pad's via array) is that pad, not a terminal of its own.
    inner = {i for i, a in enumerate(boxes) for j, b in enumerate(boxes)
             if i != j and a[0] == b[0] and (b[3] - b[1]) * (b[4] - b[2]) > (a[3] - a[1]) * (a[4] - a[2])
             and b[1] <= a[1] and b[2] <= a[2] and a[3] <= b[3] and a[4] <= b[4]}
    return [b for i, b in enumerate(boxes) if i not in inner]


def seat(placed, band: float = 0.05):
    """Points on the seating plane. The board surface is z = 0 by KiCad's
    convention, and a lead that is soldered is there: a SOT-23's feet are and
    its body (0.1 mm up) is not; a USB-C receptacle's signal leads are, while
    its shell legs continue into the board. Only when nothing touches z = 0 is
    the lowest point above the board taken instead — a press-fit standoff's
    lowest point is inside its hole."""
    plane = [p for p in placed if abs(p[2]) <= 0.15 and (p[0], p[1]) != (0.0, 0.0)]
    if len(plane) >= 3:
        return plane
    above = [p for p in placed if p[2] >= -0.15] or placed
    zmin = min(p[2] for p in above)
    return [p for p in above if p[2] <= zmin + band and (p[0], p[1]) != (0.0, 0.0)]


def stray(placed, pads, grow: float = 0.25, band: float = 0.05):
    """Fraction of seating-plane points that land on no pad — a model turned the
    wrong way puts its feet on bare board."""
    boxes = pad_boxes(pads)
    low = seat(placed, band)
    if not boxes or not low:
        return None
    off = sum(1 for x, y, _ in low
              if not any(x0 - grow <= x <= x1 + grow and y0 - grow <= y <= y1 + grow
                         for _, x0, y0, x1, y1, _t in boxes))
    return off / len(low)


def coverage(placed, pads, band: float = 0.05, grow: float = 0.25):
    """Fraction of copper pads with a model point on them. SMD: seating-plane
    points only (see `seat`). THT: any point in the hole's column."""
    boxes = pad_boxes(pads)
    if not boxes or not placed:
        return None, []
    low = seat(placed, band)
    bare = []
    for number, x0, y0, x1, y1, ptype in boxes:
        pool = placed if ptype == 'thru_hole' else low
        hit = any(x0 - grow <= x <= x1 + grow and y0 - grow <= y <= y1 + grow for x, y, _ in pool)
        if not hit:
            bare.append(number)
    return 1 - len(bare) / len(boxes), bare


def extent(placed, trim: float = 0.002):
    if not placed:
        return None
    xs = sorted(p[0] for p in placed)
    ys = sorted(p[1] for p in placed)
    zs = sorted(p[2] for p in placed)
    k = int(len(xs) * trim)
    return (xs[k], ys[k], zs[k], xs[-1 - k], ys[-1 - k], zs[-1 - k])
