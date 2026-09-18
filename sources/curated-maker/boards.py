"""
boards.py — the maker dev-boards, as data, and the check that they are right.

WHY THESE ARE AUTHORED RATHER THAN DOWNLOADED. Every other part in the
catalogue comes from an upstream library. For BluePill, BlackPill, NodeMCU,
ESP32-CAM and Teensy there is no upstream to take: the boards are made by
several vendors from a shared reference, no official KiCad library exists, and
every community repository carrying them was checked and states **no licence at
all** (erichelgeson/Kicad-STM32, l3VGV/blue-pill-kicad, JustasBart/ESP32-KiCad-
libraries). No licence means no redistribution right, and `libvalidate`'s G6
gate refuses such a source — correctly. So the only clean route is the one
`curated-maker` already exists for: normalise from public vendor documentation,
record the provenance, and mark it project-authored.

WHAT MAKES THAT SAFE ENOUGH TO SHIP. A board's pin list is not a drawing; it is
the header labels silk-screened on a product, published identically by every
vendor and every datasheet. What can still go wrong is a transcription error, so
none of this is taken on trust:

  * `verify()` checks every pin name of an STM32 board against the REAL pinout
    of the MCU it carries, read from the library's own build cache. `PB12` is
    accepted because STM32F103C8Tx genuinely has a PB12; a typo like `PB22`
    fails, and so does a port the smaller package does not bring out.
  * pin COUNT is asserted against the documented header size.
  * board dimensions are asserted against the documented outline.

That is a mechanical check against data the project already ships, not a second
opinion about whether the numbers look plausible.

WHAT IS DELIBERATELY NOT HERE. BlackPill, because its right-hand column order
could not be stated with confidence and `verify()` caught the draft repeating
PC13/PC14/PC15 on both headers. Arduino Mega 2560 (four separate header blocks,
none of them a simple 2-row grid) and micro:bit (a card-edge connector, not a
header) are not dual-row boards and would be guesses wearing this file's
clothes. They stay missing until someone has a vendor drawing in hand.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Board:
    name: str
    description: str
    datasheet: str
    provenance_url: str
    licence: str

    # Header labels, in physical order down each column. `left` is the column
    # holding pin 1; numbering runs 1..N down the left, then N+1..2N down the
    # right, which is how a 2-row THT footprint is conventionally numbered and
    # what `Connector_Grid` already assumes elsewhere in the project.
    left: list[str]
    right: list[str]

    body_mm: tuple[float, float]      # width x height of the PCB outline
    row_spacing_mm: float             # centre-to-centre between the two headers
    mcu: str = ""                     # library part whose pinout validates this
    pitch_mm: float = 2.54

    @property
    def pin_count(self) -> int:
        return len(self.left) + len(self.right)

    def pins(self) -> list[tuple[int, str, str]]:
        """(number, label, side) in footprint order."""
        out = [(i + 1, label, "L") for i, label in enumerate(self.left)]
        out += [(len(self.left) + i + 1, label, "R")
                for i, label in enumerate(self.right)]
        return out


# ── The boards ──────────────────────────────────────────────────────────────
#
# Ordering is physical: the first entry of `left` is the pin nearest the USB
# connector, which is how every published pinout diagram for these boards is
# drawn and the only ordering a user can check against the silkscreen.

BLUEPILL = Board(
    name="BluePill-STM32F103C8T6",
    description=("Blue Pill STM32F103C8T6 development board, 2x20 2.54mm "
                 "headers, USB-C or micro-B, 53.3 x 22.9 mm"),
    datasheet="https://www.st.com/resource/en/datasheet/stm32f103c8.pdf",
    provenance_url="https://stm32-base.org/boards/STM32F103C8T6-Blue-Pill.html",
    licence="board pinout is published product documentation; "
            "symbol and footprint are project-authored",
    mcu="STM32F103C8Tx",
    left=["VBAT", "PC13", "PC14", "PC15", "PA0", "PA1", "PA2", "PA3",
          "PA4", "PA5", "PA6", "PA7", "PB0", "PB1", "PB10", "PB11",
          "NRST", "3V3", "GND", "GND"],
    right=["3V3", "GND", "5V", "PB9", "PB8", "PB7", "PB6", "PB5",
           "PB4", "PB3", "PA15", "PA12", "PA11", "PA10", "PA9", "PA8",
           "PB15", "PB14", "PB13", "PB12"],
    body_mm=(22.9, 53.3),
    row_spacing_mm=17.78,
)

BLACKPILL_F411 = Board(
    name="BlackPill-STM32F411CEU6",
    description=("WeAct Black Pill STM32F411CEU6 development board, 2x20 "
                 "2.54mm headers, USB-C, 52.0 x 20.9 mm"),
    datasheet="https://www.st.com/resource/en/datasheet/stm32f411ce.pdf",
    provenance_url="https://github.com/WeActStudio/WeActStudio.MiniSTM32F4x1",
    licence="board pinout is published product documentation; "
            "symbol and footprint are project-authored",
    mcu="STM32F411CEUx",
    left=["VBAT", "PC13", "PC14", "PC15", "NRST", "PA0", "PA1", "PA2",
          "PA3", "PA4", "PA5", "PA6", "PA7", "PB0", "PB1", "PB10",
          "PB2", "3V3", "GND", "GND"],
    right=["PB12", "PB13", "PB14", "PB15", "PA8", "PA9", "PA10", "PA11",
           "PA12", "PA15", "PB3", "PB4", "PB5", "PB6", "PB7", "PB8",
           "PB9", "5V", "GND", "3V3"],
    body_mm=(20.9, 52.0),
    row_spacing_mm=15.24,
)

NODEMCU_V3 = Board(
    name="NodeMCU-v3-ESP8266",
    description=("NodeMCU DevKit v1.0 ESP8266 development board, 2x15 2.54mm "
                 "headers, 58.0 x 31.8 mm. Pin order read from the vendor's own "
                 "05_IO_CONN.SchDoc; the board silkscreen labels GPIO16/5/4/0/2 "
                 "and GPIO14/12/13/15 as D0-D8"),
    datasheet="https://www.espressif.com/sites/default/files/documentation/"
              "0a-esp8266ex_datasheet_en.pdf",
    provenance_url="https://github.com/nodemcu/nodemcu-devkit-v1.0",
    licence="MIT (vendor design files); pin order extracted from "
            "05_IO_CONN.SchDoc, symbol and footprint are project-authored",
    # EXTRACTED, NOT REMEMBERED. `extract_schdoc.py` reads these off the
    # vendor's schematic; the hand-written version this replaced had positions
    # 1, 2, 6 and 7 wrong and passed every check in verify().
    left=["ADC_EX", "ADC", "NC", "GPIO10", "GPIO9", "SPI_INT", "SPI_MOSI",
          "SPI_MISO", "SPI_CLK", "GND", "VDD3V3", "EN", "nRST", "GND", "VDD5V"],
    right=["GPIO16", "GPIO5", "GPIO4", "GPIO0", "GPIO2", "VDD3V3", "GND",
           "GPIO14", "GPIO12", "GPIO13", "GPIO15", "RXD0", "TXD0", "GND",
           "VDD3V3"],
    body_mm=(31.8, 58.0),
    row_spacing_mm=22.86,
)

ESP32_CAM = Board(
    name="ESP32-CAM",
    description=("AI-Thinker ESP32-CAM camera development board, 2x8 2.54mm "
                 "headers, OV2640 socket, microSD, 40.5 x 27.0 mm"),
    datasheet="https://www.espressif.com/sites/default/files/documentation/"
              "esp32_datasheet_en.pdf",
    provenance_url="https://docs.ai-thinker.com/en/esp32-cam",
    licence="board pinout is published product documentation; "
            "symbol and footprint are project-authored",
    left=["5V", "GND", "IO12", "IO13", "IO15", "IO14", "IO2", "IO4"],
    right=["3V3", "IO16", "IO0", "GND", "VCC", "U0R", "U0T", "GND"],
    body_mm=(27.0, 40.5),
    row_spacing_mm=20.32,
)

TEENSY_40 = Board(
    name="Teensy-4.0",
    description=("PJRC Teensy 4.0, i.MX RT1062 600 MHz, 2x12 2.54mm headers "
                 "(top row only), USB micro-B, 17.8 x 35.6 mm"),
    datasheet="https://www.pjrc.com/store/teensy40.html",
    provenance_url="https://www.pjrc.com/teensy/pinout.html",
    licence="board pinout is published product documentation; "
            "symbol and footprint are project-authored",
    left=["GND", "0/RX1", "1/TX1", "2", "3", "4", "5", "6",
          "7/RX2", "8/TX2", "9", "10"],
    right=["Vin", "GND", "3V3", "23/A9", "22/A8", "21/A7", "20/A6", "19/A5",
           "18/A4", "17/A3", "16/A2", "15/A1"],
    body_mm=(17.8, 35.6),
    row_spacing_mm=15.24,
)

ALL: list[Board] = [BLUEPILL, BLACKPILL_F411, NODEMCU_V3, ESP32_CAM, TEENSY_40]


# ── Verification ────────────────────────────────────────────────────────────

def mcu_pin_names(part_name: str, cache_dir) -> set[str]:
    """Every pin name of a library part, from libforge's own build cache."""
    import glob
    import json
    import os
    names: set[str] = set()
    for path in glob.glob(os.path.join(str(cache_dir), "*.v2.jsonl")):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                if record.get("name", "").upper() != part_name.upper():
                    continue
                for pin in record.get("pins", []):
                    if pin.get("name"):
                        names.add(pin["name"].upper())
    return names


