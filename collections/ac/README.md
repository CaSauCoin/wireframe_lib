# Bộ package AC cho WireFrame

Đã bổ sung **1,155 package**, tăng thư viện từ **8,212 lên 9,367 linh kiện**. Danh mục AC và linh kiện hỗ trợ hiện gom **1,483 gói** từ nguồn local đã có.

## Danh mục

| Nhóm | Bổ sung | Có trong danh mục |
|---|---:|---:|
| Nguồn AC/DC | 209 | 219 |
| Cầu chỉnh lưu | 164 | 214 |
| Bộ lọc EMI / choke / mạng tụ X2–Y2 | 40 | 40 |
| Optocoupler | 179 | 183 |
| SSR / optotriac | 88 | 108 |
| Relay | 139 | 199 |
| Cảm biến dòng | 195 | 255 |
| IC đo điện năng | 1 | 5 |
| Cầu chì / đế cầu chì — package generic | 35 | 35 |
| GDT — package generic | 3 | 3 |
| MOV — package generic | 102 | 102 |
| TRIAC / SCR | 0 | 46 |
| Biến áp nguồn / biến dòng | 0 | 26 |
| Terminal block | 0 | 48 |

TRIAC/SCR, biến áp và terminal block đã có các gói hợp lệ trong index; lần này giữ nguyên các gói đó. Danh mục hỗ trợ bao gồm cả linh kiện dùng cho AC/DC hoặc tín hiệu; không có nghĩa mọi linh kiện đều dùng được trực tiếp với 230 V.

## File và cách dùng

- `catalog.json`: toàn bộ ID theo nhóm, 1.155 gói thêm mới, và 141 ứng viên cần kiểm tra tiếp cùng lý do cụ thể.
- `../../Dist_Repo/v2/parts/<slug>.zip`: từng package gồm `part.json`, symbol, footprint, preview và 3D khi nguồn có sẵn.
- `../../Dist_Repo/v2/shards/`, `lib_index.json`, `lib_search.sqlite`, `clusters/`, `compat/`: đã cập nhật để tìm kiếm và phân nhóm.
- `../../sources/ac-packages/`: 140 symbol/footprint generic có nguồn gốc KiCad, hash nguồn và giấy phép; `reviewed-pairings.json` ghi bằng chứng cho 12 mã MOC.
- `validation.json`: kiểm tra toàn bộ gói mới; `retrieval-regression.json`: đối chiếu truy vấn cũ trước/sau bổ sung.

Tìm theo các mã: `HLK-PM01`, `IRM-05-5`, `GBU8K`, `MOC3021M`, `MOC3063M`, `G5LE-1`, hoặc `Generic_Varistor`, `Generic_Fuse`, `Generic_GDT_3Pin`.

**Phạm vi hiện tại là repository local.** Chưa upload release hay push GitHub; Online Store dùng bản remote sẽ chưa có các thay đổi này. File ZIP và SQLite là release assets, được `.gitignore` loại khỏi git theo cấu trúc hiện có.

## Kiểm chứng

- Toàn bộ 1.155 gói mới: parse symbol/footprint, CRC ZIP, SHA-256, identity, số và tên chân–pad; không có lỗi cấu trúc.
- Kiểm tra toàn bộ preview của các gói mới: không có lỗi/cảnh báo ảnh trống hoặc hỏng; đã xem thêm ảnh tổng hợp của sáu nhóm.
- Giữ nguyên nội dung 8.212 entry đã có. Tổng shard, manifest và SQLite đều là 9.367; SQLite integrity check đạt.
- Tám truy vấn mã linh kiện kiểm thử đều có kết quả; không đưa class `unknown` mới vào index.
- Bộ kiểm tra toàn thư viện vẫn có 39 URL cũ nằm ngoài `parts_base_url` và 5 truy vấn golden ngoài AC chưa đạt (Arduino/Nucleo/Compute Module/U.FL/M.2), cộng một cảnh báo thứ hạng ESP32. Đối chiếu tập entry cũ tái dựng cho thấy bộ truy vấn trước/sau cho cùng lỗi và cảnh báo. Đây không phải báo cáo rằng toàn bộ thư viện đã đủ điều kiện publish.

## Giới hạn và phần còn thiếu

140 package generic chỉ xác định symbol và hình học footprint. Không gán điện áp MOV, dòng/cấp cắt cầu chì, điện áp GDT, hoặc chứng nhận an toàn. Footprint MOC dùng mẫu DIP-6 upstream; đối chiếu datasheet xác nhận kiểu package và pinout, không tuyên bố courtyard riêng của nhà sản xuất đã được thẩm định.

141 ứng viên chưa thêm vì thiếu footprint, pairing suy ra từ bộ lọc chưa được thẩm định, hoặc tập chân–pad khác nhau. Pad dư đôi khi là NC/cơ khí hợp lệ; cần nguồn xác nhận riêng trước khi nhận, không coi mọi trường hợp là lỗi upstream.

Chưa có bộ đầy đủ cho NTC hạn dòng khởi động, tụ an toàn X/Y rời, contactor và aptomat/circuit breaker theo mã hãng. Nhóm EMI hiện có các mạng tụ X2/Y2; chúng không thay thế toàn bộ họ tụ an toàn. “Tất cả” ở đây là phạm vi nguồn và kiểm chứng ghi trong catalog, không phải mọi linh kiện AC trên thị trường.

## Chạy lại

Chạy từ thư mục `WireFrameEDA`, dùng venv có dependency của Tools:

```bash
WireFrame/.venv/bin/python wireframe_lib/tools/add_ac_packages.py --generic
WireFrame/.venv/bin/python wireframe_lib/tools/verify_ac_packages.py
```

Nguồn KiCad mặc định: `~/.wireframe/library_cache/repos`; có thể đổi bằng `--repos`. Không gọi mạng, AI trả phí hoặc publish. Các dòng cũ được giữ nguyên; catalog lưu commit baseline để đối chiếu.

Nguồn đối chiếu MOC: [onsemi MOC301x/MOC302x](https://www.onsemi.com/pdf/datasheet/moc3023m-d.pdf), [onsemi MOC306x/MOC316x](https://www.onsemi.com/pdf/datasheet/moc3163m-d.pdf).
