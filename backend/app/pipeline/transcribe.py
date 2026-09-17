"""
Module transcribe: chuyển audio -> text có timestamp, dùng faster-whisper.

Chọn faster-whisper thay vì openai-whisper gốc vì:
- Nhanh hơn 4x trên CPU (dùng CTranslate2), quan trọng cho máy văn phòng
  không có GPU rời — đúng rủi ro "Whisper local chậm trên máy không có GPU"
  đã nêu trong blueprint.
- Hỗ trợ VAD (Voice Activity Detection) sẵn để bỏ qua đoạn im lặng, giúp
  cuộc họp dài xử lý nhanh hơn.
- Hỗ trợ streaming segment-by-segment -> dễ báo % tiến trình thật cho UI,
  thay vì UI phải "giả vờ" progress bar.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator

from .models import TranscriptSegment


class TranscribeError(RuntimeError):
    """Lỗi trong quá trình transcribe — được orchestrator bắt và chuyển
    thành thông báo tiếng Việt dễ hiểu cho người dùng, không phải stack trace."""


@dataclass
class TranscribeResult:
    segments: list[TranscriptSegment]
    detected_language: str
    duration_seconds: float


def transcribe_audio(
    audio_path: str,
    model_size: str = "small",
    device: str = "cpu",
    compute_type: str = "int8",
    on_progress: Callable[[float, str], None] | None = None,
) -> TranscribeResult:
    """
    Chạy Whisper trên file audio, trả về danh sách đoạn có timestamp.

    on_progress(percent_0_to_100, message) được gọi định kỳ để orchestrator
    forward tiếp lên UI qua SSE — đây là chỗ giải quyết rủi ro "không có
    progress cho file dài" đã nêu trong phân tích.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise TranscribeError(
            "Chưa cài đặt faster-whisper. Chạy: pip install faster-whisper"
        ) from e

    if on_progress:
        on_progress(0, f"Đang nạp model Whisper ({model_size})...")

    try:
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
    except Exception as e:
        raise TranscribeError(
            f"Không nạp được model Whisper '{model_size}'. Kiểm tra kết nối mạng "
            f"(lần đầu cần tải model) hoặc dung lượng ổ đĩa còn trống. Chi tiết: {e}"
        ) from e

    if on_progress:
        on_progress(5, "Đang phân tích audio...")

    try:
        segments_iter, info = model.transcribe(
            audio_path,
            vad_filter=True,               # bỏ qua khoảng lặng -> nhanh hơn cho cuộc họp dài
            vad_parameters=dict(min_silence_duration_ms=500),
            word_timestamps=False,
        )
    except Exception as e:
        raise TranscribeError(
            f"Không xử lý được file audio. Kiểm tra file có đúng định dạng "
            f"(mp3, wav, m4a...) và không bị hỏng. Chi tiết: {e}"
        ) from e

    duration = info.duration or 1.0
    result_segments: list[TranscriptSegment] = []

    for seg in segments_iter:
        result_segments.append(
            TranscriptSegment(start=seg.start, end=seg.end, text=seg.text.strip())
        )
        if on_progress:
            # Whisper xử lý tuần tự theo thời gian audio -> seg.end / duration
            # là ước tính % khá sát thực tế, không phải giả lập.
            pct = min(95.0, 5 + (seg.end / duration) * 90)
            on_progress(pct, f"Đang nhận diện lời nói... {int(seg.end)}s / {int(duration)}s")

    if on_progress:
        on_progress(100, "Hoàn tất nhận diện lời nói")

    return TranscribeResult(
        segments=result_segments,
        detected_language=info.language,
        duration_seconds=duration,
    )


def estimate_processing_time(duration_seconds: float, model_size: str, has_gpu: bool) -> float:
    """Ước tính thời gian xử lý (giây) để hiển thị cho người dùng TRƯỚC khi
    bắt đầu — giải quyết rủi ro 'không cảnh báo thời gian trước khi chạy'.
    Hệ số nhân là kinh nghiệm thực tế của faster-whisper trên CPU, không
    phải số liệu chính xác tuyệt đối — nên hiển thị dưới dạng khoảng ước tính."""
    cpu_multiplier = {
        "tiny": 0.3, "base": 0.5, "small": 1.0, "medium": 2.5,
    }.get(model_size, 1.0)
    if has_gpu:
        return duration_seconds * cpu_multiplier * 0.15
    return duration_seconds * cpu_multiplier * 0.6
