"""
extract_schdoc.py — read a header pinout out of a vendor's Altium schematic.

WHY THIS EXISTS. The first NodeMCU entry in `boards.py` was written from
knowledge of the published pinout and checked by `boards.verify()`. It passed
every check and **four of its thirty pins were in the wrong place** — positions
1, 2, 6 and 7. `verify()` could not see it: every label was a real signal, none
repeated, the count and dimensions were right. Only the ORDER was wrong, and
order is the one thing that check cannot reach.

What found it was the vendor's own file. `nodemcu/nodemcu-devkit-v1.0` is MIT
and ships the Altium schematic; `05_IO_CONN.SchDoc` is the sheet that draws the
two headers. So the pinout is not remembered here, it is read.

HOW A SchDoc YIELDS A PINOUT. The file is an OLE compound document whose
`FileHeader` stream is a run of `|RECORD=n|KEY=VALUE|…` records:

  * `RECORD=2`  a component pin: `DESIGNATOR`, `LOCATION.X/Y`, and
    `OWNERINDEX` — which component it belongs to. A two-header sheet gives two
    owners with fifteen pins each.
  * `RECORD=25` / `RECORD=27`  a net label: `TEXT` and `LOCATION.X/Y`.

A pin carries the signal of the net label drawn at the same height on its side
of the connector. A pin with no label at its height is a genuine no-connect —
NodeMCU's left header has one, which is why the sheet holds 29 labels for 30
pins and why the hand-written entry invented a second `RSV` to fill it.

DELIBERATELY NOT A GENERAL ALTIUM READER. `Tools/parsers/altium_parser/` reads
`.SchLib` and `.PcbLib`, which are libraries; this reads the one thing a
schematic sheet can tell us that a library cannot — which signal reaches which
header pin. It is a few hundred bytes of record scraping, not a format
implementation, and it says so rather than pretending to be one.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

_PIN = re.compile(r"\|DESIGNATOR=(\w+)")
_OWNER = re.compile(r"\|OWNERINDEX=(\d+)")
_TEXT = re.compile(r"\|TEXT=([^|]*)")
_XY = re.compile(r"\|LOCATION\.X=(-?\d+)\|LOCATION\.Y=(-?\d+)")

# How far apart, in Altium's schematic units, a pin and its net label may sit
# vertically and still be the same wire. The sheets seen put them on exactly the
# same Y; a few units of slack costs nothing and survives a redrawn wire.
_ROW_TOLERANCE = 5

# A pin with no net label is a no-connect. Named rather than left blank so a
# generated symbol says so, instead of showing an unnamed pin a user has to
# guess about.
NO_CONNECT = "NC"


def _records(path: Path) -> list[str]:
    import olefile
    if not olefile.isOleFile(str(path)):
        raise ValueError(f"{path.name} is not an OLE compound file")
    with olefile.OleFileIO(str(path)) as ole:
        raw = ole.openstream("FileHeader").read().decode("latin-1")
    return raw.split("|RECORD=")


def headers(path: Path) -> dict[str, list[tuple[int, str]]]:
    """Every multi-pin component on the sheet, as {owner: [(pin, signal)…]}.

    Keyed by Altium's owner index rather than by a name, because the connector
    symbols on these sheets are generic parts — their pins are called `PIN1`,
    and the sheet's designator is not in this stream. The caller picks the
    header it wants by size and by what the signals say.
    """
    records = _records(path)

    pins: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    for record in records:
        if not record.startswith("2|"):
            continue
        designator, owner, xy = _PIN.search(record), _OWNER.search(record), _XY.search(record)
        if not (designator and owner and xy):
            continue
        if not designator.group(1).isdigit():
            continue
        pins[owner.group(1)].append(
            (int(designator.group(1)), int(xy.group(1)), int(xy.group(2))))

    labels: list[tuple[str, int, int]] = []
    for record in records:
        if not record.startswith(("25|", "27|")):
            continue
        text, xy = _TEXT.search(record), _XY.search(record)
        if text and xy and text.group(1):
            labels.append((text.group(1), int(xy.group(1)), int(xy.group(2))))

    # Labels are drawn in columns, one per header, outboard of its pins. Two
    # headers at the same height on one sheet is the normal case, so a pin must
    # take the label from ITS column — reading the nearer of two columns per pin
    # would let a short wire on one header steal the other's signal.
    label_columns = sorted({lx for _text, lx, _ly in labels})

    out: dict[str, list[tuple[int, str]]] = {}
    for owner, owned in pins.items():
        pin_x = sum(x for _pin, x, _y in owned) / len(owned)
        if not label_columns:
            out[owner] = [(n, NO_CONNECT) for n, _x, _y in sorted(owned)]
            continue
        column = min(label_columns, key=lambda lx: abs(lx - pin_x))
        resolved = []
        for number, _px, py in sorted(owned):
            hit = [text for text, lx, ly in labels
                   if lx == column and abs(ly - py) <= _ROW_TOLERANCE]
            resolved.append((number, hit[0] if hit else NO_CONNECT))
        out[owner] = resolved
    return out


def pin_list(path: Path, expected: int) -> list[list[str]]:
    """The signals of every `expected`-pin header on the sheet, in pin order.

    Ordered by Altium's owner index so two runs give the same two columns in the
    same order — a pinout that swapped sides between builds would be worse than
    no pinout.
    """
    out: list[list[str]] = []
    for _owner, signals in sorted(headers(path).items(), key=lambda kv: int(kv[0])):
        if len(signals) == expected:
            out.append([signal for _number, signal in sorted(signals)])
    return out


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print(f"usage: {Path(__file__).name} FILE.SchDoc [PINS_PER_HEADER]")
        raise SystemExit(2)
    sheet = Path(sys.argv[1])
    want = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    for owner, signals in sorted(headers(sheet).items()):
        if want and len(signals) != want:
            continue
        print(f"owner {owner}: {len(signals)} pins")
        for number, signal in sorted(signals):
            print(f"  {number:>3}  {signal}")
