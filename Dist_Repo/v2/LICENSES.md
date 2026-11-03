# Upstream licences

Every part distributed here is derived from one of the sources below.
Each `part.json` carries its own `source.license` and `source.commit`;
this file is the summary.

| Source | Licence | Upstream | Commit | Upstream notice |
| ------ | ------- | -------- | ------ | --------------- |
| wireframe-curated-maker | mixed per PROVENANCE.json | https://github.com/CaSauCoin/WireFrameEDA | `4b2775ba4ea5526b6093d05baa35e33cb29417b6` | — |
| wireframe-curated-maker-3d | mixed per PROVENANCE.json | https://github.com/CaSauCoin/WireFrameEDA | `4b2775ba4ea5526b6093d05baa35e33cb29417b6` | — |
| kicad-symbols | CC-BY-SA-4.0 WITH KiCad-Libraries-exception | https://gitlab.com/kicad/libraries/kicad-symbols | `b705e03a5b374ec0700469011805bf1fd5102df2` | [kicad-symbols-LICENSE.md](LICENSES/kicad-symbols-LICENSE.md) |
| kicad-footprints | CC-BY-SA-4.0 WITH KiCad-Libraries-exception | https://gitlab.com/kicad/libraries/kicad-footprints | `c2593cf26a475def24d7b2135fc46daf4d96d608` | [kicad-footprints-LICENSE.md](LICENSES/kicad-footprints-LICENSE.md) |
| kicad-packages3D | CC-BY-SA-4.0 WITH KiCad-Libraries-exception | https://gitlab.com/kicad/libraries/kicad-packages3D | `e62ed1fc7862da83f789bd562671b5e4b82afcdf` | [kicad-packages3D-LICENSE.md](LICENSES/kicad-packages3D-LICENSE.md) |
| Alternate-KiCad-Library | CC-BY-SA-4.0 WITH KiCad-Libraries-exception | https://github.com/DawidCislo/Alternate-KiCad-Library | `cf93181d5934eca1b0560f66895f1b06958700f7` | [Alternate-KiCad-Library-README.md](LICENSES/Alternate-KiCad-Library-README.md) |
| digikey-kicad-library | CC-BY-SA-4.0 with KiCad-style exception | https://github.com/Digi-Key/digikey-kicad-library | `d4bd68f42e6ccc474526811a853a03692e170b58` | [digikey-kicad-library-LICENSE.md](LICENSES/digikey-kicad-library-LICENSE.md) |
| SparkFun-KiCad-Libraries | CC-BY-4.0 | https://github.com/sparkfun/SparkFun-KiCad-Libraries | `5741e46fc9824e1e83e5cd353fc43880803dafcb` | [SparkFun-KiCad-Libraries-README.md](LICENSES/SparkFun-KiCad-Libraries-README.md) |
| espressif-kicad-libraries | CC-BY-SA-4.0 WITH KiCad-Libraries-exception | https://github.com/espressif/kicad-libraries | `dd76561812ab300351234ba6e0ec1295641796f0` | [espressif-kicad-libraries-LICENSE.md](LICENSES/espressif-kicad-libraries-LICENSE.md) |
| JLCPCB-Kicad-Library | MIT | https://github.com/CDFER/JLCPCB-Kicad-Library | `e37fb96f4a4b54013293b80963efb1208d573d43` | [JLCPCB-Kicad-Library-LICENSE](LICENSES/JLCPCB-Kicad-Library-LICENSE) |
| Seeed-OPL-Kicad-Library | CC-BY-SA-4.0 | https://github.com/Seeed-Studio/OPL_Kicad_Library | `b0035c51eb0348bb3e165fdb2f2765fa3d1d17bd` | [Seeed-OPL-Kicad-Library-LICENSE](LICENSES/Seeed-OPL-Kicad-Library-LICENSE) |

## KiCad libraries

The KiCad symbol, footprint and 3D model libraries are licensed
CC-BY-SA-4.0 with an exception permitting use in designs without the
design itself becoming a derivative work. Redistribution of the library
content, as here, requires attribution — which this file and the
per-part `source` block provide.

## WireFrame AC generic packages

KiCad-derived generic protection symbols and unmodified footprints; CC-BY-SA-4.0 WITH KiCad-Libraries-exception. See `sources/ac-packages/PROVENANCE.json` for upstream commits and hashes. No electrical rating or mains certification is implied.

## WireFrame interface connector packages

Unmodified KiCad footprints and project-authored numbered contact symbols. CC-BY-SA-4.0 WITH KiCad-Libraries-exception; see sources/interface-packages/PROVENANCE.json. No protocol or cable compatibility is inferred.

## WireFrame USB connector packages

KiCad `Connector` USB symbols bound to unmodified KiCad `Connector_USB` footprints by identical pin/pad designators; 3D models from kicad-packages3D where the footprint declares one. CC-BY-SA-4.0 WITH KiCad-Libraries-exception; see sources/usb-packages/PROVENANCE.json.

## WireFrame card socket packages

KiCad `Connector` microSD, SD and SIM symbols bound to unmodified KiCad `Connector_Card` footprints by identical pin/pad designators; 3D models from kicad-packages3D where the footprint declares one. CC-BY-SA-4.0 WITH KiCad-Libraries-exception; see sources/card-packages/PROVENANCE.json.

## WireFrame KiCad families

KiCad mechanical, switch, audio, power-entry, battery, buzzer and wire-pad symbols bound to unmodified KiCad footprints by identical pin/pad designators; 3D from kicad-packages3D where the footprint declares one. CC-BY-SA-4.0 WITH KiCad-Libraries-exception; see sources/kicad-families/PROVENANCE.json.

## 3D models added by tools/fill_3d_models.py

Each part zip's `part.json` names where its model came from (`model3d.origin`) and what was measured before it was accepted (`model3d.fit`: the share of copper pads the model's feet land on). collections/3d/fill_report.json records every decision.

- `origin: generator` — built by KiCad's own 3D generator (kicad-library-tools, CadQuery) for a model name a KiCad footprint declares and kicad-packages3D does not ship. CC-BY-SA-4.0 WITH KiCad-Libraries-exception, as kicad-packages3D.

## Licence texts

`LICENSES/` holds each upstream's own licence or notice, named after the
source, and the full texts of the Creative Commons licences they use:
`CC-BY-SA-4.0.txt` (KiCad, Digi-Key, Seeed, espressif and the WireFrame
packages derived from KiCad) and `CC-BY-4.0.txt` (SparkFun). JLCPCB's MIT
notice is its own licence file.
