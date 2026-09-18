"""
Orchestrator: điều phối toàn bộ pipeline (transcribe -> diarize -> summarize),
chạy trong thread nền (không block UI), báo tiến trình, lưu trạng thái ra
đĩa sau mỗi bước để có thể RESUME nếu app bị đóng hoặc mất điện giữa chừng
— đúng yêu cầu đã đặt ra trong Giai đoạn 5 (QA & rủi ro) của blueprint.
"""
from __future__ import annotations

import json
import os
import threading
import traceback
from pathlib import Path
from typing import Callable

from .models import MeetingJob, JobStage, ProgressEvent, TranscriptSegment
from .transcribe import transcribe_audio, TranscribeError
from .diarize import diarize_audio, assign_speakers_to_segments, DiarizeUnavailable, DiarizeError
from .summarize import summarize_meeting, SummarizeError, OllamaNotRunning
from ..paths import DATA_DIR

# QUAN TRỌNG: dùng DATA_DIR dùng chung (xem app/paths.py) -- KHÔNG tự tính
# lại theo Path(__file__) ở đây, vì sau khi đóng gói PyInstaller --onefile,
# vị trí file code chỉ là thư mục tạm bị xoá mỗi lần tắt app (lỗi thật đã
# gặp: mất hết job đã lưu sau khi tắt/mở lại app).
STORAGE_DIR = DATA_DIR / "meetings"

# Trọng số % cho từng bước trong tổng tiến trình hiển thị cho người dùng.
# Transcribe thường chiếm nhiều thời gian nhất trên máy không GPU.
# Có 2 bộ trọng số vì diarization mặc định TẮT (xem app/settings.py) — khi
# tắt, pipeline chỉ có 2 bước nên % phải chia lại, không để thanh tiến
# trình "kẹt" ở khoảng dành cho bước không chạy.
STAGE_WEIGHTS_WITH_DIARIZATION = {
    JobStage.TRANSCRIBING: (0, 70),
    JobStage.DIARIZING: (70, 85),
    JobStage.SUMMARIZING: (85, 100),
}
STAGE_WEIGHTS_NO_DIARIZATION = {
    JobStage.TRANSCRIBING: (0, 80),
    JobStage.SUMMARIZING: (80, 100),
}


