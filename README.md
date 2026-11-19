# Snapshot Vietlott tái dựng hồi cứu

Nhánh này chứa các snapshot hằng ngày được tái dựng hồi cứu, không phải bản sao lịch sử
cho biết dữ liệu đã được biết vào từng ngày. Tag `reconstructed-YYYY-MM-DD` gồm các dòng
hiện có với `draw_date` không muộn hơn ngày trong tag.

Ngày trong tag là mốc lọc theo ngày quay. Bản ghi giữ nguyên `fetched_at` và provenance
hiện có. Nguồn này không cho biết thời điểm dữ liệu được công bố lần đầu, các sửa đổi về
sau hoặc lúc collector biết đến bản ghi.

[`snapshot-index.json`](https://github.com/NhanAZ-Data/vietlott-data-collector/blob/reconstructed-datasets/snapshot-index.json)
liệt kê các tag hằng ngày và liên kết tải archive. Snapshot hằng ngày được ghi nhận tại
thời điểm phát hành riêng bằng tag `data-YYYY-MM-DD`, bắt đầu từ 2026-06-14.
