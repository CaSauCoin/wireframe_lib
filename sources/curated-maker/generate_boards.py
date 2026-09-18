"""
generate_boards.py — write the dev-board symbols and footprints from boards.py.

Generated rather than hand-written for the reason every generated thing in this
project is: four boards times two files is eight chances to mistype a
coordinate, and a footprint with one pad 2.54 mm out of place looks correct in
every preview and fails on the bench.

Run from this directory:

    python3 generate_boards.py            # write, refusing anything verify() rejects
    python3 generate_boards.py --check    # verify only, write nothing

The pads are through-hole 2.54 mm headers, which is what these boards actually
are: a module soldered into two rows of holes. Pin 1 is square, as KiCad's own
convention has it, so a person can orient the part on the board without reading
the silkscreen.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import boards as board_data

HERE = Path(__file__).resolve().parent
SYMBOL_DIR = HERE / "symbols"
FOOTPRINT_DIR = HERE / "Curated_Maker.pretty"
PROVENANCE = HERE / "PROVENANCE.json"
CACHE = Path(os.path.expanduser("~/.wireframe/library_cache/libforge"))

# Pad geometry for a 2.54 mm through-hole header. Drill 1.0 mm takes the 0.64 mm
# square post of a standard pin header with the clearance a hand-soldered board
# wants; the 1.7 mm pad leaves an annular ring of 0.35 mm, comfortably over the
# 0.15 mm most fabricators set as their minimum.
DRILL_MM = 1.0
PAD_MM = 1.7


def _power_type(label: str) -> str:
    """A pin's electrical type, from what the board calls it.

    Only the unambiguous cases are typed; everything else is `bidirectional`,
    which is what a GPIO broken out to a header actually is. Guessing harder
    would put `power_out` on a pin that merely sounds like a rail and make ERC
    accuse a correct design.
    """
    upper = label.upper()
    if upper in {"GND"}:
        return "power_in"
    if upper in {"3V3", "5V", "VIN", "VBAT", "VCC", "VB"}:
        return "power_in"
    if upper in {"NRST", "RST", "EN"}:
        return "input"
    if upper == "RSV":
        return "no_connect"
    return "bidirectional"


def symbol_text(board: board_data.Board) -> str:
    per_side = max(len(board.left), len(board.right))
    half = (per_side - 1) * 1.27 + 2.54          # body half-height, 2.54 grid
    body_w = 12.7

    lines = [
        '(kicad_symbol_lib (version 20231120) (generator wireframe_libforge)',
        f'  (symbol "{board.name}"',
        '    (exclude_from_sim no)',
        '    (in_bom yes)',
        '    (on_board yes)',
        '    (property "Reference" "MOD" (at 0 0 0)',
        '      (effects (font (size 1.27 1.27))))',
        f'    (property "Value" "{board.name}" (at 0 -2.54 0)',
        '      (effects (font (size 1.27 1.27))))',
        f'    (property "Footprint" "Curated_Maker:{board.name}_THT" (at 0 -5.08 0)',
        '      (effects (font (size 1.27 1.27)) hide))',
        f'    (property "Datasheet" "{board.datasheet}" (at 0 -7.62 0)',
        '      (effects (font (size 1.27 1.27)) hide))',
        f'    (property "Description" "{board.description}" (at 0 -10.16 0)',
        '      (effects (font (size 1.27 1.27)) hide))',
        '    (property "ki_keywords" "maker dev-board module development board '
        'IoT" (at 0 -12.7 0)',
        '      (effects (font (size 1.27 1.27)) hide))',
        f'    (symbol "{board.name}_1_0"',
        f'      (rectangle (start {-body_w / 2:.2f} {half:.2f}) '
        f'(end {body_w / 2:.2f} {-half:.2f})',
        '        (stroke (width 0) (type default)) (fill (type background)))',
    ]

    for number, label, side in board.pins():
        index = (number - 1) if side == "L" else (number - len(board.left) - 1)
        y = half - 2.54 - index * 2.54
        if side == "L":
            x, rot = -body_w / 2 - 2.54, 0
        else:
            x, rot = body_w / 2 + 2.54, 180
        lines += [
            f'      (pin {_power_type(label)} line '
            f'(at {x:.2f} {y:.2f} {rot}) (length 2.54)',
            f'        (name "{label}" (effects (font (size 1.27 1.27))))',
            f'        (number "{number}" (effects (font (size 1.27 1.27)))))',
        ]

    lines += ['    )', '  )', ')', '']
    return "\n".join(lines)


def footprint_text(board: board_data.Board) -> str:
    width, height = board.body_mm
    per_side = max(len(board.left), len(board.right))
    # The header runs down the middle of the board's length, centred.
    first_y = -((per_side - 1) * board.pitch_mm) / 2
    x_left = -board.row_spacing_mm / 2
    x_right = board.row_spacing_mm / 2

    lines = [
        f'(footprint "{board.name}_THT" (version 20240108) '
        f'(generator wireframe_libforge)',
        '  (layer "F.Cu")',
        f'  (descr "{board.description}")',
        '  (attr through_hole)',
        f'  (fp_rect (start {-width / 2:.3f} {-height / 2:.3f}) '
        f'(end {width / 2:.3f} {height / 2:.3f})',
        '    (stroke (width 0.1) (type default)) (fill (type none)) (layer "F.Fab"))',
        f'  (fp_rect (start {-width / 2:.3f} {-height / 2:.3f}) '
        f'(end {width / 2:.3f} {height / 2:.3f})',
        '    (stroke (width 0.12) (type default)) (fill (type none)) (layer "F.SilkS"))',
        f'  (fp_rect (start {-width / 2 - 0.25:.3f} {-height / 2 - 0.25:.3f}) '
        f'(end {width / 2 + 0.25:.3f} {height / 2 + 0.25:.3f})',
        '    (stroke (width 0.05) (type default)) (fill (type none)) '
        '(layer "F.CrtYd"))',
        # Pin-1 marker: a corner tick beside the first pad, which is what a
        # person looks for when the silkscreen is under the module.
        f'  (fp_line (start {x_left - 1.6:.3f} {first_y - 1.6:.3f}) '
        f'(end {x_left - 1.6:.3f} {first_y + 1.6:.3f})',
        '    (stroke (width 0.3) (type default)) (layer "F.SilkS"))',
    ]

    for number, label, side in board.pins():
        index = (number - 1) if side == "L" else (number - len(board.left) - 1)
        y = first_y + index * board.pitch_mm
        x = x_left if side == "L" else x_right
        shape = "rect" if number == 1 else "circle"
        lines.append(
            f'  (pad "{number}" thru_hole {shape} (at {x:.3f} {y:.3f}) '
            f'(size {PAD_MM} {PAD_MM}) (drill {DRILL_MM}) '
            f'(layers "*.Cu" "*.Mask"))'
        )

    lines += [')', '']
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                        help="verify only; write nothing")
    args = parser.parse_args()

    failed = False
    for board in board_data.ALL:
        problems = board_data.verify(board, CACHE)
        status = "ok" if not problems else "REFUSED"
        print(f"  {board.name:<26} {board.pin_count:>3} pins  {status}")
        for problem in problems:
            print(f"      {problem}")
            failed = True

    if failed:
        print("\nnothing written — a board that does not verify is a guess")
        return 1
    if args.check:
        print("\ncheck only; nothing written")
        return 0

    SYMBOL_DIR.mkdir(parents=True, exist_ok=True)
    FOOTPRINT_DIR.mkdir(parents=True, exist_ok=True)

    provenance = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    sources = {entry["part"]: entry for entry in provenance.get("sources", [])}
    hashes = provenance.setdefault("generated_sha256", {})

    for board in board_data.ALL:
        symbol_path = SYMBOL_DIR / f"{board.name}.kicad_sym"
        footprint_path = FOOTPRINT_DIR / f"{board.name}_THT.kicad_mod"
        symbol_path.write_text(symbol_text(board), encoding="utf-8")
        footprint_path.write_text(footprint_text(board), encoding="utf-8")

        sources[board.name] = {
            "part": board.name,
            "url": board.provenance_url,
            "license": board.licence,
        }
        for path in (symbol_path, footprint_path):
            rel = str(path.relative_to(HERE))
            hashes[rel] = "sha256:" + hashlib.sha256(
                path.read_bytes()).hexdigest()
        print(f"  wrote {symbol_path.name} + {footprint_path.name}")

    provenance["sources"] = [sources[key] for key in sorted(sources)]
    provenance["generated_sha256"] = dict(sorted(hashes.items()))
    PROVENANCE.write_text(json.dumps(provenance, indent=2) + "\n",
                          encoding="utf-8")
    print(f"  provenance updated for {len(board_data.ALL)} board(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