class JobStore:
    """Lưu/đọc trạng thái job ra file JSON trong storage/meetings/<job_id>/job.json.
    Đơn giản, không cần database — phù hợp app desktop chạy local, single-user."""

    def __init__(self, storage_dir: Path = STORAGE_DIR):
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _job_dir(self, job_id: str) -> Path:
        d = self.storage_dir / job_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(self, job: MeetingJob) -> None:
        path = self._job_dir(job.job_id) / "job.json"
        # QUAN TRỌNG: PHẢI chỉ định encoding="utf-8" tường minh -- thiếu
        # dòng này, Windows dùng bảng mã mặc định của máy (thường cp1252,
        # không có tiếng Việt) để ghi file -> lỗi thật đã gặp:
        # "UnicodeEncodeError: 'charmap' codec can't encode character..."
        # ngay khi tiêu đề/nội dung cuộc họp có dấu tiếng Việt. Linux/macOS
        # mặc định đã UTF-8 nên lỗi này không lộ ra lúc test trên máy đó.
        path.write_text(
            json.dumps(job.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def load(self, job_id: str) -> MeetingJob | None:
        path = self._job_dir(job_id) / "job.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        segments = [TranscriptSegment(**s) for s in data.get("segments", [])]
        data["segments"] = segments
        data["stage"] = JobStage(data["stage"])
        return MeetingJob(**data)

    def list_all(self) -> list[MeetingJob]:
        jobs = []
        for d in sorted(self.storage_dir.iterdir(), reverse=True):
            if d.is_dir():
                job = self.load(d.name)
                if job:
                    jobs.append(job)
        return jobs


class MeetingPipeline:
    """Chạy một MeetingJob từ đầu đến cuối trong thread nền.

    on_progress: callback(ProgressEvent) — orchestrator gọi mỗi khi có cập
    nhật, để API server forward qua SSE cho frontend (xem app/api/server.py).
    """

    def __init__(self, store: JobStore | None = None):
        self.store = store or JobStore()

    def run_async(
        self,
        job: MeetingJob,
        hf_token: str | None,
        on_progress: Callable[[ProgressEvent], None],
        enable_diarization: bool = False,
    ) -> threading.Thread:
        thread = threading.Thread(
            target=self._run, args=(job, hf_token, on_progress, enable_diarization), daemon=True
        )
        thread.start()
        return thread

    def _emit(self, job: MeetingJob, stage: JobStage, local_pct: float, message: str,
              on_progress: Callable[[ProgressEvent], None], weights: dict) -> None:
        lo, hi = weights.get(stage, (0, 100))
        overall_pct = lo + (local_pct / 100.0) * (hi - lo)
        job.stage = stage
        job.percent = round(overall_pct, 1)
        self.store.save(job)
        on_progress(ProgressEvent(job_id=job.job_id, stage=stage, percent=job.percent, message=message))

    def _run(self, job: MeetingJob, hf_token: str | None,
              on_progress: Callable[[ProgressEvent], None],
              enable_diarization: bool = False) -> None:
        weights = STAGE_WEIGHTS_WITH_DIARIZATION if enable_diarization else STAGE_WEIGHTS_NO_DIARIZATION
        try:
            # --- Bước 1: Transcribe (bắt buộc) ---
            def transcribe_cb(pct: float, msg: str) -> None:
                self._emit(job, JobStage.TRANSCRIBING, pct, msg, on_progress, weights)

            result = transcribe_audio(
                job.source_audio_path, model_size=job.whisper_model,
                on_progress=transcribe_cb,
            )
            job.segments = result.segments
            self.store.save(job)

            # --- Bước 2: Diarize — CHỈ chạy nếu người dùng chủ động bật trong
            # Cài đặt (mặc định tắt, xem app/settings.py). Bỏ qua hẳn bước này
            # khi tắt, thay vì cố chạy rồi báo lỗi thiếu token — người dùng
            # không bật thì không nên thấy nhắc gì về HF token cả. ---
            if enable_diarization:
                def diarize_cb(pct: float, msg: str) -> None:
                    self._emit(job, JobStage.DIARIZING, pct, msg, on_progress, weights)

                try:
                    turns = diarize_audio(job.source_audio_path, hf_token=hf_token, on_progress=diarize_cb)
                    job.segments = assign_speakers_to_segments(job.segments, turns)
                except DiarizeUnavailable as e:
                    # Lỗi ở đây KHÔNG làm hỏng cả job — transcript vẫn có giá
                    # trị dù không phân biệt được người nói.
                    self._emit(job, JobStage.DIARIZING, 100,
                                f"Bỏ qua nhận diện người nói: {e}", on_progress, weights)
                except DiarizeError as e:
                    self._emit(job, JobStage.DIARIZING, 100,
                                f"Nhận diện người nói lỗi, tiếp tục không có nhãn người nói: {e}",
                                on_progress, weights)
                self.store.save(job)

            # --- Bước 3: Summarize (bắt buộc) ---
            def summarize_cb(pct: float, msg: str) -> None:
                self._emit(job, JobStage.SUMMARIZING, pct, msg, on_progress, weights)

            # Dùng đúng model đã chốt lúc TẠO job (job.ollama_model) — không tự
            # suy ra lại ở đây nữa, để tránh lệch model giữa 2 thời điểm.
            job.summary_markdown = summarize_meeting(
                job.segments, ollama_model=job.ollama_model, on_progress=summarize_cb,
            )

            job.stage = JobStage.DONE
            job.percent = 100.0
            self.store.save(job)
            on_progress(ProgressEvent(job_id=job.job_id, stage=JobStage.DONE, percent=100,
                                        message="Hoàn tất"))

        except (TranscribeError, OllamaNotRunning, SummarizeError) as e:
            # Lỗi "đã biết" -> thông báo tiếng Việt rõ ràng, không phải stack trace
            job.stage = JobStage.ERROR
            job.error_message = str(e)
            self.store.save(job)
            on_progress(ProgressEvent(job_id=job.job_id, stage=JobStage.ERROR, percent=job.percent,
                                        message=str(e)))
        except Exception as e:
            # Lỗi không lường trước -> vẫn lưu lại job để user không mất hoàn toàn
            # tiến trình, và log traceback đầy đủ ra file riêng để debug sau.
            job.stage = JobStage.ERROR
            job.error_message = f"Lỗi không xác định: {e}"
            self.store.save(job)
            (self.store._job_dir(job.job_id) / "error_trace.log").write_text(
                traceback.format_exc(), encoding="utf-8"
            )
            on_progress(ProgressEvent(job_id=job.job_id, stage=JobStage.ERROR, percent=job.percent,
                                        message=job.error_message))