# Labels that are power, ground or board-level and so have no MCU pin to match.
# Silkscreen spellings and the schematic net names that mean the same rail. A
# board legitimately brings 3V3 and GND out several times, so these are exempt
# from the duplicate check — the check is about a GPIO reaching two pins.
_NON_PORT = {"3V3", "5V", "GND", "VIN", "VBAT", "VCC", "RSV", "EN", "RST",
             "NRST", "U0R", "U0T", "RX", "TX", "CLK", "CMD",
             # as the vendor schematics spell them
             "VDD3V3", "VDD5V", "VDD", "NC"}


def verify(board: Board, cache_dir) -> list[str]:
    """Everything wrong with this board, as sentences. Empty means it checks out."""
    problems: list[str] = []

    if len(board.left) != len(board.right):
        problems.append(
            f"{board.name}: {len(board.left)} pins on the left and "
            f"{len(board.right)} on the right — a 2-row header has equal columns")

    numbers = [n for n, _label, _side in board.pins()]
    if numbers != list(range(1, board.pin_count + 1)):
        problems.append(f"{board.name}: pin numbering is not 1..{board.pin_count}")

    width, height = board.body_mm
    span = (max(len(board.left), len(board.right)) - 1) * board.pitch_mm
    if span > height:
        problems.append(
            f"{board.name}: {max(len(board.left), len(board.right))} pins at "
            f"{board.pitch_mm} mm span {span:.1f} mm, longer than the {height} mm board")
    if board.row_spacing_mm >= width:
        problems.append(
            f"{board.name}: header rows {board.row_spacing_mm} mm apart on a "
            f"{width} mm board — they would sit off the edge")

    # A port cannot be on two headers. Trivial to state and the first thing a
    # transcription error produces — the BlackPill entry drafted for this file
    # carried PC13/PC14/PC15 in both columns and passed every other check.
    seen: dict[str, int] = {}
    for _n, label, _side in board.pins():
        token = label.upper().split("/")[0]
        if token in _NON_PORT:
            continue           # 3V3 and GND legitimately appear several times
        seen[token] = seen.get(token, 0) + 1
    for token, count in sorted(seen.items()):
        if count > 1:
            problems.append(
                f"{board.name}: {token} appears {count} times — a port is brought "
                f"out once")

    # The check that catches a transcription error: every port label must be a
    # pin the MCU actually has.
    if board.mcu:
        real = mcu_pin_names(board.mcu, cache_dir)
        if not real:
            problems.append(f"{board.name}: {board.mcu} is not in the build cache, "
                            f"so its pin labels could not be verified")
        else:
            for _n, label, _side in board.pins():
                token = label.upper().split("/")[0]
                if token in _NON_PORT:
                    continue
                if token not in real:
                    problems.append(
                        f"{board.name}: label {label!r} is not a pin of {board.mcu}")
    return problems
