# Vietlott Data Collector

`vietlott-data-collector` là công cụ Python để thu thập, chuẩn hóa và kiểm tra dữ liệu kết quả Vietlott. Snapshot CSV được lưu trên nhánh dữ liệu và phát hành hằng ngày để dùng trong ứng dụng và nghiên cứu.

## Phạm vi

Project hỗ trợ tám sản phẩm: Mega 6/45 (`mega645`), Power 6/55 (`power655`), Lotto 5/35 (`lotto535`), Max 3D (`max3d`), Max 3D Pro (`max3dpro`), Max 4D (`max4d`), Keno (`keno`) và Bingo18 (`bingo18`).

Collector lưu kết quả kỳ quay, giải thưởng, trạng thái xác nhận và thông tin nguồn. Mỗi snapshot giữ cấu trúc CSV, metadata chất lượng và manifest có hash để người dùng kiểm tra phiên bản dữ liệu.

## Cài đặt

Yêu cầu Python 3.11 trở lên.

```powershell
git clone https://github.com/NhanAZ-Data/vietlott-data-collector.git
cd vietlott-data-collector
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e '.[parquet]'
```

Extra `parquet` cài PyArrow để đọc và ghi Parquet. Nếu chỉ dùng CSV, cài package bằng `python -m pip install -e .`.

## Dùng collector

Liệt kê sản phẩm:

```powershell
vietlott-collector products
```

Thu thập các kỳ mới vào thư mục `data/` dưới dạng CSV:

```powershell
vietlott-collector collect `
  --products keno bingo18 `
  --output-dir data `
  --format csv `
  --contact-email you@example.com
```

Tiếp tục thu thập dữ liệu lịch sử cho mọi sản phẩm:

```powershell
vietlott-collector collect --products all --backfill --output-dir data --format csv --contact-email you@example.com
```

Kiểm tra kho dữ liệu:

```powershell
vietlott-collector validate --output-dir data --format csv
```

Thay `csv` bằng `parquet` nếu đã cài extra `parquet`. Hãy thay `you@example.com` bằng địa chỉ liên hệ để collector đưa vào HTTP User-Agent.

## Dùng snapshot đã phát hành

Tải snapshot mới nhất từ [nhánh `datasets`](https://github.com/NhanAZ-Data/vietlott-data-collector/tree/datasets) hoặc chọn ngày trong [danh sách Releases](https://github.com/NhanAZ-Data/vietlott-data-collector/releases). Nhánh dữ liệu thay đổi khi có kỳ mới. Release theo tag `data-YYYY-MM-DD` là snapshot cố định được lưu tại thời điểm chốt ngày. Chuỗi release chính xác hằng ngày bắt đầu từ 2026-06-14.

Để xem lịch sử từ năm 2017, dùng [nhánh snapshot tái dựng](https://github.com/NhanAZ-Data/vietlott-data-collector/tree/reconstructed-datasets) và [chỉ mục snapshot](https://github.com/NhanAZ-Data/vietlott-data-collector/blob/reconstructed-datasets/snapshot-index.json). Tag `reconstructed-YYYY-MM-DD` lọc dữ liệu hiện có theo `draw_date` đến ngày đó. Đây là bản tái dựng hồi cứu, không thể hiện dữ liệu Vietlott hoặc collector đã biết vào ngày trong tag. Các dòng vẫn giữ `fetched_at` và provenance gốc, nên có thể mang thời điểm muộn hơn ngày tái dựng. Kho hiện có không lưu được lịch sử quan sát đầy đủ từ năm 2017.

Có thể clone riêng nhánh dữ liệu:

```powershell
git clone --branch datasets --single-branch --depth 1 https://github.com/NhanAZ-Data/vietlott-data-collector.git vietlott-datasets
```

Trong bản tải về, thư mục `datasets/` có các tệp chính sau:

| Đường dẫn | Nội dung |
| --- | --- |
| `datasets/draws/<product>/YYYY-MM.csv` | Kỳ quay Keno và Bingo18, chia theo tháng |
| `datasets/draws/<product>/all.csv` | Kỳ quay của các sản phẩm còn lại |
| `datasets/prizes/<product>/all.csv` | Dữ liệu giải thưởng |
| `datasets/prize_rules.csv` | Luật giải đã chuẩn hóa |
| `datasets/exclusions.csv` | Ngoại lệ kỳ quay có thông báo nguồn |
| `datasets/metadata/dataset-summary.json` | Phạm vi, số dòng và khoảng ngày |
| `datasets/metadata/quality-report.json` | Kết quả kiểm tra cấu trúc và chất lượng |
| `datasets/metadata/snapshot-manifest.json` | Hash và kích thước từng tệp |

Giữ nguyên `draw_status`, `validation_status` và các trường provenance khi chuyển đổi dữ liệu. Collector không tạo kỳ quay hoặc kết quả từ mã kỳ còn thiếu hay lịch dự kiến.

Ghép snapshot thành kho làm việc:

```powershell
vietlott-repository-data hydrate --source-dir datasets --destination-dir data
```

Sau khi cập nhật dữ liệu, xuất snapshot mới và kiểm tra:

```powershell
vietlott-repository-data publish --source-dir data --destination-dir datasets
vietlott-repository-data validate --source-dir datasets
vietlott-repository-data audit --source-dir datasets
```

## Cập nhật tự động

GitHub Actions chạy collector từ `main`, cập nhật snapshot trên nhánh `datasets`, rồi phát hành snapshot theo ngày vào 00:30 giờ Việt Nam. Keno và Bingo18 được kiểm tra thường xuyên. Mega 6/45, Power 6/55, Lotto 5/35, Max 3D và Max 3D Pro được kiểm tra theo lịch. Max 4D có trong snapshot lịch sử nhưng không thuộc lịch cập nhật tự động.

Mỗi lượt khôi phục kho làm việc từ snapshot, thu thập và đối chiếu dữ liệu, áp dụng ngoại lệ có nguồn, rồi chạy kiểm tra chất lượng. Workflow chỉ cập nhật nhánh `datasets` khi snapshot hợp lệ có thay đổi. Release hằng đêm chỉ được tạo sau khi lượt chốt dữ liệu thành công. Lịch chỉ xác định thời điểm kiểm tra; collector không tạo kỳ quay khi Vietlott chưa công bố dữ liệu.

## Tài liệu

- [Nguồn và quy trình thu thập](docs/THU_THAP_DU_LIEU.md)
- [Từ điển dữ liệu](docs/DATA_DICTIONARY.md)
- [Chất lượng và provenance](docs/CHAT_LUONG_DU_LIEU.md)
- [Tự động cập nhật](docs/TU_DONG_CAP_NHAT.md)
- [Kiến trúc collector](docs/ARCHITECTURE.md)

## Nguồn và giấy phép

Collector ưu tiên kết quả công khai của [Vietlott](https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/). Snapshot lưu thông tin nguồn và trạng thái xác nhận để người dùng tự đánh giá dữ liệu trước khi sử dụng.

Project không liên kết hoặc đại diện cho Vietlott. Mã nguồn được phát hành theo giấy phép MIT. Dữ liệu gốc vẫn tuân theo quyền sở hữu và điều kiện của nguồn tương ứng.
