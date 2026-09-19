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
from typing import Callable

from .models import TranscriptSegment


class TranscribeError(RuntimeError):
    """Lỗi trong quá trình transcribe — được orchestrator bắt và chuyển
    thành thông báo tiếng Việt dễ hiểu cho người dùng, không phải stack trace."""


@dataclass
class TranscribeResult:
    segments: list[TranscriptSegment]
    detected_language: str
    duration_seconds: float


SAMPLE_RATE = 16000

# QUAN TRỌNG: xử lý audio theo từng đoạn ~10 phút một, KHÔNG đưa nguyên cả
# file dài (vd cuộc họp 50-60 phút) vào Whisper trong 1 lần. Lỗi thật đã
# gặp trên máy 8GB RAM: "Unable to allocate 890 MiB for an array with
# shape (1, 290344, 201) and data type complex128" -- đây là MemoryError
# khi faster-whisper tính phổ tần số (spectrogram) cho TOÀN BỘ audio cùng
# lúc trước khi chia nhỏ để nhận diện; mảng tạm này nặng tỉ lệ thuận với
# độ dài file, không phụ thuộc kích thước model. Cắt nhỏ MẢNG SỐ đã giải
# mã (không phải cắt file) thành từng đoạn rồi transcribe riêng từng đoạn
# giúp mỗi lần chỉ cần RAM tương ứng đoạn đó.
CHUNK_SECONDS = 600.0  # ~10 phút mỗi đoạn
MIN_CHUNK_SECONDS = 10.0  # chia nhỏ tới mức này thì thôi, báo lỗi rõ ràng


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
        on_progress(2, "Đang đọc file audio...")

    # Tự giải mã audio ra mảng số 1 lần bằng chính hàm của faster-whisper
    # (decode_audio) -- bước NÀY an toàn về RAM kể cả file dài (giải mã
    # tuần tự bằng ffmpeg/libav, không tính spectrogram). Chỉ bước tính
    # spectrogram bên trong model.transcribe() mới cần chia nhỏ.
    try:
        from faster_whisper.audio import decode_audio
        full_audio = decode_audio(audio_path, sampling_rate=SAMPLE_RATE)
    except Exception as e:
        raise TranscribeError(
            f"Không xử lý được file audio. Kiểm tra file có đúng định dạng "
            f"(mp3, wav, m4a...) và không bị hỏng. Chi tiết: {e}"
        ) from e

    total_samples = len(full_audio)
    duration = (total_samples / SAMPLE_RATE) if total_samples else 1.0

    if on_progress:
        on_progress(5, "Đang phân tích audio...")

    chunk_samples = int(CHUNK_SECONDS * SAMPLE_RATE)
    min_chunk_samples = int(MIN_CHUNK_SECONDS * SAMPLE_RATE)
    result_segments: list[TranscriptSegment] = []
    detected_language = "vi"

    offset_samples = 0
    while offset_samples < total_samples:
        offset_seconds = offset_samples / SAMPLE_RATE
        attempt_samples = min(chunk_samples, total_samples - offset_samples)
        last_error: Exception | None = None
        segments_list = None
        info = None

        # Nếu vẫn hết RAM ngay cả với đoạn hiện tại (máy quá yếu hoặc đang
        # bị chiếm dụng bởi app khác) -> tự giảm nửa kích thước đoạn rồi
        # thử lại vài lần, thay vì để cả job thất bại ngay lập tức.
        while True:
            attempt_chunk = full_audio[offset_samples: offset_samples + attempt_samples]
            try:
                segments_iter, info = model.transcribe(
                    attempt_chunk,
                    vad_filter=True,
                    vad_parameters=dict(min_silence_duration_ms=500),
                    word_timestamps=False,
                )
                segments_list = list(segments_iter)
                last_error = None
                break
            except MemoryError as e:
                last_error = e
                if attempt_samples <= min_chunk_samples:
                    break
                attempt_samples = max(attempt_samples // 2, min_chunk_samples)
            except Exception as e:
                raise TranscribeError(
                    f"Không xử lý được file audio. Kiểm tra file có đúng định dạng "
                    f"(mp3, wav, m4a...) và không bị hỏng. Chi tiết: {e}"
                ) from e

        if last_error is not None:
            raise TranscribeError(
                "Máy hết bộ nhớ (RAM) khi xử lý file audio này, kể cả sau khi đã "
                "tự chia nhỏ đoạn xử lý. Hãy đóng bớt ứng dụng khác (đặc biệt "
                "trình duyệt) hoặc khởi động lại máy để giải phóng RAM rồi thử "
                f"lại. Chi tiết kỹ thuật: {last_error}"
            )

        for seg in segments_list:
            result_segments.append(
                TranscriptSegment(
                    start=offset_seconds + seg.start,
                    end=offset_seconds + seg.end,
                    text=seg.text.strip(),
                )
            )
        if info is not None and info.language:
            detected_language = info.language

        offset_samples += attempt_samples
        if on_progress:
            # Whisper xử lý tuần tự theo thời gian audio -> tỉ lệ đã xử lý
            # là ước tính % khá sát thực tế, không phải giả lập.
            done_seconds = min(offset_samples / SAMPLE_RATE, duration)
            pct = min(95.0, 5 + (done_seconds / duration) * 90)
            on_progress(pct, f"Đang nhận diện lời nói... {int(done_seconds)}s / {int(duration)}s")

    if on_progress:
        on_progress(100, "Hoàn tất nhận diện lời nói")

    return TranscribeResult(
        segments=result_segments,
        detected_language=detected_language,
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
