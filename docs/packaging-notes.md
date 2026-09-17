# Ghi chú đóng gói (Packaging notes)

## 1. Đóng gói backend Python thành 1 binary độc lập (bắt buộc)

Người dùng thường không có Python cài sẵn. `src-tauri/src/main.rs` khởi động
backend như một **sidecar binary**, nghĩa là backend phải được đóng gói
bằng PyInstaller thành file thực thi độc lập trước khi build app Tauri.

```bash
cd backend
pip install -r requirements.txt pyinstaller
pyinstaller --onefile --name meeting-backend \
  --add-data "app:app" \
  -m uvicorn app.api.server:app --host 127.0.0.1 --port 8756
```

Copy binary ra đúng chỗ Tauri tìm sidecar (tên phải có hậu tố target triple,
xem tài liệu Tauri sidecar):
```
frontend/src-tauri/binaries/meeting-backend-x86_64-pc-windows-msvc.exe
frontend/src-tauri/binaries/meeting-backend-x86_64-apple-darwin
frontend/src-tauri/binaries/meeting-backend-aarch64-apple-darwin
```

## 2. Ollama — ĐÃ CHỌN Phương án 2: bundle làm sidecar thứ hai (quyết định của Thiên)

Người dùng thường không được biết Ollama tồn tại — không có bước "tự cài
Ollama" nào cả, kể cả qua trình duyệt. App tự mang theo và tự khởi động.

Cách làm (đã code trong `frontend/src-tauri/src/main.rs`):
1. Tải binary Ollama gốc cho từng OS đích từ https://ollama.com/download
   (hoặc GitHub release của `ollama/ollama`) — đây là 1 file thực thi độc
   lập (Go binary), không cần cài đặt.
2. Đổi tên theo đúng target triple mà Tauri sidecar yêu cầu, đặt vào
   `frontend/src-tauri/binaries/`:
   ```
   binaries/ollama-x86_64-pc-windows-msvc.exe
   binaries/ollama-x86_64-apple-darwin
   binaries/ollama-aarch64-apple-darwin
   binaries/ollama-x86_64-unknown-linux-gnu
   ```
3. `main.rs` tự spawn sidecar này bằng `ollama serve` khi app mở, với
   `OLLAMA_HOST=127.0.0.1:11434` và `OLLAMA_MODELS` trỏ vào thư mục dữ liệu
   app (`app_data_dir/ollama-models` — thư mục có quyền ghi, khác thư mục
   cài đặt app thường chỉ đọc), và tự tắt khi app đóng — y hệt cách làm với
   `meeting-backend`.
4. Ollama phát hành theo giấy phép MIT — bundle kèm app được phép, chỉ cần
   giữ lại file LICENSE của Ollama trong bản đóng gói (thêm vào `resources`
   trong `tauri.conf.json` khi đóng gói release).

Đánh đổi đã chấp nhận: installer nặng hơn (~vài chục-100MB cho binary
Ollama, tuỳ OS) đổi lấy trải nghiệm không cần bước cài đặt phụ nào — đúng
yêu cầu "người dùng thường, không chạy lệnh" đặt ra từ đầu dự án.

## 3. Model AI (LLM) tải lần đầu mở app — có UI riêng, không phải lỗi âm thầm

Model (vài trăm MB - vài GB) **không đóng gói sẵn trong installer** (sẽ
làm file cài đặt quá nặng, và mỗi máy cần model khác nhau tuỳ cấu hình —
xem `hardware.py`). Thay vào đó:

- Onboarding (`view-onboarding` trong `index.html`, bước 2 sau khi kiểm
  tra cấu hình máy) gọi `GET /api/onboarding/ai-ready` để biết model đề
  xuất cho máy này đã có chưa, rồi mở SSE `GET /api/onboarding/prepare-ai`
  để tải model kèm thanh tiến trình % thật (Ollama tự báo % qua API pull)
  — người dùng thấy "Đang chuẩn bị AI lần đầu...", không thấy chữ "Ollama"
  hay "model" ở đâu cả.
- Chạy đúng 1 lần thật sự (model tải xong nằm trên đĩa, các lần mở app
  sau chỉ mất 1 lệnh gọi API kiểm tra rất nhanh — xem `main.js: init()`).
- Nếu lần trước người dùng đóng app giữa lúc đang tải, lần mở tiếp theo
  sẽ tự phát hiện model chưa xong và tải tiếp, không cần Thiên xử lý gì.

Whisper model (`faster-whisper`) hiện vẫn tự tải về `~/.cache/huggingface`
lúc gọi `WhisperModel(...)` lần đầu, nhẹ hơn nhiều so với LLM (vài chục-
vài trăm MB tuỳ size) — **việc cần làm ở bản tiếp theo**: gộp luôn bước
tải Whisper model vào onboarding thay vì để xảy ra lúc xử lý cuộc họp đầu
tiên, cho nhất quán với cách đã làm với model Ollama ở trên.

## 4. pyannote.audio cần Hugging Face token

Model diarization (`pyannote/speaker-diarization-3.1`) yêu cầu người dùng
chấp nhận điều khoản sử dụng trên huggingface.co và lấy access token miễn
phí. Đây là bước 1 lần, cần hướng dẫn cụ thể trong onboarding (link trực
tiếp tới trang model, giải thích bằng tiếng Việt đơn giản).

Nếu không có token, pipeline **vẫn chạy được** (xem `diarize.py` /
`DiarizeUnavailable`) — chỉ là không có nhãn người nói, transcript vẫn có
giá trị. Đây là quyết định thiết kế có chủ đích.

## 5. Giới hạn đã gặp khi build trong sandbox này

Môi trường phát triển hiện tại (nơi Claude viết code này) chặn truy cập
huggingface.co ở tầng mạng (chỉ cho phép registry gói như PyPI/npm và
GitHub) — nên **không tải được model thật để test transcribe/diarize/
Tauri build end-to-end tại đây**. Đã kiểm chứng được:
- Module `docx_export.py` chạy thật, xuất file đúng định dạng (đã gửi mẫu).
- API server (`FastAPI`) khởi động thật, endpoint `/api/hardware` trả kết
  quả đúng dựa trên cấu hình máy thật của sandbox.
- Module `transcribe.py` gọi đúng, lỗi mạng được bắt và báo bằng tiếng Việt
  rõ ràng thay vì crash — nghĩa là luồng xử lý lỗi hoạt động đúng thiết kế.
- `main.js` không có lỗi cú pháp.

**Việc Thiên cần tự làm trên máy thật** (có mạng đầy đủ + cài được Rust/
Tauri prerequisites): `pip install -r requirements.txt` rồi chạy thử
`uvicorn app.api.server:app --port 8756`, thử upload 1 file audio thật qua
Swagger UI (`/docs`) để xác nhận toàn bộ pipeline transcribe→diarize→
summarize chạy đúng trước khi build bản Tauri release.
