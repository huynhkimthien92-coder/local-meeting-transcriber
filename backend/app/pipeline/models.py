"""
Kiểu dữ liệu dùng chung cho pipeline.

Toàn bộ pipeline (transcribe -> diarize -> summarize -> export) trao đổi
dữ liệu qua các dataclass ở đây, để mỗi module có thể test độc lập và
frontend (Tauri) nhận JSON có cấu trúc rõ ràng qua API.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional
import uuid


class JobStage(str, Enum):
    QUEUED = "queued"
    LOADING_MODEL = "loading_model"
    TRANSCRIBING = "transcribing"
    DIARIZING = "diarizing"
    SUMMARIZING = "summarizing"
    DONE = "done"
    ERROR = "error"


@dataclass
class TranscriptSegment:
    """Một đoạn lời nói, có thời gian bắt đầu/kết thúc và (nếu có) người nói."""
    start: float          # giây
    end: float            # giây
    text: str
    speaker: str = "unknown"   # vd: "SPEAKER_00" — sẽ được người dùng đổi tên trong UI

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ProgressEvent:
    """Sự kiện tiến trình gửi về UI qua SSE/WebSocket."""
    job_id: str
    stage: JobStage
    percent: float              # 0-100, tính trong phạm vi cả job
    message: str = ""
    eta_seconds: Optional[float] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["stage"] = self.stage.value
        return d


@dataclass
class MeetingJob:
    """Trạng thái đầy đủ của một job xử lý cuộc họp — được lưu ra đĩa để
    có thể tiếp tục (resume) nếu app bị đóng hoặc mất điện giữa chừng."""
    job_id: str
    source_audio_path: str
    title: str = "Cuộc họp chưa đặt tên"
    stage: JobStage = JobStage.QUEUED
    percent: float = 0.0
    error_message: Optional[str] = None
    whisper_model: str = "small"
    # Chốt NGAY khi tạo job (không để orchestrator tự suy ra lại lúc tóm tắt) —
    # tránh lệch model giữa lúc tạo job và lúc thực sự chạy summarize, đã từng
    # gây lỗi "model chưa tải về" khi 2 chỗ tính recommend_models() ra kết quả
    # khác nhau (vd. máy đổi trạng thái GPU giữa chừng, hiếm nhưng có thể).
    ollama_model: str = "llama3.2:1b"
    segments: list[TranscriptSegment] = field(default_factory=list)
    speaker_names: dict[str, str] = field(default_factory=dict)  # SPEAKER_00 -> "Thiên"
    summary_markdown: Optional[str] = None
    created_at: str = ""

    @staticmethod
    def new(
        source_audio_path: str, title: str,
        whisper_model: str = "small", ollama_model: str = "llama3.2:1b",
    ) -> "MeetingJob":
        import datetime
        return MeetingJob(
            job_id=str(uuid.uuid4()),
            source_audio_path=source_audio_path,
            title=title,
            whisper_model=whisper_model,
            ollama_model=ollama_model,
            created_at=datetime.datetime.now().isoformat(timespec="seconds"),
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["stage"] = self.stage.value
        return d
