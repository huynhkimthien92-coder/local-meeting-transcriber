"""
API server local cho app desktop.

Đây là "cầu nối" giữa giao diện Tauri (frontend/) và pipeline Python
(app/pipeline/). Chạy trên 127.0.0.1 (không expose ra mạng ngoài — dữ
liệu cuộc họp không rời khỏi máy, đúng cam kết "local" của sản phẩm).

Chạy thử: uvicorn app.api.server:app --port 8756
"""
from __future__ import annotations

import asyncio
import json
import queue
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from ..pipeline.hardware import detect_hardware, recommend_models
from ..pipeline.models import MeetingJob, ProgressEvent
from ..pipeline.orchestrator import MeetingPipeline, JobStore
from ..pipeline.transcribe import estimate_processing_time
from ..pipeline import ollama_manager
from ..export.docx_export import export_to_docx
from ..settings import AppSettings, load_settings, save_settings
from ..paths import DATA_DIR

app = FastAPI(title="Local Meeting Transcriber API")

# Tauri frontend chạy trên origin riêng (tauri://localhost hoặc http://localhost:xxxx
# tuỳ platform) -> cần CORS mở cho localhost. Đây là app desktop cá nhân chạy local,
# không phải server công khai, nên mở CORS rộng cho localhost là chấp nhận được.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# QUAN TRỌNG: dùng DATA_DIR dùng chung (xem app/paths.py) -- KHÔNG tự tính
# theo Path(__file__), vì sau khi đóng gói PyInstaller --onefile, đường dẫn
# đó chỉ là thư mục tạm bị xoá mỗi lần tắt app (lỗi thật đã gặp: mất file
# ghi âm đã upload sau khi tắt/mở lại app).
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

store = JobStore()
pipeline = MeetingPipeline(store=store)

# Mỗi job có 1 queue riêng để phát progress event qua SSE cho đúng client đang theo dõi.
_progress_queues: dict[str, "queue.Queue[ProgressEvent]"] = {}


@app.get("/api/hardware")
def get_hardware():
    """Gọi ở màn hình onboarding: kiểm tra cấu hình máy, đề xuất model."""
    hw = detect_hardware()
    rec = recommend_models(hw)
    return {"hardware": hw.to_dict(), "recommendation": rec.to_dict()}


@app.get("/api/onboarding/ai-ready")
def ai_ready():
    """Gọi ở onboarding TRƯỚC khi cho vào màn hình chính: AI engine (Ollama,
    chạy ngầm như sidecar — xem frontend/src-tauri/src/main.rs) đã sẵn sàng
    và model tóm tắt đề xuất cho máy này đã tải chưa. Người dùng không cần
    biết "Ollama" là gì — chỉ thấy "đang chuẩn bị AI"."""
    rec = recommend_models(detect_hardware())
    settings = load_settings()
    model = settings.ollama_model_override or rec.ollama_model
    return {
        "engine_running": ollama_manager.is_running(),
        "model": model,
        "model_ready": ollama_manager.has_model(model),
    }


@app.get("/api/onboarding/prepare-ai")
async def prepare_ai():
    """SSE — tải model AI cần thiết cho máy này (nếu chưa có), stream %
    tiến trình cho onboarding hiển thị thanh loading. Đây là bước THAY THẾ
    cho việc bắt người dùng tự gõ `ollama pull` — chạy 1 lần duy nhất khi
    mở app lần đầu (hoặc khi đổi model trong Cài đặt)."""
    rec = recommend_models(detect_hardware())
    settings = load_settings()
    model = settings.ollama_model_override or rec.ollama_model

    def event_stream():
        try:
            for progress in ollama_manager.ensure_model_stream(model):
                yield f"data: {json.dumps(progress, ensure_ascii=False)}\n\n"
        except ollama_manager.OllamaUnreachable as e:
            yield f"data: {json.dumps({'percent': 0, 'message': str(e), 'done': True, 'error': True}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/settings")
def get_settings():
    """Cho màn hình Cài đặt. hf_token trả về dạng che bớt (vd: 'hf_A…9x2Z'),
    không bao giờ trả nguyên token ra ngoài sau khi đã lưu."""
    return load_settings().to_dict(mask_token=True)


@app.post("/api/settings/diarization")
def set_diarization_enabled(enabled: bool = Form(...)):
    """Bật/tắt nhận diện người nói — mặc định TẮT (xem app/settings.py).
    Đây là toggle độc lập với việc đã có token hay chưa: người dùng có thể
    bật trước rồi mới đi lấy token theo hướng dẫn."""
    settings = load_settings()
    settings.diarization_enabled = enabled
    save_settings(settings)
    return settings.to_dict()


@app.post("/api/settings/ollama-model")
def set_ollama_model_override(model: str = Form("")):
    """Cho người dùng nâng cao tự chọn model tóm tắt lớn hơn (chậm hơn,
    biên bản chi tiết hơn) thay vì model app tự đề xuất theo máy. Gửi
    chuỗi rỗng để xoá ghi đè, quay về dùng đề xuất tự động (mặc định ưu
    tiên tốc độ, xem pipeline/hardware.py)."""
    settings = load_settings()
    settings.ollama_model_override = model.strip() or None
    save_settings(settings)
    return settings.to_dict()


