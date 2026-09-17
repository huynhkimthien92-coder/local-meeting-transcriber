# Local Meeting Transcriber

Ứng dụng desktop chạy local: nhận file ghi âm cuộc họp → nhận diện lời nói
(Whisper) → nhận diện người nói (pyannote) → sinh biên bản (Ollama, LLM
local) → xuất DOCX. Không cần chạy lệnh khi dùng — đóng gói thành app cài
đặt được, theo đúng blueprint đã thống nhất (`docs/blueprint.md` nếu bạn
copy file gốc vào đây).

## Cấu trúc dự án

```
backend/              Python — pipeline AI + API server local
  app/pipeline/        transcribe, diarize, summarize, orchestrator, hardware
  app/api/server.py     FastAPI — cầu nối giữa frontend và pipeline
  app/export/           xuất DOCX
  tests/                test có dữ liệu thật, không phải TODO rỗng
frontend/              Tauri — vỏ desktop + giao diện web (vanilla JS)
  src/                  index.html, main.js, style.css — 4 màn hình chính
  src-tauri/            cấu hình Tauri, khởi động backend làm sidecar
docs/
  packaging-notes.md    cách đóng gói thành installer thật, giới hạn đã gặp khi build ở đây
```

## Chạy thử backend (đã kiểm chứng chạy được trong sandbox)

```bash
cd backend
pip install -r requirements.txt
uvicorn app.api.server:app --port 8756
# Mở http://127.0.0.1:8756/docs để thử API bằng Swagger UI
```

Đã tự kiểm tra trong quá trình build:
- `GET /api/hardware` — chạy thật, trả đúng RAM/CPU máy hiện tại.
- `GET/POST /api/settings*` — chạy thật, nhận diện người nói mặc định TẮT,
  bật/lưu token/che token khi trả về đều đúng.
- Export DOCX (`tests/test_docx_export.py`) — chạy thật, đã gửi file mẫu.
- `transcribe.py` — gọi đúng luồng, nhưng **chưa tải được model Whisper
  thật** vì môi trường build này chặn truy cập huggingface.co. Chạy
  `python3 -m tests.test_transcribe_real` trên máy Thiên (có mạng đầy đủ)
  để xác nhận bước này trước khi đi tiếp.

## Nhận diện người nói (diarization) — mặc định TẮT

Quyết định UX quan trọng: setup Hugging Face token là rào cản với người
dùng thường, nên tính năng phân biệt "ai nói câu nào" **mặc định tắt**.
App chạy đầy đủ (transcribe + tóm tắt) mà không cần bước này.

Ai muốn bật thì vào màn hình **Cài đặt** trong app — có sẵn luồng hướng
dẫn 3 bước (tạo tài khoản HF → đồng ý điều khoản model → lấy token dán
vào), kèm nút "Kiểm tra" xác nhận token dùng được ngay, không phải đợi
đến lúc xử lý cuộc họp mới biết token sai.

## Chạy thử frontend (dev mode, cần Rust + Tauri CLI trên máy)

```bash
cd frontend
npm install
npm run dev   # cần cargo/Tauri prerequisites: xem https://tauri.app/start/prerequisites/
```

Frontend gọi API ở `http://127.0.0.1:8756` (xem `API_BASE` trong `src/main.js`)
— chạy song song với bước "Chạy thử backend" ở trên.

## Việc cần làm tiếp theo (chưa làm trong lượt này)

1. **Cài Ollama trên máy dev thật** và test `summarize.py` với model thật
   (`ollama pull llama3.2:3b` rồi `ollama serve`).
2. **Lấy Hugging Face token free** qua luồng hướng dẫn trong màn hình Cài đặt
   (hoặc thủ công), test `diarize.py` với audio nhiều người nói thật.
3. **Đóng gói sidecar** theo `docs/packaging-notes.md` mục 1, rồi `npm run build`
   để ra installer thật (.exe/.dmg) — cần làm trên máy có đủ Rust +
   webview prerequisites cho từng OS đích.
4. **Thêm bước kiểm tra/cài Ollama vào onboarding wizard** (hiện
   `view-onboarding` mới kiểm tra RAM/CPU/GPU, chưa kiểm tra Ollama đã
   cài/chạy chưa — xem mục 2 trong packaging-notes.md).
5. QA với file ghi âm thật 1-2 tiếng, nhiều người nói, theo đúng Giai đoạn 5
   của blueprint.

## Icon app

`frontend/src-tauri/icons/` hiện còn trống — cần thêm icon thật (32x32,
128x128, .icns, .ico) trước khi build release; Tauri có lệnh
`tauri icon <path-to-1024px-png>` để tự sinh đủ kích cỡ từ 1 file gốc.
