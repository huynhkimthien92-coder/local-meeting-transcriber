"""
Module diarize: xác định "ai nói khi nào" (speaker diarization).

Đây là rủi ro đã được blueprint gọi tên rõ: "Diarization speaker miễn phí
độ chính xác thấp với nhiều người". Thiết kế ở đây theo đúng quyết định
đã thống nhất: KHÔNG cố gắng làm diarization tự động hoàn hảo, mà:
  1. Chạy pyannote.audio (free, open-source) để có nhãn SPEAKER_00, SPEAKER_01...
  2. Gán nhãn đó vào từng đoạn transcript theo % chồng lấn thời gian.
  3. Để UI cho người dùng SỬA TAY (gán lại tên) — đây là phần bắt buộc,
     không phải tùy chọn, vì độ chính xác tự động không đủ tin cậy.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .models import TranscriptSegment


class DiarizeError(RuntimeError):
    pass


class DiarizeUnavailable(DiarizeError):
    """Diarization không chạy được (thiếu model/token) — pipeline vẫn phải
    tiếp tục chạy được, chỉ là không có nhãn người nói (tất cả = 'unknown'),
    thay vì làm cả pipeline thất bại vì một bước tùy chọn."""


@dataclass
class SpeakerTurn:
    start: float
    end: float
    speaker_label: str  # "SPEAKER_00", "SPEAKER_01", ...


def diarize_audio(
    audio_path: str,
    hf_token: str | None = None,
    on_progress: Callable[[float, str], None] | None = None,
) -> list[SpeakerTurn]:
    """
    Chạy pyannote.audio speaker-diarization pipeline.

    Cần hf_token (Hugging Face access token, free) vì model pyannote yêu cầu
    người dùng tự chấp nhận điều khoản sử dụng trên trang Hugging Face lần
    đầu — đây là bước 1 lần, cần đưa vào onboarding wizard của app, không
    phải thứ người dùng thường tự làm được nếu không có hướng dẫn.
    """
    try:
        from pyannote.audio import Pipeline
    except ImportError as e:
        raise DiarizeUnavailable(
            "Chưa cài đặt pyannote.audio. Chạy: pip install pyannote.audio"
        ) from e

    if not hf_token:
        raise DiarizeUnavailable(
            "Thiếu Hugging Face token để tải model nhận diện người nói. "
            "Xem hướng dẫn lấy token miễn phí trong màn hình cài đặt."
        )

    if on_progress:
        on_progress(0, "Đang nạp model nhận diện người nói...")

    try:
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1", use_auth_token=hf_token
        )
    except Exception as e:
        raise DiarizeUnavailable(
            f"Không nạp được model diarization. Kiểm tra token và kết nối mạng. "
            f"Chi tiết: {e}"
        ) from e

    if on_progress:
        on_progress(10, "Đang phân tích giọng nói theo từng người...")

    try:
        diarization = pipeline(audio_path)
    except Exception as e:
        raise DiarizeError(f"Lỗi khi phân tích người nói: {e}") from e

    turns: list[SpeakerTurn] = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        turns.append(SpeakerTurn(start=turn.start, end=turn.end, speaker_label=speaker))

    if on_progress:
        on_progress(100, "Hoàn tất nhận diện người nói")

    return turns


def assign_speakers_to_segments(
    segments: list[TranscriptSegment], speaker_turns: list[SpeakerTurn]
) -> list[TranscriptSegment]:
    """Gán speaker cho mỗi đoạn transcript dựa trên % thời gian chồng lấn
    lớn nhất với các speaker turn. Nếu không có diarization (danh sách
    rỗng), giữ nguyên speaker='unknown' để UI hiển thị 'Chưa xác định'
    thay vì lỗi."""
    if not speaker_turns:
        return segments

    for seg in segments:
        best_speaker = "unknown"
        best_overlap = 0.0
        for turn in speaker_turns:
            overlap = min(seg.end, turn.end) - max(seg.start, turn.start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = turn.speaker_label
        seg.speaker = best_speaker

    return segments
