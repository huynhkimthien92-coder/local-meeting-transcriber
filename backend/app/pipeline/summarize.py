"""
Module summarize: gọi Ollama local (LLM chạy trên máy, không gửi dữ liệu
lên mạng) để biến transcript thô thành biên bản cuộc họp chuẩn.

Gọi qua HTTP API local (http://localhost:39217) — đây là cách tích hợp
chuẩn với Ollama, không cần thư viện ngoài ngoài `requests`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
import json

import requests

from .models import TranscriptSegment

# Cổng RIÊNG (không dùng 11434 mặc định của Ollama) -- khớp với
# frontend/src-tauri/src/main.rs (OLLAMA_HOST=127.0.0.1:39217) và
# ollama_manager.py. Tránh đụng độ nếu máy người dùng lỡ có cài sẵn Ollama
# khác chạy ở cổng mặc định (lỗi thật đã gặp: "Only one usage of each
# socket address...").
OLLAMA_BASE_URL = "http://localhost:39217"


class SummarizeError(RuntimeError):
    pass


class OllamaNotRunning(SummarizeError):
    """Ollama server chưa chạy — lỗi rất hay gặp với người dùng thường vì
    họ không biết Ollama là một 'server' cần khởi động, không phải app
    bấm-mở-là-chạy. App desktop PHẢI tự khởi động Ollama nền khi mở app
    (xem docs/packaging-notes.md), người dùng không được thấy lỗi kỹ thuật này."""


MEETING_MINUTES_PROMPT_TEMPLATE = """\
Bạn là trợ lý thư ký chuyên nghiệp. Dưới đây là bản ghi lời nói (transcript) \
của một cuộc họp, đã có tên người nói. Hãy viết biên bản cuộc họp CHUẨN, \
súc tích, bằng tiếng Việt, theo đúng cấu trúc sau (dùng markdown):

## Mục tiêu cuộc họp
(1-2 câu tóm tắt mục tiêu chính, suy ra từ nội dung trao đổi)

## Nội dung trao đổi chính
(gạch đầu dòng các điểm quan trọng đã bàn, theo thứ tự thời gian)

## Quyết định
(gạch đầu dòng các quyết định đã chốt trong cuộc họp — nếu không có quyết định nào rõ ràng thì ghi "Không có quyết định cụ thể được chốt")

## Việc cần làm
(liệt kê dạng bảng: Việc cần làm | Người phụ trách | Hạn chót (nếu có nhắc đến))

Chỉ dựa trên nội dung transcript, KHÔNG bịa thêm thông tin không có trong đó. \
Nếu transcript không đủ rõ để xác định người phụ trách hoặc hạn chót, ghi "chưa rõ".

--- TRANSCRIPT ---
{transcript}
--- HẾT TRANSCRIPT ---
"""


def format_transcript_for_prompt(segments: list[TranscriptSegment]) -> str:
    lines = []
    for seg in segments:
        speaker = seg.speaker if seg.speaker != "unknown" else "Người nói"
        lines.append(f"[{speaker}] {seg.text}")
    return "\n".join(lines)


def summarize_meeting(
    segments: list[TranscriptSegment],
    ollama_model: str = "llama3.2:3b",
    on_progress: Callable[[float, str], None] | None = None,
) -> str:
    """Trả về biên bản dạng markdown. Ném OllamaNotRunning nếu server chưa
    chạy — orchestrator sẽ bắt lỗi này để hiển thị hướng dẫn cụ thể thay
    vì thông báo lỗi chung chung."""
    transcript_text = format_transcript_for_prompt(segments)
    prompt = MEETING_MINUTES_PROMPT_TEMPLATE.format(transcript=transcript_text)

    if on_progress:
        on_progress(0, f"Đang tóm tắt biên bản bằng {ollama_model}...")

    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": ollama_model, "prompt": prompt, "stream": True},
            stream=True,
            # connect timeout ngắn, read timeout RẤT dài: token đầu tiên chỉ về
            # sau khi Ollama nạp xong model + xử lý hết prompt (prompt eval) —
            # trên CPU yếu (vd. Colab không có GPU cho Ollama, hoặc máy cấu hình
            # thấp) bước này có thể mất nhiều phút TRƯỚC KHI có ký tự nào chảy về,
            # nên timeout phải đủ rộng để không cắt ngang một job vẫn đang chạy.
            timeout=(10, 1800),
        )
        response.raise_for_status()
    except requests.exceptions.ConnectionError as e:
        raise OllamaNotRunning(
            "Không kết nối được tới Ollama. Ollama cần đang chạy nền để sinh "
            "biên bản. App sẽ tự khởi động Ollama — nếu lỗi này vẫn xuất hiện, "
            "thử khởi động lại ứng dụng."
        ) from e
    except requests.exceptions.HTTPError as e:
        raise SummarizeError(
            f"Model '{ollama_model}' có thể chưa được tải về máy. Chi tiết: {e}"
        ) from e

    full_text = ""
    approx_total_tokens = max(200, len(transcript_text) // 8)  # ước tính thô để ra %
    tokens_seen = 0

    for line in response.iter_lines():
        if not line:
            continue
        chunk = json.loads(line)
        piece = chunk.get("response", "")
        full_text += piece
        tokens_seen += 1
        if on_progress:
            pct = min(95.0, (tokens_seen / approx_total_tokens) * 100)
            on_progress(pct, "Đang sinh biên bản...")
        if chunk.get("done"):
            break

    if on_progress:
        on_progress(100, "Hoàn tất biên bản")

    if not full_text.strip():
        raise SummarizeError("Ollama trả về kết quả rỗng — thử lại hoặc đổi model.")

    return full_text.strip()
