"""
author_components.py — Authoritative maker dev boards, displays, and wireless modules.

Generates KiCad 8 symbols (.kicad_sym), footprints (.kicad_mod), and 3D shapes (.wrl)
for iconic maker components requested by users:
  1. Arduino Mega 2560, Due, Uno R4 (Minima, WiFi)
  2. STM32 Discovery (STM32F4-Discovery, STM32F3-Discovery)
  3. Circular & Wearable Boards (LilyPad 328, LilyPad USB, Adafruit Flora, Circuit Playground, micro:bit)
  4. Displays (OLED 0.96 I2C/SPI, 0.91, 1.3, TFT 1.8, TFT 2.4, TFT 1.3, E-Paper 2.13, TM1637, MAX7219, LCD 1602/2004)
  5. Wireless Modules (NRF24L01, NRF24L01 PA+LNA, ESP-01S, HC-05, HC-06, HM-10, LoRa Ra-02, EBYTE E32, SIM800L, NEO-6M, RC522)
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE
SYMBOL_DIR = ROOT / "symbols"
FOOTPRINT_DIR = ROOT / "Curated_Maker.pretty"
MODEL_DIR = ROOT / "Curated_Maker.3dshapes"
PROVENANCE = ROOT / "PROVENANCE.json"


@dataclass
class CuratedPart:
    name: str
    description: str
    datasheet: str
    provenance_url: str
    license: str
    reference: str = "MOD"
    keywords: str = "maker module breakout dev-board"

    # Outline & mechanical
    outline_type: str = "rect"    # "rect" | "circle"
    dimensions_mm: tuple[float, float, float] = (30.0, 20.0, 5.0)  # width, height/length, depth
    color_rgb: tuple[float, float, float] = (0.1, 0.35, 0.75)       # default blue PCB

    # Mounting holes: list of (x, y, drill_dia)
    holes: list[tuple[float, float, float]] = field(default_factory=list)

    # Pins: list of (number_str, name_str, pad_x, pad_y, elec_type, side)
    # side is "L", "R", "T", "B" for symbol placement
    pins: list[tuple[str, str, float, float, str, str]] = field(default_factory=list)

    # Pad style: "tht_header" (1.0mm drill, 1.7mm pad) or "sew_tab" (1.8mm drill, 3.5mm pad)
    pad_style: str = "tht_header"


def _wrl_box(w_mm: float, h_mm: float, d_mm: float, rgb: tuple[float, float, float]) -> str:
    w, h, d = w_mm / 2.54, h_mm / 2.54, d_mm / 2.54
    return (
        "#VRML V2.0 utf8\n"
        "Shape {\n"
        "  appearance Appearance {\n"
        f"    material Material {{ diffuseColor {rgb[0]:.3f} {rgb[1]:.3f} {rgb[2]:.3f} }}\n"
        "  }\n"
        f"  geometry Box {{ size {w:.4f} {h:.4f} {d:.4f} }}\n"
        "}\n"
    )


def generate_symbol(part: CuratedPart) -> str:
    left_pins = [p for p in part.pins if p[5] == "L"]
    right_pins = [p for p in part.pins if p[5] == "R"]

    # Fallback to balanced left/right if not specified
    if not left_pins and not right_pins:
        n = len(part.pins)
        half = (n + 1) // 2
        left_pins = [(p[0], p[1], p[2], p[3], p[4], "L") for p in part.pins[:half]]
        right_pins = [(p[0], p[1], p[2], p[3], p[4], "R") for p in part.pins[half:]]

    max_side = max(len(left_pins), len(right_pins), 1)
    body_h = (max_side + 1) * 2.54
    half_h = body_h / 2
    body_w = 20.32  # 800 mil standard width for symbols

    fp_name = f"{part.name}_Module"

    lines = [
        '(kicad_symbol_lib (version 20231120) (generator wireframe_libforge)',
        f'  (symbol "{part.name}"',
        '    (exclude_from_sim no)',
        '    (in_bom yes)',
        '    (on_board yes)',
        f'    (property "Reference" "{part.reference}" (at 0 {half_h + 2.54:.2f} 0)',
        '      (effects (font (size 1.27 1.27))))',
        f'    (property "Value" "{part.name}" (at 0 {-half_h - 2.54:.2f} 0)',
        '      (effects (font (size 1.27 1.27))))',
        f'    (property "Footprint" "Curated_Maker:{fp_name}" (at 0 -5.08 0)',
        '      (effects (font (size 1.27 1.27)) hide))',
        f'    (property "Datasheet" "{part.datasheet}" (at 0 -7.62 0)',
        '      (effects (font (size 1.27 1.27)) hide))',
        f'    (property "Description" "{part.description}" (at 0 -10.16 0)',
        '      (effects (font (size 1.27 1.27)) hide))',
        f'    (property "ki_keywords" "{part.keywords}" (at 0 -12.7 0)',
        '      (effects (font (size 1.27 1.27)) hide))',
        f'    (symbol "{part.name}_1_0"',
        f'      (rectangle (start {-body_w / 2:.2f} {half_h:.2f}) (end {body_w / 2:.2f} {-half_h:.2f})',
        '        (stroke (width 0.254) (type default)) (fill (type background)))',
    ]

    for i, p in enumerate(left_pins):
        y = half_h - 2.54 - i * 2.54
        lines.append(
            f'      (pin {p[4]} line (at {-body_w / 2 - 2.54:.2f} {y:.2f} 0) (length 2.54)'
            f' (name "{p[1]}" (effects (font (size 1.27 1.27))))'
            f' (number "{p[0]}" (effects (font (size 1.27 1.27)))))'
        )

    for i, p in enumerate(right_pins):
        y = half_h - 2.54 - i * 2.54
        lines.append(
            f'      (pin {p[4]} line (at {body_w / 2 + 2.54:.2f} {y:.2f} 180) (length 2.54)'
            f' (name "{p[1]}" (effects (font (size 1.27 1.27))))'
            f' (number "{p[0]}" (effects (font (size 1.27 1.27)))))'
        )

    lines += ['    )', '  )', ')', '']
    return "\n".join(lines)


def generate_footprint(part: CuratedPart) -> str:
    fp_name = f"{part.name}_Module"
    w, h, d = part.dimensions_mm
    model_name = f"{part.name}.wrl"

    drill = 1.8 if part.pad_style == "sew_tab" else 1.0
    pad_dia = 3.5 if part.pad_style == "sew_tab" else 1.7

    lines = [
        f'(footprint "{fp_name}" (version 20240108) (generator wireframe_libforge)',
        '  (layer "F.Cu")',
        f'  (descr "{part.description}")',
        '  (attr through_hole)',
    ]

    # Outline
    if part.outline_type == "circle":
        radius = w / 2
        lines.extend([
            f'  (fp_circle (center 0 0) (end {radius:.3f} 0) (stroke (width 0.15) (type default)) (fill (type none)) (layer "F.Fab"))',
            f'  (fp_circle (center 0 0) (end {radius:.3f} 0) (stroke (width 0.2) (type default)) (fill (type none)) (layer "F.SilkS"))',
            f'  (fp_circle (center 0 0) (end {radius + 0.5:.3f} 0) (stroke (width 0.05) (type default)) (fill (type none)) (layer "F.CrtYd"))',
        ])
    elif part.outline_type == "arduino_mega":
        pts = [
            (-50.800, -26.670),
            (46.736, -26.670),
            (48.260, -25.146),
            (48.260, -13.970),
            (50.800, -11.430),
            (50.800, 22.860),
            (48.260, 25.400),
            (48.260, 26.670),
            (-50.800, 26.670),
            (-50.800, -26.670),
        ]
        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            lines.append(f'  (fp_line (start {x1:.3f} {y1:.3f}) (end {x2:.3f} {y2:.3f}) (stroke (width 0.15) (type default)) (fill (type none)) (layer "F.Fab"))')
            lines.append(f'  (fp_line (start {x1:.3f} {y1:.3f}) (end {x2:.3f} {y2:.3f}) (stroke (width 0.2) (type default)) (fill (type none)) (layer "F.SilkS"))')
        lines.extend([
            f'  (fp_rect (start {-w/2 - 0.5:.3f} {-h/2 - 0.5:.3f}) (end {w/2 + 0.5:.3f} {h/2 + 0.5:.3f}) (stroke (width 0.05) (type default)) (fill (type none)) (layer "F.CrtYd"))',
            # USB port silkscreen
            '  (fp_line (start -57.150 -17.145) (end -41.275 -17.145) (stroke (width 0.15) (type default)) (layer "F.SilkS"))',
            '  (fp_line (start -57.150 -5.715) (end -41.275 -5.715) (stroke (width 0.15) (type default)) (layer "F.SilkS"))',
            '  (fp_line (start -57.150 -17.145) (end -57.150 -5.715) (stroke (width 0.15) (type default)) (layer "F.SilkS"))',
            '  (fp_line (start -41.275 -17.145) (end -41.275 -5.715) (stroke (width 0.15) (type default)) (layer "F.SilkS"))',
            '  (fp_line (start -44.450 -14.605) (end -44.450 -8.255) (stroke (width 0.15) (type default)) (layer "F.SilkS"))',
            '  (fp_line (start -44.450 -14.605) (end -47.625 -14.605) (stroke (width 0.15) (type default)) (layer "F.SilkS"))',
            '  (fp_line (start -44.450 -8.255) (end -47.625 -8.255) (stroke (width 0.15) (type default)) (layer "F.SilkS"))',
            '  (fp_line (start -47.625 -14.605) (end -47.625 -8.255) (stroke (width 0.15) (type default)) (layer "F.SilkS"))',
            # DC Power Jack silkscreen
            '  (fp_line (start -52.705 14.605) (end -39.370 14.605) (stroke (width 0.15) (type default)) (layer "F.SilkS"))',
            '  (fp_line (start -52.705 23.495) (end -39.370 23.495) (stroke (width 0.15) (type default)) (layer "F.SilkS"))',
            '  (fp_line (start -52.705 14.605) (end -52.705 23.495) (stroke (width 0.15) (type default)) (layer "F.SilkS"))',
            '  (fp_line (start -39.370 14.605) (end -39.370 23.495) (stroke (width 0.15) (type default)) (layer "F.SilkS"))',
            # Header block silk outlines
            '  (fp_rect (start -24.130 22.860) (end -3.810 25.400) (stroke (width 0.15) (type default)) (fill (type none)) (layer "F.SilkS"))',
            '  (fp_rect (start -1.270 22.860) (end 19.050 25.400) (stroke (width 0.15) (type default)) (fill (type none)) (layer "F.SilkS"))',
            '  (fp_rect (start 21.590 22.860) (end 41.910 25.400) (stroke (width 0.15) (type default)) (fill (type none)) (layer "F.SilkS"))',
            '  (fp_rect (start -33.274 -25.400) (end -7.874 -22.860) (stroke (width 0.15) (type default)) (fill (type none)) (layer "F.SilkS"))',
            '  (fp_rect (start -6.350 -25.400) (end 13.970 -22.860) (stroke (width 0.15) (type default)) (fill (type none)) (layer "F.SilkS"))',
            '  (fp_rect (start 16.510 -25.400) (end 36.830 -22.860) (stroke (width 0.15) (type default)) (fill (type none)) (layer "F.SilkS"))',
            '  (fp_rect (start 41.910 -25.400) (end 46.990 20.320) (stroke (width 0.15) (type default)) (fill (type none)) (layer "F.SilkS"))',
            '  (fp_rect (start 11.557 -5.080) (end 16.637 2.540) (stroke (width 0.15) (type default)) (fill (type none)) (layer "F.SilkS"))',
        ])
        # Silkscreen text matching real board & user image
        display_name = part.name.replace("_", " ")
        lines.extend([
            f'  (fp_text user "{display_name}" (at 15.0 10.0 0) (layer "F.SilkS") (effects (font (size 2.5 2.5) (thickness 0.3))))',
            '  (fp_text user "ANALOG IN" (at 20.0 20.5 0) (layer "F.SilkS") (effects (font (size 1.2 1.2) (thickness 0.18))))',
            '  (fp_text user "DIGITAL" (at 40.5 -2.5 90) (layer "F.SilkS") (effects (font (size 1.2 1.2) (thickness 0.18))))',
            '  (fp_text user "PWM" (at -5.0 -20.5 0) (layer "F.SilkS") (effects (font (size 1.2 1.2) (thickness 0.18))))',
            '  (fp_text user "ICSP" (at 14.1 -6.5 0) (layer "F.SilkS") (effects (font (size 1.0 1.0) (thickness 0.15))))',
            '  (fp_text user "TX" (at 10.16 -20.5 0) (layer "F.SilkS") (effects (font (size 1.0 1.0) (thickness 0.15))))',
            '  (fp_text user "RX" (at 12.70 -20.5 0) (layer "F.SilkS") (effects (font (size 1.0 1.0) (thickness 0.15))))',
        ])
    else:
        # Standard rectangular board outline
        lines.extend([
            f'  (fp_rect (start {-w/2:.3f} {-h/2:.3f}) (end {w/2:.3f} {h/2:.3f}) (stroke (width 0.15) (type default)) (fill (type none)) (layer "F.Fab"))',
            f'  (fp_rect (start {-w/2:.3f} {-h/2:.3f}) (end {w/2:.3f} {h/2:.3f}) (stroke (width 0.2) (type default)) (fill (type none)) (layer "F.SilkS"))',
            f'  (fp_rect (start {-w/2 - 0.5:.3f} {-h/2 - 0.5:.3f}) (end {w/2 + 0.5:.3f} {h/2 + 0.5:.3f}) (stroke (width 0.05) (type default)) (layer "F.CrtYd"))',
        ])

    # Mounting holes
    for hx, hy, hdrill in part.holes:
        lines.append(
            f'  (pad "" np_thru_hole circle (at {hx:.3f} {hy:.3f}) (size {hdrill:.3f} {hdrill:.3f}) (drill {hdrill:.3f}) (layers "*.Cu" "*.Mask"))'
        )

    # Pads
    for i, p in enumerate(part.pins):
        p_num, p_name, px, py, p_type, _side = p
        shape = "rect" if i == 0 and part.pad_style != "sew_tab" else "circle"
        lines.append(
            f'  (pad "{p_num}" thru_hole {shape} (at {px:.3f} {py:.3f}) (size {pad_dia:.3f} {pad_dia:.3f}) (drill {drill:.3f}) (layers "*.Cu" "*.Mask"))'
        )

    # 3D model
    lines.extend([
        f'  (model "${{KICAD8_3DMODEL_DIR}}/Curated_Maker.3dshapes/{model_name}"',
        '    (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))',
        ')', ''
    ])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Component Catalog Definitions
# ---------------------------------------------------------------------------

def _make_single_row_pins(labels: list[str], start_x: float, start_y: float, pitch: float, horizontal: bool = True, p_types: list[str] | None = None) -> list[tuple[str, str, float, float, str, str]]:
    res = []
    n = len(labels)
    for i, label in enumerate(labels):
        num = str(i + 1)
        px = start_x + (i * pitch if horizontal else 0.0)
        py = start_y + (0.0 if horizontal else i * pitch)
        pt = p_types[i] if p_types and i < len(p_types) else ("power_in" if label.upper() in ("GND", "VCC", "5V", "3V3", "VIN", "VBAT") else "bidirectional")
        side = "L" if i < (n + 1) // 2 else "R"
        res.append((num, label, px, py, pt, side))
    return res


def _make_dual_row_pins(labels_l: list[str], labels_r: list[str], row_spacing: float, pitch: float) -> list[tuple[str, str, float, float, str, str]]:
    res = []
    nl = len(labels_l)
    first_y = -((nl - 1) * pitch) / 2
    for i, label in enumerate(labels_l):
        num = str(i + 1)
        px = -row_spacing / 2
        py = first_y + i * pitch
        pt = "power_in" if label.upper() in ("GND", "VCC", "5V", "3V3", "VIN", "VBAT", "VDD") else "bidirectional"
        res.append((num, label, px, py, pt, "L"))
    for i, label in enumerate(labels_r):
        num = str(nl + i + 1)
        px = row_spacing / 2
        py = first_y + i * pitch
        pt = "power_in" if label.upper() in ("GND", "VCC", "5V", "3V3", "VIN", "VBAT", "VDD") else "bidirectional"
        res.append((num, label, px, py, pt, "R"))
    return res


def _make_circular_pins(labels: list[str], radius: float) -> list[tuple[str, str, float, float, str, str]]:
    res = []
    n = len(labels)
    for i, label in enumerate(labels):
        num = str(i + 1)
        ang = 2 * math.pi * i / n - math.pi / 2
        px = radius * math.cos(ang)
        py = radius * math.sin(ang)
        pt = "power_in" if label.upper() in ("GND", "+", "-", "VCC", "VBATT", "3.3V", "3V3") else "bidirectional"
        side = "L" if px <= 0 else "R"
        res.append((num, label, px, py, pt, side))
    return res


PARTS: list[CuratedPart] = []

# ---------------------------------------------------------------------------
# 1. Arduino Mega, Due & Uno Ecosystem
# ---------------------------------------------------------------------------

def _make_arduino_mega_pins() -> list[tuple[str, str, float, float, str, str]]:
    pins = []
    # 1. Bottom Power header (8 pins, pitch 2.54mm): NC, IOREF, RESET, 3V3, 5V, GND, GND, VIN
    pwr_labels = ["NC", "IOREF", "RESET", "3V3", "5V", "GND_1", "GND_2", "VIN"]
    pwr_x_start = -22.860
    for i, l in enumerate(pwr_labels):
        pins.append((str(len(pins) + 1), l, pwr_x_start + i * 2.54, 24.130, "power_in" if "GND" in l or l in ("5V", "3V3", "VIN") else "bidirectional", "L"))

    # 2. Bottom Analog header A0-A7 (8 pins, pitch 2.54mm)
    a0_x_start = 0.000
    for i in range(8):
        pins.append((str(len(pins) + 1), f"A{i}", a0_x_start + i * 2.54, 24.130, "input", "L"))

    # 3. Bottom Analog header A8-A15 (8 pins, pitch 2.54mm)
    a8_x_start = 22.860
    for i in range(8, 16):
        pins.append((str(len(pins) + 1), f"A{i}", a8_x_start + (i - 8) * 2.54, 24.130, "input", "L"))

    # 4. Top Digital D0-D7 (8 pins, pitch 2.54mm): D0 at +12.7, D7 at -5.08
    d_low = ["D0/RX0", "D1/TX0", "D2/PWM", "D3/PWM", "D4/PWM", "D5/PWM", "D6/PWM", "D7/PWM"]
    for i, l in enumerate(d_low):
        pins.append((str(len(pins) + 1), l, 12.700 - i * 2.54, -24.130, "bidirectional", "L"))

    # 5. Top Digital D8-D13, GND, AREF, SDA, SCL (10 pins)
    d_high = [
        ("D8/PWM", -9.144, "L"), ("D9/PWM", -11.684, "L"), ("D10/PWM", -14.224, "L"),
        ("D11/PWM", -16.764, "L"), ("D12/PWM", -19.304, "L"), ("D13/PWM", -21.844, "L"),
        ("GND_3", -24.384, "R"), ("AREF", -26.924, "R"), ("SDA", -29.464, "R"), ("SCL", -32.004, "R")
    ]
    for l, px, side in d_high:
        pins.append((str(len(pins) + 1), l, px, -24.130, "power_in" if "GND" in l else "bidirectional", side))

    # 6. Top Communication D14-D21 (8 pins: TX3, RX3, TX2, RX2, TX1, RX1, SDA, SCL)
    comm = ["TX3/D14", "RX3/D15", "TX2/D16", "RX2/D17", "TX1/D18", "RX1/D19", "SDA/D20", "SCL/D21"]
    for i, l in enumerate(comm):
        pins.append((str(len(pins) + 1), l, 17.780 + i * 2.54, -24.130, "bidirectional", "L"))

    # 7. Right End Double Header 2x18 (36 pins: D22-D53, 5V, GND)
    # Row 1 (inner): x = 43.180, Y from -24.130 to 19.050
    # Row 2 (outer): x = 45.720, Y from -24.130 to 19.050
    d_even = ["5V_A"] + [f"D{p}" for p in range(22, 54, 2)] + ["GND_A"]
    d_odd  = ["5V_B"] + [f"D{p}" for p in range(23, 55, 2)] + ["GND_B"]
    for j in range(18):
        py = -24.130 + j * 2.54
        le = d_even[j]
        pins.append((str(len(pins) + 1), le, 43.180, py, "power_in" if "GND" in le or "5V" in le else "bidirectional", "R"))
        lo = d_odd[j]
        pins.append((str(len(pins) + 1), lo, 45.720, py, "power_in" if "GND" in lo or "5V" in lo else "bidirectional", "R"))

    return pins


def _make_nucleo64_pins() -> list[tuple[str, str, float, float, str, str]]:
    pins = []
    # CN7 (Left 2x19 ST Morpho header, pitch 2.54mm, center X = -30.48mm)
    cn7_labels = [
        "PC10", "PC11", "PC12", "PD2", "VDD", "E5V", "~{BOOT0}", "GND", "NC", "NC",
        "NC", "IOREF", "PA13", "~{RESET}", "PA14", "+3V3", "PA15", "+5V", "GND", "GND",
        "PB7", "GND", "PC13", "VIN", "PC14", "NC", "PC15", "PA0", "PH0", "PA1",
        "PH1", "PA4", "VBAT", "PB0", "PC2", "PC1", "PC3", "PC0"
    ]
    for i in range(19):
        py = -22.86 + i * 2.54
        p_odd = cn7_labels[2 * i]
        pins.append((str(2 * i + 1), p_odd, -31.750, py, "power_in" if "GND" in p_odd or "V" in p_odd else "bidirectional", "L"))
        p_even = cn7_labels[2 * i + 1]
        pins.append((str(2 * i + 2), p_even, -29.210, py, "power_in" if "GND" in p_even or "V" in p_even else "bidirectional", "L"))

    # CN10 (Right 2x19 ST Morpho header, pitch 2.54mm, center X = +30.48mm)
    cn10_labels = [
        "PC9", "PC8", "PB8", "PC6", "PB9", "PC5", "AVDD", "U5V", "GND", "NC",
        "PA5", "PA12", "PA6", "PA11", "PA7", "PB12", "PB6", "NC", "PC7", "GND",
        "PA9", "PB2", "PA8", "PB1", "PB10", "PB15", "PB4", "PB14", "PB5", "PB13",
        "PB3", "AGND", "PA10", "PC4", "PA2", "NC", "PA3", "NC"
    ]
    for i in range(19):
        py = -22.86 + i * 2.54
        p_odd = cn10_labels[2 * i]
        pins.append((str(39 + 2 * i), p_odd, 29.210, py, "power_in" if "GND" in p_odd or "V" in p_odd else "bidirectional", "R"))
        p_even = cn10_labels[2 * i + 1]
        pins.append((str(40 + 2 * i), p_even, 31.750, py, "power_in" if "GND" in p_even or "V" in p_even else "bidirectional", "R"))

    # 4 mounting / shield GND pads (pins 77-80)
    pins.append(("77", "GND", -35.000, -22.000, "power_in", "L"))
    pins.append(("78", "GND", -35.000, 22.000, "power_in", "L"))
    pins.append(("79", "GND", 35.000, -22.000, "power_in", "R"))
    pins.append(("80", "GND", 35.000, 22.000, "power_in", "R"))

    return pins


PARTS.append(CuratedPart(
    name="Arduino_Mega_2560",
    description="Arduino Mega 2560 Rev3 development board, ATmega2560 16MHz, 54 digital IO, 16 analog inputs, 4 UARTs, 101.6 x 53.3 mm",
    datasheet="https://docs.arduino.cc/resources/datasheets/A000067-datasheet.pdf",
    provenance_url="https://store.arduino.cc/products/arduino-mega-2560-rev3",
    license="CC-BY-SA-4.0 (Arduino official hardware files); symbol & footprint project-authored",
    outline_type="arduino_mega",
    dimensions_mm=(101.6, 53.34, 12.0),
    color_rgb=(0.0, 0.4, 0.45),
    holes=[(-36.83, 24.13, 3.2), (-35.56, -24.13, 3.2), (15.24, 19.05, 3.2), (15.24, -8.89, 3.2), (39.37, -24.13, 3.2), (45.72, 24.13, 3.2)],
    pins=_make_arduino_mega_pins(),
))

PARTS.append(CuratedPart(
    name="Arduino_Due",
    description="Arduino Due 32-bit ARM Cortex-M3 (Atmel SAM3X8E 84MHz) development board, 3.3V logic, Mega form factor, 101.6 x 53.3 mm",
    datasheet="https://docs.arduino.cc/resources/datasheets/A000062-datasheet.pdf",
    provenance_url="https://store.arduino.cc/products/arduino-due",
    license="CC-BY-SA-4.0; symbol & footprint project-authored",
    outline_type="arduino_mega",
    dimensions_mm=(101.6, 53.34, 12.0),
    color_rgb=(0.0, 0.4, 0.45),
    holes=[(-36.83, 24.13, 3.2), (-35.56, -24.13, 3.2), (15.24, 19.05, 3.2), (15.24, -8.89, 3.2), (39.37, -24.13, 3.2), (45.72, 24.13, 3.2)],
    pins=_make_arduino_mega_pins(),
))

PARTS.append(CuratedPart(
    name="NUCLEO64-F411RE",
    description="STMicroelectronics STM32 Nucleo-64 development board, STM32F411RE Cortex-M4 100MHz 512KB Flash, Arduino Uno V3 & ST Morpho headers, 82.5 x 53.4 mm",
    datasheet="https://www.st.com/resource/en/user_manual/um1724-stm32-nucleo64-boards-stmicroelectronics.pdf",
    provenance_url="https://www.st.com/en/evaluation-tools/nucleo-f411re.html",
    license="STMicroelectronics product documentation; symbol & footprint project-authored",
    dimensions_mm=(82.5, 54.0, 12.0),
    color_rgb=(0.9, 0.9, 0.92),
    holes=[],
    pins=_make_nucleo64_pins(),
))

uno_r4_l = ["NC", "IOREF", "RESET", "3V3", "5V", "GND_A", "GND_B", "VIN", "A0", "A1", "A2", "A3", "A4", "A5"]
uno_r4_r = ["D0/RX", "D1/TX", "D2", "D3/PWM", "D4", "D5/PWM", "D6/PWM", "D7", "D8", "D9/PWM", "D10/PWM", "D11/PWM", "D12", "D13", "GND_C", "AREF", "SDA", "SCL"]
uno_r4_pins = []
for i, l in enumerate(uno_r4_l):
    uno_r4_pins.append((str(i + 1), l, -25.4, -20.0 + i * 2.54, "power_in" if "GND" in l or l in ("5V", "3V3", "VIN") else "bidirectional", "L"))
for i, l in enumerate(uno_r4_r):
    uno_r4_pins.append((str(len(uno_r4_l) + i + 1), l, 25.4, -22.0 + i * 2.54, "power_in" if "GND" in l else "bidirectional", "R"))

PARTS.append(CuratedPart(
    name="Arduino_UNO_R4_Minima",
    description="Arduino UNO R4 Minima, Renesas RA4M1 32-bit Cortex-M4F 48MHz, 5V operating voltage, USB-C, 68.6 x 53.4 mm",
    datasheet="https://docs.arduino.cc/resources/datasheets/ABX00080-datasheet.pdf",
    provenance_url="https://store.arduino.cc/products/uno-r4-minima",
    license="CC-BY-SA-4.0; symbol & footprint project-authored",
    dimensions_mm=(53.4, 68.6, 12.0),
    color_rgb=(0.0, 0.45, 0.5),
    holes=[(-20.32, -26.67, 3.2), (22.86, -26.67, 3.2), (-20.32, 26.67, 3.2), (22.86, 26.67, 3.2)],
    pins=uno_r4_pins,
))

PARTS.append(CuratedPart(
    name="Arduino_UNO_R4_WiFi",
    description="Arduino UNO R4 WiFi, Renesas RA4M1 + ESP32-S3 WiFi/BLE module, 12x8 LED matrix, Qwiic I2C, 68.6 x 53.4 mm",
    datasheet="https://docs.arduino.cc/resources/datasheets/ABX00087-datasheet.pdf",
    provenance_url="https://store.arduino.cc/products/uno-r4-wifi",
    license="CC-BY-SA-4.0; symbol & footprint project-authored",
    dimensions_mm=(53.4, 68.6, 12.0),
    color_rgb=(0.0, 0.45, 0.5),
    holes=[(-20.32, -26.67, 3.2), (22.86, -26.67, 3.2), (-20.32, 26.67, 3.2), (22.86, 26.67, 3.2)],
    pins=uno_r4_pins,
))

# ---------------------------------------------------------------------------
# 2. STM32 Discovery Series
# ---------------------------------------------------------------------------

disc_p1_l = ["GND_1", "VDD_1", "GND_2", "PC1", "PC3", "PA1", "PA3", "PA5", "PA7", "PC5", "PB1", "GND_3", "PE7", "PE9", "PE11", "PE13", "PE15", "PB11", "PB13", "PB15", "PD9", "PD11", "PD13", "PD15", "GND_4"]
disc_p1_r = ["GND_5", "VDD_2", "GND_6", "PC0", "PC2", "PA0", "PA2", "PA4", "PA6", "PC4", "PB0", "PB2", "PE8", "PE10", "PE12", "PE14", "PB10", "PB12", "PB14", "PD8", "PD10", "PD12", "PD14", "NC", "GND_7"]
disc_p2_l = ["GND_8", "5V_1", "3V3_1", "PH0", "NRST", "PC14", "PE6", "PE4", "PE2", "PE0", "PB8", "BOOT0", "PB6", "PB4", "PD7", "PD5", "PD3", "PD1", "PC12", "PC10", "PA14", "PA10", "PA8", "PC8", "GND_9"]
disc_p2_r = ["GND_10", "5V_2", "3V3_2", "PH1", "PC15", "PC13", "PE5", "PE3", "PE1", "PB9", "VDD_3", "PB7", "PB5", "PD6", "PD4", "PD2", "PD0", "PC11", "PC9", "PA15", "PA13", "PA9", "PC7", "PC6", "GND_11"]

disc_pins = []
idx = 1
for i, l in enumerate(disc_p1_l):
    disc_pins.append((str(idx), f"P1_{l}", -28.270, -30.0 + i * 2.54, "power_in" if "GND" in l or "VDD" in l or "5V" in l or "3V3" in l else "bidirectional", "L"))
    idx += 1
for i, l in enumerate(disc_p1_r):
    disc_pins.append((str(idx), f"P1_{l}", -25.730, -30.0 + i * 2.54, "power_in" if "GND" in l or "VDD" in l or "5V" in l or "3V3" in l else "bidirectional", "L"))
    idx += 1
for i, l in enumerate(disc_p2_l):
    disc_pins.append((str(idx), f"P2_{l}", 25.730, -30.0 + i * 2.54, "power_in" if "GND" in l or "VDD" in l or "5V" in l or "3V3" in l else "bidirectional", "R"))
    idx += 1
for i, l in enumerate(disc_p2_r):
    disc_pins.append((str(idx), f"P2_{l}", 28.270, -30.0 + i * 2.54, "power_in" if "GND" in l or "VDD" in l or "5V" in l or "3V3" in l else "bidirectional", "R"))
    idx += 1

PARTS.append(CuratedPart(
    name="STM32F407G-DISC1",
    description="STMicroelectronics STM32F4-Discovery board, STM32F407VGT6 Cortex-M4F 168MHz 1MB Flash, ST-LINK/V2, 2x 2x25 header P1/P2, 97.0 x 66.0 mm",
    datasheet="https://www.st.com/resource/en/user_manual/um1472-stm32f4discovery-highperformance-discovery-board-stmicroelectronics.pdf",
    provenance_url="https://www.st.com/en/evaluation-tools/stm32f4discovery.html",
    license="STMicroelectronics product documentation; symbol & footprint project-authored",
    dimensions_mm=(66.0, 97.0, 15.0),
    color_rgb=(0.05, 0.15, 0.45),
    holes=[(-28.0, -43.0, 3.2), (28.0, -43.0, 3.2), (-28.0, 43.0, 3.2), (28.0, 43.0, 3.2)],
    pins=disc_pins,
))

PARTS.append(CuratedPart(
    name="STM32F3-DISCOVERY",
    description="STMicroelectronics STM32F3-Discovery board, STM32F303VCT6 Cortex-M4 72MHz, 256KB Flash, compass/gyro, 2x 2x25 header P1/P2, 97.0 x 66.0 mm",
    datasheet="https://www.st.com/resource/en/user_manual/um1570-stm32f3discovery-discovery-kit-stmicroelectronics.pdf",
    provenance_url="https://www.st.com/en/evaluation-tools/stm32f3discovery.html",
    license="STMicroelectronics product documentation; symbol & footprint project-authored",
    dimensions_mm=(66.0, 97.0, 15.0),
    color_rgb=(0.05, 0.15, 0.45),
    holes=[(-28.0, -43.0, 3.2), (28.0, -43.0, 3.2), (-28.0, 43.0, 3.2), (28.0, 43.0, 3.2)],
    pins=disc_pins,
))

# ---------------------------------------------------------------------------
# 3. Circular & Wearable Boards
# ---------------------------------------------------------------------------

lily_labels = [
    "D0/RX", "D1/TX", "D2", "D3", "D4", "D5", "D6", "D7",
    "D8", "D9", "D10", "D11", "D12", "D13",
    "A0", "A1", "A2", "A3", "A4", "A5",
    "VCC", "GND"
]
PARTS.append(CuratedPart(
    name="LilyPad-Arduino-328",
    description="SparkFun LilyPad Arduino 328, circular wearable sewable board, ATmega328V 8MHz 3.3V, diameter 50.0 mm",
    datasheet="https://cdn.sparkfun.com/datasheets/Dev/Arduino/Boards/LilyPad-Main-v18.pdf",
    provenance_url="https://www.sparkfun.com/products/13342",
    license="CC-BY-SA-3.0; symbol & footprint project-authored",
    outline_type="circle",
    pad_style="sew_tab",
    dimensions_mm=(50.0, 50.0, 3.5),
    color_rgb=(0.4, 0.1, 0.45),
    pins=_make_circular_pins(lily_labels, 22.0),
))

lily_usb_labels = ["D2/SDA", "D3/SCL", "D9/PWM", "D10/PWM", "D11/PWM", "D13", "A2", "A3", "A4", "A5", "+", "-"]
PARTS.append(CuratedPart(
    name="LilyPad-Arduino-USB",
    description="SparkFun LilyPad Arduino USB, ATmega32U4 with native micro-USB, circular wearable sewable board, diameter 50.0 mm",
    datasheet="https://cdn.sparkfun.com/datasheets/Dev/Arduino/Boards/LilyPad_Arduino_USB_v13.pdf",
    provenance_url="https://www.sparkfun.com/products/12049",
    license="CC-BY-SA-3.0; symbol & footprint project-authored",
    outline_type="circle",
    pad_style="sew_tab",
    dimensions_mm=(50.0, 50.0, 4.0),
    color_rgb=(0.4, 0.1, 0.45),
    pins=_make_circular_pins(lily_usb_labels, 22.0),
))

flora_labels = ["VBATT", "3.3V", "GND_A", "D6", "D9", "D10", "D11", "D12", "SDA", "SCL", "RX", "TX", "RESET", "GND_B"]
PARTS.append(CuratedPart(
    name="Adafruit-Flora",
    description="Adafruit FLORA wearable electronic platform, ATmega32U4 8MHz 3.3V, sewable round PCB, diameter 45.0 mm",
    datasheet="https://cdn-learn.adafruit.com/downloads/pdf/getting-started-with-flora.pdf",
    provenance_url="https://www.adafruit.com/product/659",
    license="Creative Commons Attribution, Share-Alike; symbol & footprint project-authored",
    outline_type="circle",
    pad_style="sew_tab",
    dimensions_mm=(45.0, 45.0, 4.0),
    color_rgb=(0.0, 0.1, 0.15),
    pins=_make_circular_pins(flora_labels, 20.0),
))

cp_labels = ["3.3V", "GND_A", "A1/D6", "A2/D9", "A3/D10", "A4/D3", "A5/D2", "A6/D0", "A7/D1", "GND_B", "VBATT", "TX", "RX", "RESET"]
PARTS.append(CuratedPart(
    name="Adafruit-CircuitPlayground-Express",
    description="Adafruit Circuit Playground Express, ATSAMD21 ARM Cortex-M0+ 48MHz, 14 alligator-clip ring pads, 10 NeoPixels, sensors, diameter 50.8 mm",
    datasheet="https://cdn-learn.adafruit.com/downloads/pdf/adafruit-circuit-playground-express.pdf",
    provenance_url="https://www.adafruit.com/product/3333",
    license="CC-BY-SA-3.0; symbol & footprint project-authored",
    outline_type="circle",
    pad_style="sew_tab",
    dimensions_mm=(50.8, 50.8, 5.0),
    color_rgb=(0.0, 0.1, 0.15),
    pins=_make_circular_pins(cp_labels, 22.5),
))

ubit_labels = ["RING_0", "RING_1", "RING_2", "RING_3V", "RING_GND", "P3", "P0", "P4", "P5", "P6", "P7", "P1", "P8", "P9", "P10", "P11", "P12", "P2", "P13", "P14", "P15", "P16", "P19", "P20"]
ubit_pins = []
for i, l in enumerate(ubit_labels):
    px = -20.0 + i * 1.7
    py = 23.0
    pt = "power_in" if "3V" in l or "GND" in l else "bidirectional"
    side = "L" if i < 12 else "R"
    ubit_pins.append((str(i + 1), l, px, py, pt, side))

PARTS.append(CuratedPart(
    name="BBC-microbit-v2",
    description="BBC micro:bit v2, Nordic nRF52833 BLE ARM Cortex-M4 64MHz, edge connector + 5 ring pads for alligator clips, 51.6 x 42.0 mm",
    datasheet="https://tech.microbit.org/hardware/1-5-revision/",
    provenance_url="https://microbit.org",
    license="Solderpad Hardware Licence v0.51; symbol & footprint project-authored",
    dimensions_mm=(51.6, 42.0, 6.0),
    color_rgb=(0.1, 0.1, 0.1),
    holes=[(-19.0, -15.0, 3.2), (19.0, -15.0, 3.2)],
    pins=ubit_pins,
))

# ---------------------------------------------------------------------------
# 4. Displays (OLED, TFT, LCD, 7-Segment, LED Matrix)
# ---------------------------------------------------------------------------

oled_096_i2c = _make_single_row_pins(["GND", "VCC", "SCL", "SDA"], -3.81, -11.0, 2.54)
PARTS.append(CuratedPart(
    name="OLED-0.96-I2C-128x64",
    reference="DISP",
    keywords="display oled graphic ssd1306 i2c 128x64",
    description="0.96 inch OLED graphic display module, 128x64 pixels, SSD1306 controller, I2C interface 4-pin header, 27.0 x 27.0 mm",
    datasheet="https://cdn-shop.adafruit.com/datasheets/SSD1306.pdf",
    provenance_url="https://www.adafruit.com/product/326",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(27.0, 27.0, 4.0),
    color_rgb=(0.05, 0.1, 0.25),
    holes=[(-11.5, -11.5, 2.0), (11.5, -11.5, 2.0), (-11.5, 11.5, 2.0), (11.5, 11.5, 2.0)],
    pins=oled_096_i2c,
))

oled_096_spi = _make_single_row_pins(["GND", "VCC", "D0/SCK", "D1/MOSI", "RES", "DC", "CS"], -7.62, -11.0, 2.54)
PARTS.append(CuratedPart(
    name="OLED-0.96-SPI-128x64",
    reference="DISP",
    keywords="display oled graphic ssd1306 spi 128x64",
    description="0.96 inch OLED graphic display module, 128x64 pixels, SSD1306 controller, 4-wire SPI 7-pin header, 27.0 x 27.0 mm",
    datasheet="https://cdn-shop.adafruit.com/datasheets/SSD1306.pdf",
    provenance_url="https://www.adafruit.com/product/271",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(27.0, 27.0, 4.0),
    color_rgb=(0.05, 0.1, 0.25),
    holes=[(-11.5, -11.5, 2.0), (11.5, -11.5, 2.0), (-11.5, 11.5, 2.0), (11.5, 11.5, 2.0)],
    pins=oled_096_spi,
))

oled_091_i2c = _make_single_row_pins(["GND", "VCC", "SCL", "SDA"], -3.81, -4.5, 2.54)
PARTS.append(CuratedPart(
    name="OLED-0.91-I2C-128x32",
    reference="DISP",
    keywords="display oled graphic ssd1306 i2c 128x32",
    description="0.91 inch narrow OLED graphic display module, 128x32 pixels, SSD1306 controller, I2C 4-pin header, 38.0 x 12.0 mm",
    datasheet="https://cdn-shop.adafruit.com/datasheets/SSD1306.pdf",
    provenance_url="https://www.adafruit.com/product/4440",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(38.0, 12.0, 3.5),
    color_rgb=(0.05, 0.1, 0.25),
    pins=oled_091_i2c,
))

oled_13_i2c = _make_single_row_pins(["VCC", "GND", "SCL", "SDA"], -3.81, -14.0, 2.54)
PARTS.append(CuratedPart(
    name="OLED-1.3-I2C-128x64",
    reference="DISP",
    keywords="display oled graphic sh1106 i2c 128x64",
    description="1.3 inch OLED graphic display module, 128x64 pixels, SH1106 controller, I2C 4-pin header, 35.5 x 33.5 mm",
    datasheet="https://www.waveshare.com/w/upload/e/e3/SH1106.pdf",
    provenance_url="https://www.waveshare.com/1.3inch-oled-b.htm",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(35.5, 33.5, 4.0),
    color_rgb=(0.05, 0.1, 0.25),
    holes=[(-15.0, -14.0, 2.5), (15.0, -14.0, 2.5), (-15.0, 14.0, 2.5), (15.0, 14.0, 2.5)],
    pins=oled_13_i2c,
))

tft_18_spi = _make_single_row_pins(["GND", "VCC", "SCL", "SDA", "RES", "DC", "CS", "BLK"], -8.89, 25.0, 2.54)
PARTS.append(CuratedPart(
    name="TFT-1.8-SPI-ST7735",
    reference="DISP",
    keywords="display tft lcd color graphic st7735 spi 128x160",
    description="1.8 inch full-color TFT LCD module with micro-SD slot, 128x160 pixels, ST7735 driver, 8-pin SPI header, 58.0 x 34.0 mm",
    datasheet="https://www.displayfuture.com/Display/datasheet/controller/ST7735.pdf",
    provenance_url="https://www.adafruit.com/product/358",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(34.0, 58.0, 5.0),
    color_rgb=(0.8, 0.1, 0.1),
    holes=[(-14.0, -26.0, 2.0), (14.0, -26.0, 2.0), (-14.0, 26.0, 2.0), (14.0, 26.0, 2.0)],
    pins=tft_18_spi,
))

tft_24_spi = _make_single_row_pins(
    ["VCC", "GND", "CS", "RESET", "DC", "SDI/MOSI", "SCK", "LED", "SDO/MISO", "T_CLK", "T_CS", "T_DIN", "T_DO", "T_IRQ"],
    -16.51, 35.0, 2.54
)
PARTS.append(CuratedPart(
    name="TFT-2.4-SPI-ILI9341",
    reference="DISP",
    keywords="display tft lcd color graphic ili9341 touch xpt2046 spi 240x320",
    description="2.4 inch 240x320 TFT LCD module with resistive touch (XPT2046) & SD socket, ILI9341 driver, 14-pin SPI header, 77.0 x 42.5 mm",
    datasheet="https://cdn-shop.adafruit.com/datasheets/ILI9341.pdf",
    provenance_url="https://www.adafruit.com/product/2478",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(42.5, 77.0, 6.0),
    color_rgb=(0.8, 0.1, 0.1),
    holes=[(-18.0, -35.0, 2.5), (18.0, -35.0, 2.5), (-18.0, 35.0, 2.5), (18.0, 35.0, 2.5)],
    pins=tft_24_spi,
))

tft_13_spi = _make_single_row_pins(["GND", "VCC", "SCL", "SDA", "RES", "DC", "BLK"], -7.62, 16.0, 2.54)
PARTS.append(CuratedPart(
    name="TFT-1.3-SPI-ST7789",
    reference="DISP",
    keywords="display tft ips color graphic st7789 spi 240x240",
    description="1.3 inch IPS full-color TFT display module, 240x240 pixels, ST7789 driver, 7-pin SPI header, 39.0 x 28.0 mm",
    datasheet="https://www.waveshare.com/w/upload/a/ae/ST7789_Datasheet.pdf",
    provenance_url="https://www.waveshare.com/1.3inch-lcd-module.htm",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(28.0, 39.0, 4.0),
    color_rgb=(0.1, 0.2, 0.6),
    pins=tft_13_spi,
))

epaper_213 = _make_single_row_pins(["VCC", "GND", "DIN", "CLK", "CS", "DC", "RST", "BUSY"], -8.89, 28.0, 2.54)
PARTS.append(CuratedPart(
    name="E-Paper-2.13-SPI",
    reference="DISP",
    keywords="display epaper eink graphic waveshare spi 250x122",
    description="Waveshare 2.13 inch e-Paper / e-Ink graphic display module, 250x122 pixels, ultra-low power, SPI 8-pin header, 65.0 x 30.2 mm",
    datasheet="https://www.waveshare.com/wiki/2.13inch_e-Paper_HAT",
    provenance_url="https://www.waveshare.com/2.13inch-e-paper-module.htm",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(30.2, 65.0, 3.5),
    color_rgb=(0.1, 0.2, 0.6),
    holes=[(-12.0, -29.0, 2.5), (12.0, -29.0, 2.5), (-12.0, 29.0, 2.5), (12.0, 29.0, 2.5)],
    pins=epaper_213,
))

tm1637_pins = _make_single_row_pins(["GND", "VCC", "DIO", "CLK"], -3.81, 9.0, 2.54)
PARTS.append(CuratedPart(
    name="TM1637-4Digit-Display",
    reference="DISP",
    keywords="display segment led 7-segment tm1637 clock 4-digit",
    description="0.36 inch 4-digit 7-segment LED display module with clock colon, TM1637 driver, 4-pin header (GND, VCC, DIO, CLK), 42.0 x 24.0 mm",
    datasheet="https://datasheet.lcsc.com/lcsc/2108131830_TM-Titan-Micro-Elec-TM1637_C2683935.pdf",
    provenance_url="https://www.makerfabs.com/tm1637-4-digit-display.html",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(42.0, 24.0, 11.0),
    color_rgb=(0.05, 0.1, 0.3),
    holes=[(-18.0, -9.0, 2.2), (18.0, -9.0, 2.2), (-18.0, 9.0, 2.2), (18.0, 9.0, 2.2)],
    pins=tm1637_pins,
))

max7219_8dig_pins = _make_single_row_pins(["VCC", "GND", "DIN", "CS", "CLK"], -38.0, 0.0, 2.54, horizontal=False)
PARTS.append(CuratedPart(
    name="MAX7219-8Digit-Display",
    reference="DISP",
    keywords="display segment led 7-segment max7219 8-digit spi",
    description="8-digit 7-segment LED display module with MAX7219 driver, SPI serial interface 5-pin header, 82.0 x 15.0 mm",
    datasheet="https://datasheets.maximintegrated.com/en/ds/MAX7219-MAX7221.pdf",
    provenance_url="https://www.makerfabs.com/max7219-8-digit-led-display-module.html",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(82.0, 15.0, 12.0),
    color_rgb=(0.05, 0.1, 0.3),
    holes=[(-38.0, -5.0, 3.0), (38.0, -5.0, 3.0), (-38.0, 5.0, 3.0), (38.0, 5.0, 3.0)],
    pins=max7219_8dig_pins,
))

max7219_matrix_pins = _make_single_row_pins(["VCC", "GND", "DIN", "CS", "CLK"], -5.08, 13.5, 2.54)
PARTS.append(CuratedPart(
    name="MAX7219-DotMatrix-8x8",
    reference="DISP",
    keywords="display led matrix dot 8x8 max7219 spi",
    description="8x8 red LED dot matrix display module with MAX7219 driver, cascadable SPI 5-pin header, 32.0 x 32.0 mm",
    datasheet="https://datasheets.maximintegrated.com/en/ds/MAX7219-MAX7221.pdf",
    provenance_url="https://www.makerfabs.com/max7219-dot-matrix-module.html",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(32.0, 32.0, 13.0),
    color_rgb=(0.05, 0.1, 0.3),
    pins=max7219_matrix_pins,
))

lcd_1602_pins = _make_single_row_pins(["GND", "VCC", "SDA", "SCL"], -36.0, -15.0, 2.54, horizontal=False)
PARTS.append(CuratedPart(
    name="LCD-1602-I2C",
    reference="DISP",
    keywords="display lcd character 1602 pcf8574 i2c 16x2",
    description="16x2 Character LCD display module with PCF8574 I2C backpack interface 4-pin header, HD44780 standard, 80.0 x 36.0 mm",
    datasheet="https://www.sparkfun.com/datasheets/LCD/HD44780.pdf",
    provenance_url="https://www.sparkfun.com/products/16398",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(80.0, 36.0, 13.0),
    color_rgb=(0.05, 0.4, 0.15),
    holes=[(-37.5, -15.5, 3.0), (37.5, -15.5, 3.0), (-37.5, 15.5, 3.0), (37.5, 15.5, 3.0)],
    pins=lcd_1602_pins,
))

lcd_2004_pins = _make_single_row_pins(["GND", "VCC", "SDA", "SCL"], -45.0, -25.0, 2.54, horizontal=False)
PARTS.append(CuratedPart(
    name="LCD-2004-I2C",
    reference="DISP",
    keywords="display lcd character 2004 pcf8574 i2c 20x4",
    description="20x4 Character LCD display module with PCF8574 I2C backpack interface 4-pin header, HD44780 standard, 98.0 x 60.0 mm",
    datasheet="https://www.sparkfun.com/datasheets/LCD/HD44780.pdf",
    provenance_url="https://www.sunfounder.com/products/i2c-lcd2004-module",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(98.0, 60.0, 13.0),
    color_rgb=(0.05, 0.4, 0.15),
    holes=[(-46.5, -27.5, 3.5), (46.5, -27.5, 3.5), (-46.5, 27.5, 3.5), (46.5, 27.5, 3.5)],
    pins=lcd_2004_pins,
))

# ---------------------------------------------------------------------------
# 5. Wireless & RF Modules
# ---------------------------------------------------------------------------

nrf_pins = _make_dual_row_pins(
    ["GND", "CE", "SCK", "MISO"],
    ["VCC", "CSN", "MOSI", "IRQ"],
    row_spacing=2.54, pitch=2.54
)
nrf_pins_placed = []
for p in nrf_pins:
    num, label, px, py, pt, side = p
    nrf_pins_placed.append((num, label, px - 10.0, py, pt, side))

PARTS.append(CuratedPart(
    name="NRF24L01-Module",
    keywords="wireless rf transceiver 2.4ghz nrf24l01 spi",
    description="Nordic nRF24L01+ 2.4GHz ISM band RF transceiver module with integrated PCB antenna, 2x4 2.54mm header, 29.0 x 15.0 mm",
    datasheet="https://www.sparkfun.com/datasheets/Components/SMD/nRF24L01Pluss_Preliminary_Product_Specification_v1_0.pdf",
    provenance_url="https://www.sparkfun.com/products/691",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(29.0, 15.0, 4.5),
    color_rgb=(0.1, 0.15, 0.1),
    pins=nrf_pins_placed,
))

PARTS.append(CuratedPart(
    name="NRF24L01-PA-LNA",
    keywords="wireless rf transceiver 2.4ghz nrf24l01 pa lna sma 1000m",
    description="Long-range nRF24L01+ 2.4GHz RF transceiver module with RFX2401C PA/LNA and external SMA antenna, 2x4 2.54mm header, 41.0 x 15.5 mm",
    datasheet="https://www.makerfabs.com/desfile/files/NRF24L01P_PA_LNA.pdf",
    provenance_url="https://www.makerfabs.com/nrf24l01-pa-lna.html",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(41.0, 15.5, 6.0),
    color_rgb=(0.1, 0.15, 0.1),
    pins=nrf_pins_placed,
))

esp01_pins = _make_dual_row_pins(
    ["GND", "GPIO2", "GPIO0", "RXD"],
    ["VCC", "CH_PD", "RST", "TXD"],
    row_spacing=2.54, pitch=2.54
)
esp01_placed = [(p[0], p[1], p[2] - 8.0, p[3], p[4], p[5]) for p in esp01_pins]
PARTS.append(CuratedPart(
    name="ESP-01S-WiFi",
    keywords="wireless wifi esp8266 iot module uart",
    description="Ai-Thinker ESP-01S ESP8266 WiFi SoC module with 1MB Flash, PCB antenna, 2x4 2.54mm header, 24.8 x 14.4 mm",
    datasheet="https://docs.ai-thinker.com/_media/esp8266/docs/esp-01s_product_specification_en.pdf",
    provenance_url="https://docs.ai-thinker.com/en/esp8266",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(24.8, 14.4, 4.5),
    color_rgb=(0.05, 0.1, 0.1),
    pins=esp01_placed,
))

hc05_pins = _make_single_row_pins(["STATE", "RXD", "TXD", "GND", "VCC", "EN"], 0.0, -15.0, 2.54, horizontal=True)
PARTS.append(CuratedPart(
    name="HC-05-Bluetooth",
    keywords="wireless bluetooth spp uart classic hc05 master slave",
    description="HC-05 Classic Bluetooth 2.0+EDR SPP serial module on breakout board with button, 6-pin 2.54mm header, 37.3 x 15.5 mm",
    datasheet="https://components101.com/sites/default/files/component_datasheet/HC-05%20Datasheet.pdf",
    provenance_url="https://components101.com/wireless/hc-05-bluetooth-module",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(15.5, 37.3, 4.0),
    color_rgb=(0.1, 0.25, 0.65),
    pins=hc05_pins,
))

hc06_pins = _make_single_row_pins(["VCC", "GND", "TXD", "RXD"], 0.0, -15.0, 2.54, horizontal=True)
PARTS.append(CuratedPart(
    name="HC-06-Bluetooth",
    keywords="wireless bluetooth spp uart classic hc06 slave",
    description="HC-06 Classic Bluetooth 2.0+EDR SPP serial slave module on breakout board, 4-pin 2.54mm header, 37.3 x 15.5 mm",
    datasheet="https://components101.com/sites/default/files/component_datasheet/HC-06%20Datasheet.pdf",
    provenance_url="https://components101.com/wireless/hc-06-bluetooth-module",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(15.5, 37.3, 4.0),
    color_rgb=(0.1, 0.25, 0.65),
    pins=hc06_pins,
))

hm10_pins = _make_single_row_pins(["STATE", "VCC", "GND", "TXD", "RXD", "BRK"], 0.0, -16.0, 2.54, horizontal=True)
PARTS.append(CuratedPart(
    name="HM-10-BLE-Module",
    keywords="wireless bluetooth ble 4.0 cc2541 uart low energy",
    description="HM-10 Bluetooth Low Energy (BLE 4.0) CC2541 serial transceiver module on breakout board, 6-pin 2.54mm header, 40.0 x 16.0 mm",
    datasheet="https://www.huamaosoft.com/upload/2016/11/17/20161117173810243.pdf",
    provenance_url="https://www.huamaosoft.com",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(16.0, 40.0, 4.0),
    color_rgb=(0.1, 0.25, 0.65),
    pins=hm10_pins,
))

ra02_l = ["GND_1", "DIO1", "DIO2", "DIO3", "VCC", "MISO", "MOSI", "SCK"]
ra02_r = ["NSS", "RESET", "DIO5", "DIO4", "DIO0", "GND_2", "ANT", "GND_3"]
ra02_pins = _make_dual_row_pins(ra02_l, ra02_r, row_spacing=15.0, pitch=2.0)
PARTS.append(CuratedPart(
    name="LoRa-Ra-02-SX1278",
    keywords="wireless lora sx1278 433mhz ai-thinker ra-02 long-range spi",
    description="Ai-Thinker Ra-02 433MHz LoRa transceiver module based on Semtech SX1278, IPEX antenna connector, 16-pin 2.0mm header, 17.0 x 16.0 mm",
    datasheet="https://docs.ai-thinker.com/_media/lora/docs/ra-02_product_specification_en.pdf",
    provenance_url="https://docs.ai-thinker.com/en/lora",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(16.0, 17.0, 3.5),
    color_rgb=(0.05, 0.1, 0.25),
    pins=ra02_pins,
))

e32_pins = _make_single_row_pins(["M0", "M1", "RXD", "TXD", "AUX", "VCC", "GND"], -7.62, 16.0, 2.54)
PARTS.append(CuratedPart(
    name="EBYTE-E32-433T20D",
    keywords="wireless lora ebyte e32 433mhz uart transparent 100mw 3000m",
    description="EBYTE E32-433T20D UART SX1278 433MHz 100mW wireless transceiver module with SMA antenna connector, 7-pin 2.54mm header, 36.0 x 21.0 mm",
    datasheet="https://www.ebyte.com/en/pdf-down.aspx?id=132",
    provenance_url="https://www.cdebyte.com/products/E32-433T20D",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(21.0, 36.0, 6.0),
    color_rgb=(0.1, 0.15, 0.4),
    pins=e32_pins,
))

sim800l_pins = _make_single_row_pins(["NET", "VCC", "RST", "RXD", "TXD", "GND", "RING"], -7.62, 10.0, 2.54)
PARTS.append(CuratedPart(
    name="SIM800L-GPRS-Module",
    keywords="wireless cellular gsm gprs sim800l quad-band uart iot",
    description="SIM800L Quad-band GSM/GPRS breakout module with micro-SIM socket and spring antenna, 7-pin 2.54mm header, 25.0 x 23.0 mm",
    datasheet="https://www.simcom.com/product/SIM800L.html",
    provenance_url="https://components101.com/wireless/sim800l-gsm-gprs-module",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(25.0, 23.0, 5.0),
    color_rgb=(0.8, 0.1, 0.1),
    pins=sim800l_pins,
))

neo6m_pins = _make_single_row_pins(["VCC", "RX", "TX", "GND", "PPS"], -5.08, 11.0, 2.54)
PARTS.append(CuratedPart(
    name="NEO-6M-GPS-Module",
    keywords="wireless gps gnss u-blox neo-6m positioning uart eeprom",
    description="u-blox NEO-6M GPS satellite receiver module with onboard ceramic patch antenna and EEPROM, 5-pin 2.54mm header, 36.0 x 26.0 mm",
    datasheet="https://www.u-blox.com/sites/default/files/products/documents/NEO-6_DataSheet_(GPS.G6-HW-09005).pdf",
    provenance_url="https://www.u-blox.com/en/product/neo-6-series",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(26.0, 36.0, 7.0),
    color_rgb=(0.1, 0.25, 0.65),
    holes=[(-10.0, -15.0, 3.0), (10.0, -15.0, 3.0), (-10.0, 15.0, 3.0), (10.0, 15.0, 3.0)],
    pins=neo6m_pins,
))

rc522_pins = _make_single_row_pins(["SDA/SS", "SCK", "MOSI", "MISO", "IRQ", "GND", "RST", "3.3V"], -8.89, 27.0, 2.54)
PARTS.append(CuratedPart(
    name="RC522-RFID-Module",
    keywords="wireless rfid nfc 13.56mhz mfrc522 mifare spi reader",
    description="MFRC522 13.56MHz RFID / NFC contactless reader module with integrated PCB coil antenna, 8-pin 2.54mm SPI header, 60.0 x 40.0 mm",
    datasheet="https://www.nxp.com/docs/en/data-sheet/MFRC522.pdf",
    provenance_url="https://components101.com/modules/rc522-rfid-module",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(40.0, 60.0, 5.0),
    color_rgb=(0.1, 0.25, 0.65),
    holes=[(-17.0, -27.0, 3.0), (17.0, -27.0, 3.0), (-17.0, 27.0, 3.0), (17.0, 27.0, 3.0)],
    pins=rc522_pins,
))



# ==============================================================================
# 5. Multi-Digit 7-Segment & Multi-Block LED Matrix Displays
# ==============================================================================

# 1. 0.56" 2-Digit 7-Segment Display (5261AS / 5261BS)
p5261_pins = [
    ("1", "E", -5.08, 7.62, "input", "L"),
    ("2", "D", -2.54, 7.62, "input", "L"),
    ("3", "DP", 0.0, 7.62, "input", "L"),
    ("4", "C", 2.54, 7.62, "input", "L"),
    ("5", "DIG2", 5.08, 7.62, "power_in", "L"),
    ("6", "B", 5.08, -7.62, "input", "R"),
    ("7", "A", 2.54, -7.62, "input", "R"),
    ("8", "DIG1", 0.0, -7.62, "power_in", "R"),
    ("9", "F", -2.54, -7.62, "input", "R"),
    ("10", "G", -5.08, -7.62, "input", "R"),
]
PARTS.append(CuratedPart(
    name="LED-7Segment-2Digit-0.56in",
    reference="DISP",
    keywords="display led segment 7-segment 2-digit 0.56 5261as 5261bs dual dip-10",
    description="0.56 inch 2-digit 7-segment LED display, 10-pin DIP multiplexed (5261AS / 5261BS compatible), 25.0 x 19.0 mm",
    datasheet="https://datasheet.lcsc.com/lcsc/1811081912_FUXIN-5261AS_C317180.pdf",
    provenance_url="https://www.sparkfun.com/products/11408",
    license="published vendor standard component; symbol & footprint project-authored",
    dimensions_mm=(25.0, 19.0, 8.0),
    color_rgb=(0.1, 0.1, 0.1),
    pins=p5261_pins,
))

# 2. 0.36" 3-Digit 7-Segment Display (3361AS / 3361BS)
p3361_pins = [
    ("1", "E", -6.35, 3.81, "input", "L"),
    ("2", "D", -3.81, 3.81, "input", "L"),
    ("3", "DP", -1.27, 3.81, "input", "L"),
    ("4", "C", 1.27, 3.81, "input", "L"),
    ("5", "G", 3.81, 3.81, "input", "L"),
    ("6", "DIG3", 6.35, 3.81, "power_in", "L"),
    ("7", "B", 5.08, -3.81, "input", "R"),
    ("8", "DIG2", 2.54, -3.81, "power_in", "R"),
    ("9", "F", 0.0, -3.81, "input", "R"),
    ("10", "A", -2.54, -3.81, "input", "R"),
    ("11", "DIG1", -5.08, -3.81, "power_in", "R"),
]
PARTS.append(CuratedPart(
    name="LED-7Segment-3Digit-0.36in",
    reference="DISP",
    keywords="display led segment 7-segment 3-digit 0.36 3361as 3361bs triple",
    description="0.36 inch 3-digit 7-segment LED display, 11-pin compact DIP (3361AS / 3361BS compatible), 22.5 x 14.0 mm",
    datasheet="https://datasheet.lcsc.com/lcsc/1811081912_FUXIN-3361AS_C317178.pdf",
    provenance_url="https://www.adafruit.com/product/1270",
    license="published vendor standard component; symbol & footprint project-authored",
    dimensions_mm=(22.5, 14.0, 7.2),
    color_rgb=(0.1, 0.1, 0.1),
    pins=p3361_pins,
))

# 3. 0.56" 3-Digit 7-Segment Display (5361AS / 5361BS)
p5361_pins = [
    ("1", "E", -6.35, 7.62, "input", "L"),
    ("2", "D", -3.81, 7.62, "input", "L"),
    ("3", "DP", -1.27, 7.62, "input", "L"),
    ("4", "C", 1.27, 7.62, "input", "L"),
    ("5", "G", 3.81, 7.62, "input", "L"),
    ("6", "DIG3", 6.35, 7.62, "power_in", "L"),
    ("7", "B", 6.35, -7.62, "input", "R"),
    ("8", "DIG2", 3.81, -7.62, "power_in", "R"),
    ("9", "NC", 1.27, -7.62, "no_connect", "R"),
    ("10", "F", -1.27, -7.62, "input", "R"),
    ("11", "A", -3.81, -7.62, "input", "R"),
    ("12", "DIG1", -6.35, -7.62, "power_in", "R"),
]
PARTS.append(CuratedPart(
    name="LED-7Segment-3Digit-0.56in",
    reference="DISP",
    keywords="display led segment 7-segment 3-digit 0.56 5361as 5361bs triple dip-12",
    description="0.56 inch 3-digit 7-segment LED display, 12-pin DIP multiplexed (5361AS / 5361BS compatible), 37.6 x 19.0 mm",
    datasheet="https://datasheet.lcsc.com/lcsc/1811081912_FUXIN-5361AS_C317181.pdf",
    provenance_url="https://www.sparkfun.com/products/11409",
    license="published vendor standard component; symbol & footprint project-authored",
    dimensions_mm=(37.6, 19.0, 8.0),
    color_rgb=(0.1, 0.1, 0.1),
    pins=p5361_pins,
))

# 4. 0.56" 4-Digit 7-Segment Display with Clock Colon (5461AS-Clock / 5641BS-Clock)
p5461_clock_pins = [
    ("1", "E", -6.35, 7.62, "input", "L"),
    ("2", "D", -3.81, 7.62, "input", "L"),
    ("3", "COLON", -1.27, 7.62, "input", "L"),
    ("4", "C", 1.27, 7.62, "input", "L"),
    ("5", "G", 3.81, 7.62, "input", "L"),
    ("6", "DIG4", 6.35, 7.62, "power_in", "L"),
    ("7", "B", 6.35, -7.62, "input", "R"),
    ("8", "DIG3", 3.81, -7.62, "power_in", "R"),
    ("9", "DIG2", 1.27, -7.62, "power_in", "R"),
    ("10", "F", -1.27, -7.62, "input", "R"),
    ("11", "A", -3.81, -7.62, "input", "R"),
    ("12", "DIG1", -6.35, -7.62, "power_in", "R"),
]
PARTS.append(CuratedPart(
    name="LED-7Segment-4Digit-Clock-0.56in",
    reference="DISP",
    keywords="display led segment 7-segment 4-digit 0.56 clock colon 5461as 5641bs digital-clock",
    description="0.56 inch 4-digit 7-segment LED display with central clock colon (:), 12-pin DIP (5461AS-Clock / 5641BS-Clock), 50.3 x 19.0 mm",
    datasheet="https://datasheet.lcsc.com/lcsc/1811081912_FUXIN-5461AS_C317182.pdf",
    provenance_url="https://www.adafruit.com/product/811",
    license="published vendor standard component; symbol & footprint project-authored",
    dimensions_mm=(50.3, 19.0, 8.0),
    color_rgb=(0.1, 0.1, 0.1),
    pins=p5461_clock_pins,
))

# 5. TM1638 8-Digit Display + 8 Keys + 8 Dual-Color LEDs Module
tm1638_pins = [
    ("1", "VCC", 34.0, -5.08, "power_in", "L"),
    ("2", "GND", 34.0, -2.54, "power_in", "L"),
    ("3", "CLK", 34.0, 0.0, "input", "L"),
    ("4", "DIO", 34.0, 2.54, "bidirectional", "R"),
    ("5", "STB", 34.0, 5.08, "input", "R"),
]
PARTS.append(CuratedPart(
    name="TM1638-8Digit-Display-Key-Module",
    reference="DISP",
    keywords="display segment led 7-segment tm1638 8-digit key buttons leds spi keypad",
    description="TM1638 8-digit 7-segment display module with 8 push buttons and 8 bi-color LEDs, 5-pin serial interface, 76.2 x 50.8 mm",
    datasheet="https://datasheet.lcsc.com/lcsc/2108131830_TM-Titan-Micro-Elec-TM1638_C2683936.pdf",
    provenance_url="https://www.handsontec.com/dataspecs/module/TM1638.pdf",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(76.2, 50.8, 12.0),
    color_rgb=(0.05, 0.1, 0.3),
    holes=[(-35.0, -22.0, 3.2), (35.0, -22.0, 3.2), (-35.0, 22.0, 3.2), (35.0, 22.0, 3.2)],
    pins=tm1638_pins,
))

# 6. HT16K33 4-Digit 14-Segment Alphanumeric Backpack (0.54in)
ht16k33_alpha_pins = [
    ("1", "VCC", -5.08, 11.43, "power_in", "L"),
    ("2", "GND", -2.54, 11.43, "power_in", "L"),
    ("3", "SDA", 0.0, 11.43, "bidirectional", "R"),
    ("4", "SCL", 2.54, 11.43, "input", "R"),
    ("5", "IO", 5.08, 11.43, "bidirectional", "R"),
]
PARTS.append(CuratedPart(
    name="HT16K33-4Digit-14Seg-Alphanumeric",
    reference="DISP",
    keywords="display alphanumeric 14-segment ht16k33 i2c 4-character adafruit feather backpack",
    description="0.54 inch 4-character 14-segment alphanumeric LED display module with HT16K33 I2C driver, 50.8 x 28.0 mm",
    datasheet="https://cdn-shop.adafruit.com/datasheets/ht16K33v110.pdf",
    provenance_url="https://www.adafruit.com/product/1911",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(50.8, 28.0, 12.0),
    color_rgb=(0.05, 0.1, 0.3),
    holes=[(-22.0, -11.0, 2.5), (22.0, -11.0, 2.5), (-22.0, 11.0, 2.5), (22.0, 11.0, 2.5)],
    pins=ht16k33_alpha_pins,
))

# 7. HT16K33 4-Digit 7-Segment Backpack (0.56in)
ht16k33_7seg_pins = [
    ("1", "VCC", -3.81, 11.43, "power_in", "L"),
    ("2", "GND", -1.27, 11.43, "power_in", "L"),
    ("3", "SDA", 1.27, 11.43, "bidirectional", "R"),
    ("4", "SCL", 3.81, 11.43, "input", "R"),
]
PARTS.append(CuratedPart(
    name="HT16K33-4Digit-7Segment-0.56in",
    reference="DISP",
    keywords="display segment led 7-segment ht16k33 i2c 4-digit 0.56 clock backpack",
    description="0.56 inch 4-digit 7-segment LED display module with HT16K33 I2C backpack and clock colon, 50.0 x 28.0 mm",
    datasheet="https://cdn-shop.adafruit.com/datasheets/ht16K33v110.pdf",
    provenance_url="https://www.adafruit.com/product/878",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(50.0, 28.0, 12.0),
    color_rgb=(0.05, 0.1, 0.3),
    holes=[(-21.0, -10.0, 2.5), (21.0, -10.0, 2.5), (-21.0, 10.0, 2.5), (21.0, 10.0, 2.5)],
    pins=ht16k33_7seg_pins,
))

# 8. MAX7219 Dot Matrix 4-in-1 Module (32x8)
max7219_4in1_pins = [
    ("1", "VCC_IN", -61.0, -5.08, "power_in", "L"),
    ("2", "GND_IN", -61.0, -2.54, "power_in", "L"),
    ("3", "DIN", -61.0, 0.0, "input", "L"),
    ("4", "CS_IN", -61.0, 2.54, "input", "L"),
    ("5", "CLK_IN", -61.0, 5.08, "input", "L"),
    ("6", "VCC_OUT", 61.0, -5.08, "power_out", "R"),
    ("7", "GND_OUT", 61.0, -2.54, "power_out", "R"),
    ("8", "DOUT", 61.0, 0.0, "output", "R"),
    ("9", "CS_OUT", 61.0, 2.54, "output", "R"),
    ("10", "CLK_OUT", 61.0, 5.08, "output", "R"),
]
PARTS.append(CuratedPart(
    name="MAX7219-DotMatrix-4in1-32x8",
    reference="DISP",
    keywords="display led matrix dot 32x8 8x8 4in1 4-block max7219 spi daisy-chain",
    description="32x8 Red LED dot matrix display module (4 cascaded 8x8 blocks, 4x MAX7219 drivers), SPI input & daisy-chain output, 128.0 x 32.0 mm",
    datasheet="https://datasheets.maximintegrated.com/en/ds/MAX7219-MAX7221.pdf",
    provenance_url="https://www.makerfabs.com/max7219-dot-matrix-4-in-1-display-module.html",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(128.0, 32.0, 13.0),
    color_rgb=(0.05, 0.1, 0.3),
    holes=[(-61.0, -12.5, 3.2), (61.0, -12.5, 3.2), (-61.0, 12.5, 3.2), (61.0, 12.5, 3.2)],
    pins=max7219_4in1_pins,
))

# 9. MAX7219 Dot Matrix 2-in-1 Module (16x8)
max7219_2in1_pins = [
    ("1", "VCC_IN", -29.0, -5.08, "power_in", "L"),
    ("2", "GND_IN", -29.0, -2.54, "power_in", "L"),
    ("3", "DIN", -29.0, 0.0, "input", "L"),
    ("4", "CS_IN", -29.0, 2.54, "input", "L"),
    ("5", "CLK_IN", -29.0, 5.08, "input", "L"),
    ("6", "VCC_OUT", 29.0, -5.08, "power_out", "R"),
    ("7", "GND_OUT", 29.0, -2.54, "power_out", "R"),
    ("8", "DOUT", 29.0, 0.0, "output", "R"),
    ("9", "CS_OUT", 29.0, 2.54, "output", "R"),
    ("10", "CLK_OUT", 29.0, 5.08, "output", "R"),
]
PARTS.append(CuratedPart(
    name="MAX7219-DotMatrix-2in1-16x8",
    reference="DISP",
    keywords="display led matrix dot 16x8 8x8 2in1 2-block max7219 spi daisy-chain",
    description="16x8 Red LED dot matrix display module (2 cascaded 8x8 blocks, 2x MAX7219 drivers), SPI input & daisy-chain output, 64.0 x 32.0 mm",
    datasheet="https://datasheets.maximintegrated.com/en/ds/MAX7219-MAX7221.pdf",
    provenance_url="https://www.makerfabs.com/max7219-dot-matrix-2-in-1-display-module.html",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(64.0, 32.0, 13.0),
    color_rgb=(0.05, 0.1, 0.3),
    holes=[(-29.0, -12.5, 3.2), (29.0, -12.5, 3.2), (-29.0, 12.5, 3.2), (29.0, 12.5, 3.2)],
    pins=max7219_2in1_pins,
))

# 10. WS2812B RGB Matrix 8x8 Panel
ws2812_8x8_pins = [
    ("1", "5V_IN", -27.0, -2.54, "power_in", "L"),
    ("2", "DIN", -27.0, 0.0, "input", "L"),
    ("3", "GND_IN", -27.0, 2.54, "power_in", "L"),
    ("4", "5V_OUT", 27.0, -2.54, "power_out", "R"),
    ("5", "DOUT", 27.0, 0.0, "output", "R"),
    ("6", "GND_OUT", 27.0, 2.54, "power_out", "R"),
]
PARTS.append(CuratedPart(
    name="WS2812B-RGB-Matrix-8x8",
    reference="DISP",
    keywords="display led matrix rgb ws2812b neopixel 8x8 64-led addressable flexible",
    description="8x8 Addressable RGB LED matrix panel, 64 WS2812B / NeoPixel LEDs, cascaded DIN/DOUT 3-pin headers, 65.0 x 65.0 mm",
    datasheet="https://cdn-shop.adafruit.com/datasheets/WS2812B.pdf",
    provenance_url="https://www.adafruit.com/product/1487",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(65.0, 65.0, 3.0),
    color_rgb=(0.1, 0.1, 0.1),
    holes=[(-28.0, -28.0, 2.5), (28.0, -28.0, 2.5), (-28.0, 28.0, 2.5), (28.0, 28.0, 2.5)],
    pins=ws2812_8x8_pins,
))

# 11. WS2812B RGB Matrix 16x16 Panel
ws2812_16x16_pins = [
    ("1", "5V_IN", -75.0, -2.54, "power_in", "L"),
    ("2", "DIN", -75.0, 0.0, "input", "L"),
    ("3", "GND_IN", -75.0, 2.54, "power_in", "L"),
    ("4", "5V_OUT", 75.0, -2.54, "power_out", "R"),
    ("5", "DOUT", 75.0, 0.0, "output", "R"),
    ("6", "GND_OUT", 75.0, 2.54, "power_out", "R"),
    ("7", "5V_PWR", -2.54, 75.0, "power_in", "L"),
    ("8", "GND_PWR", 2.54, 75.0, "power_in", "L"),
]
PARTS.append(CuratedPart(
    name="WS2812B-RGB-Matrix-16x16",
    reference="DISP",
    keywords="display led matrix rgb ws2812b neopixel 16x16 256-led addressable panel",
    description="16x16 Addressable RGB LED matrix panel, 256 WS2812B / NeoPixel LEDs, DIN/DOUT and power injection pads, 160.0 x 160.0 mm",
    datasheet="https://cdn-shop.adafruit.com/datasheets/WS2812B.pdf",
    provenance_url="https://www.adafruit.com/product/2547",
    license="published vendor module; symbol & footprint project-authored",
    dimensions_mm=(160.0, 160.0, 3.0),
    color_rgb=(0.1, 0.1, 0.1),
    holes=[(-75.0, -75.0, 3.0), (75.0, -75.0, 3.0), (-75.0, 75.0, 3.0), (75.0, 75.0, 3.0)],
    pins=ws2812_16x16_pins,
))

# 12. Bi-Color 8x8 LED Matrix (Red/Green 24-Pin DIP)
bicolor_pins = [
    # Bottom row (12 pins, Y = 15.24mm)
    ("1", "ROW1", -13.97, 15.24, "power_in", "L"),
    ("2", "ROW2", -11.43, 15.24, "power_in", "L"),
    ("3", "ROW3", -8.89, 15.24, "power_in", "L"),
    ("4", "ROW4", -6.35, 15.24, "power_in", "L"),
    ("5", "ROW5", -3.81, 15.24, "power_in", "L"),
    ("6", "ROW6", -1.27, 15.24, "power_in", "L"),
    ("7", "ROW7", 1.27, 15.24, "power_in", "L"),
    ("8", "ROW8", 3.81, 15.24, "power_in", "L"),
    ("9", "RED1", 6.35, 15.24, "input", "L"),
    ("10", "RED2", 8.89, 15.24, "input", "L"),
    ("11", "RED3", 11.43, 15.24, "input", "L"),
    ("12", "RED4", 13.97, 15.24, "input", "L"),
    # Top row (12 pins, Y = -15.24mm)
    ("13", "RED5", 13.97, -15.24, "input", "R"),
    ("14", "RED6", 11.43, -15.24, "input", "R"),
    ("15", "RED7", 8.89, -15.24, "input", "R"),
    ("16", "RED8", 6.35, -15.24, "input", "R"),
    ("17", "GRN1", 3.81, -15.24, "input", "R"),
    ("18", "GRN2", 1.27, -15.24, "input", "R"),
    ("19", "GRN3", -1.27, -15.24, "input", "R"),
    ("20", "GRN4", -3.81, -15.24, "input", "R"),
    ("21", "GRN5", -6.35, -15.24, "input", "R"),
    ("22", "GRN6", -8.89, -15.24, "input", "R"),
    ("23", "GRN7", -11.43, -15.24, "input", "R"),
    ("24", "GRN8", -13.97, -15.24, "input", "R"),
]
PARTS.append(CuratedPart(
    name="LED-Matrix-8x8-BiColor",
    reference="DISP",
    keywords="display led matrix dot 8x8 bicolor dual-color red-green 24-pin dip-24",
    description="8x8 Dual-color (Red/Green/Yellow) LED dot matrix display block, 24-pin DIP standard pinout, 38.0 x 38.0 mm",
    datasheet="https://cdn-shop.adafruit.com/datasheets/BL-M12A881XX.pdf",
    provenance_url="https://www.adafruit.com/product/902",
    license="published vendor standard component; symbol & footprint project-authored",
    dimensions_mm=(38.0, 38.0, 8.5),
    color_rgb=(0.1, 0.1, 0.1),
    pins=bicolor_pins,
))

# 13. HUB75 RGB Matrix Panel 64x32
hub75_pins = [
    # 16-pin 2x8 IDC header at left
    ("1", "R1", -63.81, -1.27, "input", "L"),
    ("2", "G1", -63.81, 1.27, "input", "L"),
    ("3", "B1", -61.27, -1.27, "input", "L"),
    ("4", "GND_1", -61.27, 1.27, "power_in", "L"),
    ("5", "R2", -58.73, -1.27, "input", "L"),
    ("6", "G2", -58.73, 1.27, "input", "L"),
    ("7", "B2", -56.19, -1.27, "input", "L"),
    ("8", "GND_2", -56.19, 1.27, "power_in", "L"),
    ("9", "A", -53.65, -1.27, "input", "L"),
    ("10", "B", -53.65, 1.27, "input", "L"),
    ("11", "C", -51.11, -1.27, "input", "L"),
    ("12", "D", -51.11, 1.27, "input", "L"),
    ("13", "CLK", -48.57, -1.27, "input", "L"),
    ("14", "LAT", -48.57, 1.27, "input", "L"),
    ("15", "OE", -46.03, -1.27, "input", "L"),
    ("16", "GND_3", -46.03, 1.27, "power_in", "L"),
    # Power terminal block at right
    ("17", "VCC_1", 56.19, -3.81, "power_in", "R"),
    ("18", "VCC_2", 56.19, -1.27, "power_in", "R"),
    ("19", "GND_A", 56.19, 1.27, "power_in", "R"),
    ("20", "GND_B", 56.19, 3.81, "power_in", "R"),
]
PARTS.append(CuratedPart(
    name="HUB75-RGB-Matrix-64x32",
    reference="DISP",
    keywords="display led matrix rgb hub75 64x32 p3 p4 p5 panel billboard billboard-display",
    description="HUB75 RGB LED matrix panel 64x32 pixels, P3/P4/P5 standard 16-pin IDC control header and 4-pin power terminal, 192.0 x 96.0 mm",
    datasheet="https://cdn-learn.adafruit.com/downloads/pdf/32x16-32x32-rgb-led-matrix.pdf",
    provenance_url="https://www.adafruit.com/product/2279",
    license="published vendor standard component; symbol & footprint project-authored",
    dimensions_mm=(192.0, 96.0, 15.0),
    color_rgb=(0.05, 0.05, 0.05),
    holes=[(-90.0, -42.0, 3.2), (90.0, -42.0, 3.2), (-90.0, 42.0, 3.2), (90.0, 42.0, 3.2)],
    pins=hub75_pins,
))

def build_all() -> None:
    SYMBOL_DIR.mkdir(parents=True, exist_ok=True)
    FOOTPRINT_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    provenance_path = PROVENANCE
    prov = json.loads(provenance_path.read_text(encoding="utf-8")) if provenance_path.exists() else {"schema": 1, "sources": [], "generated_sha256": {}}
    sources_dict = {s["part"]: s for s in prov.get("sources", [])}
    hashes_dict = prov.setdefault("generated_sha256", {})

    for p in PARTS:
        sym_content = generate_symbol(p)
        fp_content = generate_footprint(p)
        wrl_content = _wrl_box(*p.dimensions_mm, p.color_rgb)

        sym_file = SYMBOL_DIR / f"{p.name}.kicad_sym"
        fp_file = FOOTPRINT_DIR / f"{p.name}_Module.kicad_mod"
        wrl_file = MODEL_DIR / f"{p.name}.wrl"

        sym_file.write_text(sym_content, encoding="utf-8")
        fp_file.write_text(fp_content, encoding="utf-8")
        wrl_file.write_text(wrl_content, encoding="utf-8")

        sources_dict[p.name] = {
            "part": p.name,
            "url": p.provenance_url,
            "license": p.license,
        }

        for path in (sym_file, fp_file, wrl_file):
            rel = str(path.relative_to(ROOT))
            hashes_dict[rel] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

        print(f"Generated: {p.name:<32} ({len(p.pins)} pins, {p.dimensions_mm[0]}x{p.dimensions_mm[1]}mm)")

    prov["sources"] = [sources_dict[k] for k in sorted(sources_dict)]
    prov["generated_sha256"] = dict(sorted(hashes_dict.items()))
    provenance_path.write_text(json.dumps(prov, indent=2) + "\n", encoding="utf-8")
    print(f"\nAll {len(PARTS)} curated parts successfully written and recorded in PROVENANCE.json!")


if __name__ == "__main__":
    build_all()
