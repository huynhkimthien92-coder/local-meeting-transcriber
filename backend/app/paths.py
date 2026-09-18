"""
Thư mục dữ liệu gốc dùng chung cho cả app (job đã lưu, file ghi âm upload,
file .docx xuất ra, settings.json).

QUAN TRỌNG -- lỗi thật đã gặp: các module trước đây tự tính đường dẫn kiểu
`Path(__file__).resolve().parents[2] / "storage"`, tức là DỰA VÀO VỊ TRÍ
FILE CODE đang nằm. Lúc chạy `python run_server.py` trực tiếp lúc dev thì
không sao (file code nằm cố định trong repo). Nhưng khi PyInstaller đóng
gói kiểu --onefile, backend thực chất được giải nén ra một thư mục TẠM
THỜI MỚI (vd C:\\...\\Temp\\_MEIxxxxxx) mỗi lần app khởi động, và thư mục đó
bị xoá khi app đóng -> nếu storage nằm trong đó, mọi thứ (biên bản đã lưu,
cài đặt, file ghi âm) biến mất hoàn toàn sau khi tắt app, kể cả tính năng
"resume nếu app bị đóng giữa chừng" mà orchestrator.py đã thiết kế riêng
cũng vô nghĩa.

Cách sửa: main.rs (Tauri) truyền vào biến môi trường MEETING_DATA_DIR trỏ
tới thư mục dữ liệu CÓ QUYỀN GHI và ỔN ĐỊNH của app (app_data_dir, giống
cách đã làm với thư mục lưu model Ollama) khi khởi động sidecar backend.
Nếu biến này không có (vd lúc dev chạy `python run_server.py` trực tiếp,
không qua Tauri), tự động rơi về đường dẫn cũ để không phá vỡ cách chạy
dev hiện tại.
"""
from __future__ import annotations

import os
from pathlib import Path

_env_dir = os.environ.get("MEETING_DATA_DIR")

if _env_dir:
    DATA_DIR = Path(_env_dir)
else:
    # Fallback lúc dev: backend/storage (thư mục gốc của backend, không phải
    # thư mục tạm PyInstaller) -- giữ nguyên hành vi cũ khi chạy trực tiếp.
    DATA_DIR = Path(__file__).resolve().parents[1] / "storage"

DATA_DIR.mkdir(parents=True, exist_ok=True)
