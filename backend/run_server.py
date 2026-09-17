"""
Điểm vào (entry point) cho PyInstaller — không thể đóng gói kiểu
`pyinstaller ... -m uvicorn app.api.server:app --host ... --port ...` như
lệnh cũ trong docs vì PyInstaller không có kiểu chạy "-m module" giống
`python -m` (flag `-m` của PyInstaller là để chỉ định manifest file trên
Windows, khác hoàn toàn) — PyInstaller cần 1 FILE SCRIPT PYTHON THẬT làm
điểm vào, phân tích import tĩnh từ đó để đóng gói.

Import trực tiếp `app` (literal import, không phải chuỗi "app.api.server:app")
cũng giúp PyInstaller tự dò ra và đóng gói đúng toàn bộ package app/ mà
không cần thêm --add-data nữa (đỡ phải lo dấu phân cách ':' vs ';' khác
nhau giữa Windows và macOS/Linux).
"""
import uvicorn

from app.api.server import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8756)