@app.post("/api/settings/hf-token")
def set_hf_token(hf_token: str = Form(...)):
    """Lưu token sau khi người dùng dán vào ở bước cuối luồng hướng dẫn."""
    settings = load_settings()
    settings.hf_token = hf_token.strip()
    save_settings(settings)
    return settings.to_dict()


@app.post("/api/settings/hf-token/test")
def test_hf_token():
    """Kiểm tra token đang lưu có dùng được không — gọi ngay sau khi dán
    token, để người dùng biết ngay có làm đúng không thay vì phải chờ đến
    lúc xử lý cuộc họp mới phát hiện ra lỗi."""
    settings = load_settings()
    if not settings.hf_token:
        return {"ok": False, "message": "Chưa nhập token."}
    try:
        import requests
        res = requests.get(
            "https://huggingface.co/api/whoami-v2",
            headers={"Authorization": f"Bearer {settings.hf_token}"},
            timeout=8,
        )
        if res.status_code == 200:
            return {"ok": True, "message": "Token hợp lệ — có thể dùng nhận diện người nói."}
        return {"ok": False, "message": "Token không hợp lệ hoặc đã hết hạn. Thử lấy token mới."}
    except requests.exceptions.RequestException as e:
        return {"ok": False, "message": f"Không kết nối được để kiểm tra token: {e}"}


@app.post("/api/jobs")
async def create_job(
    file: UploadFile = File(...),
    title: str = Form("Cuộc họp chưa đặt tên"),
):
    """Nhận file audio kéo-thả từ UI, tạo job, bắt đầu xử lý nền ngay,
    trả về job_id để UI mở kết nối SSE theo dõi tiến trình.

    Không nhận hf_token qua request nữa — đọc từ Cài đặt đã lưu (xem
    /api/settings/*). Người dùng thường không cần biết khái niệm "token"
    tồn tại nếu họ không chủ động bật nhận diện người nói."""
    job_id = str(uuid.uuid4())
    dest_path = UPLOAD_DIR / f"{job_id}_{file.filename}"
    with dest_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    hw = detect_hardware()
    rec = recommend_models(hw)
    settings = load_settings()
    # Người dùng nâng cao có thể tự đổi model tóm tắt (chậm hơn, chất lượng
    # cao hơn) trong Cài đặt — nếu không đổi gì thì dùng đúng đề xuất theo
    # máy (mặc định ưu tiên tốc độ khi không có GPU, xem hardware.py).
    ollama_model = settings.ollama_model_override or rec.ollama_model

    job = MeetingJob.new(
        source_audio_path=str(dest_path), title=title,
        whisper_model=rec.whisper_model, ollama_model=ollama_model,
    )
    store.save(job)

    q: "queue.Queue[ProgressEvent]" = queue.Queue()
    _progress_queues[job.job_id] = q

    def on_progress(event: ProgressEvent) -> None:
        q.put(event)

    pipeline.run_async(
        job,
        hf_token=settings.hf_token,
        on_progress=on_progress,
        enable_diarization=settings.diarization_enabled,
    )

    return {"job_id": job.job_id, "recommendation": rec.to_dict()}


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str):
    """SSE stream — UI subscribe để cập nhật thanh tiến trình real-time,
    thay vì poll liên tục (nhẹ hơn cho máy yếu)."""
    if job_id not in _progress_queues:
        raise HTTPException(404, "Không tìm thấy job hoặc job đã xử lý xong từ phiên trước")

    q = _progress_queues[job_id]

    async def event_stream():
        loop = asyncio.get_event_loop()
        while True:
            event = await loop.run_in_executor(None, q.get)
            yield f"data: {json.dumps(event.to_dict(), ensure_ascii=False)}\n\n"
            if event.stage.value in ("done", "error"):
                break

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = store.load(job_id)
    if not job:
        raise HTTPException(404, "Không tìm thấy job")
    return job.to_dict()


@app.get("/api/jobs")
def list_jobs():
    """Cho màn hình 'Thư viện biên bản cũ'."""
    return [job.to_dict() for job in store.list_all()]


@app.post("/api/jobs/{job_id}/speakers")
def update_speakers(job_id: str, speaker_names: dict[str, str]):
    """UI gọi khi người dùng gán lại tên người nói bằng kéo-thả
    (SPEAKER_00 -> 'Thiên', SPEAKER_01 -> 'Lan', ...)."""
    job = store.load(job_id)
    if not job:
        raise HTTPException(404, "Không tìm thấy job")
    job.speaker_names = speaker_names
    store.save(job)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/export")
def export_job(job_id: str, fmt: str = "docx"):
    job = store.load(job_id)
    if not job:
        raise HTTPException(404, "Không tìm thấy job")
    if fmt != "docx":
        raise HTTPException(400, "Hiện chỉ hỗ trợ xuất DOCX")

    out_dir = DATA_DIR / "exports"
    out_path = out_dir / f"{job.job_id}.docx"
    export_to_docx(job, out_path)
    return FileResponse(
        out_path, filename=f"{job.title}.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@app.get("/api/estimate")
def estimate(duration_seconds: float, whisper_model: str = "small"):
    """Gọi TRƯỚC khi bắt đầu xử lý, để hiển thị 'ước tính khoảng X phút'
    cho người dùng — giải quyết rủi ro đã nêu: không cảnh báo thời gian trước."""
    hw = detect_hardware()
    est = estimate_processing_time(duration_seconds, whisper_model, hw.has_gpu)
    return {"estimated_seconds": round(est)}
