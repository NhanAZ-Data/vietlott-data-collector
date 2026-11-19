# Tự động cập nhật dữ liệu

Workflow lịch chỉ là lịch thăm dò; collector không tạo kỳ chỉ vì đồng hồ đến giờ.

## Lịch hiện tại

- `update-fast.yml`: Keno và Bingo18 trong các khung phát hành dày.
- `update-scheduled.yml`: Mega 6/45, Power 6/55, Lotto 5/35, Max 3D và Max 3D Pro sau các mốc công bố.
- Max 4D được giữ như dữ liệu lịch sử và chỉ thu thập khi chạy thủ công.

Các mốc lịch có thể thay đổi; nguồn chính thức có giá trị cao hơn tài liệu này.

## Một lần chạy

1. Checkout `main` để chạy collector và checkout nhánh `datasets` vào thư mục riêng.
2. `hydrate` snapshot từ nhánh `datasets` vào kho SQLite.
3. Chạy `vietlott-auto-update` cho nhóm sản phẩm.
4. Nếu nguồn chính thức lỗi, thử nguồn đối chiếu được khai báo.
5. `publish`, đồng bộ với nhánh `datasets`, chạy `validate`, `audit` và kiểm tra hồi quy chất lượng.
6. Commit vào nhánh `datasets` nếu và chỉ nếu snapshot hợp lệ thay đổi.
7. Vào 00:30 giờ Việt Nam, chạy lượt chốt cuối. Nếu lượt chốt thành công, gắn tag `data-YYYY-MM-DD` và tạo GitHub Release từ đúng snapshot đã kiểm tra.

Báo cáo JSON của lượt chạy được lưu trong thư mục tạm của Actions. Dữ liệu lâu dài nằm trên nhánh `datasets` và trong các release đã phát hành.

## Chịu lỗi

- Kết quả trễ: lượt sau đọc lại vùng gần nhất.
- Nhiều kỳ xuất hiện: collector tiếp tục qua các trang cho tới vùng đã biết.
- Kỳ hủy hoặc sản phẩm dừng: không tạo bản ghi giả.
- Mạng lỗi: retry, backoff, jitter và `Retry-After`.
- HTML thay đổi: parser dừng với lỗi để sửa có kiểm soát.
- Một sản phẩm lỗi: phần hợp lệ của sản phẩm khác vẫn được giữ, sau đó workflow báo đỏ.
- Lượt chốt trong ngày lỗi: giữ phần dữ liệu hợp lệ trên nhánh `datasets`, nhưng không phát hành snapshot ngày đó.
- Tag release đã tồn tại: không ghi đè. Bản hiệu chỉnh dùng tag mới có hậu tố `-r2`.

Không có workflow build/deploy website hoặc sinh artifact dự đoán/phân tích.
