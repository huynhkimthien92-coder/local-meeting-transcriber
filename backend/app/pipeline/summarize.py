"""
Module summarize: gọi Ollama local (LLM chạy trên máy, không gửi dữ liệu
lên mạng) để biến transcript thô thành biên bản cuộc họp chuẩn.

Gọi qua HTTP API local (http://localhost:39217) — đây là cách tích hợp
chuẩn với Ollama, không cần thư viện ngoài ngoài `requests`.
"""
from __future__ import annotations

from typing import Callable
import json

import requests

from . import ollama_manager
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
của một cuộc họp, đã có tên người nói (transcript có thể đã được tóm tắt \
theo từng phần trước đó nếu cuộc họp dài — xem rõ trong nội dung). Hãy viết \
biên bản cuộc họp CHUẨN, súc tích, bằng tiếng Việt, theo đúng cấu trúc sau \
(dùng markdown):

## Mục tiêu cuộc họp
(1-2 câu tóm tắt mục tiêu chính, suy ra từ nội dung trao đổi)

## Nội dung trao đổi chính
(gạch đầu dòng các điểm quan trọng đã bàn, theo thứ tự thời gian, bao quát \
TOÀN BỘ các phần đã cho, không chỉ phần đầu)

## Quyết định
(gạch đầu dòng các quyết định đã chốt trong cuộc họp — nếu không có quyết định nào rõ ràng thì ghi "Không có quyết định cụ thể được chốt")

## Việc cần làm
(liệt kê dạng bảng: Việc cần làm | Người phụ trách | Hạn chót (nếu có nhắc đến))

Chỉ dựa trên nội dung đã cho, KHÔNG bịa thêm thông tin không có trong đó. \
Nếu không đủ rõ để xác định người phụ trách hoặc hạn chót, ghi "chưa rõ".

--- NỘI DUNG ---
{transcript}
--- HẾT NỘI DUNG ---
"""

# QUAN TRỌNG: Ollama mặc định chỉ cho model "nhìn thấy" tối đa ~4096 token
# (num_ctx mặc định, khoảng 3000 từ tiếng Việt) trong 1 lần gọi. Một cuộc
# họp dài (vd 52 phút) có transcript dài hơn thế RẤT NHIỀU -- nếu nhét
# nguyên transcript vào 1 lần gọi, phần vượt quá cửa sổ ngữ cảnh bị ÂM THẦM
# CẮT BỎ, khiến biên bản chỉ phản ánh đúng đoạn ĐẦU cuộc họp -- lỗi thật đã
# gặp: biên bản ra "quá sơ sài và sai" dù transcript gốc đầy đủ. Giải pháp:
# chia transcript thành từng đoạn nhỏ (đủ nằm gọn trong cửa sổ ngữ cảnh kể
# cả với model nhỏ 1B dùng cho máy không GPU, xem hardware.py), tóm tắt
# riêng từng đoạn ("map"), rồi tóm tắt LẦN NỮA từ các đoạn đã tóm tắt để ra
# biên bản cuối ("reduce") -- không đoạn nào của cuộc họp bị bỏ sót.
CHUNK_CHAR_LIMIT = 6000  # ~1500 từ tiếng Việt mỗi đoạn

CHUNK_DIGEST_PROMPT_TEMPLATE = """\
Đây là MỘT PHẦN (không phải toàn bộ) bản ghi lời nói của 1 cuộc họp, đã có \
tên người nói. Hãy liệt kê ngắn gọn, dạng gạch đầu dòng, các ý chính / quyết \
định / việc cần làm ĐÃ NÓI TRONG ĐOẠN NÀY (giữ nguyên tên riêng, số liệu nếu \
có). KHÔNG bịa thêm, KHÔNG cố tóm tắt cả cuộc họp — chỉ đoạn dưới đây.

--- ĐOẠN TRANSCRIPT ---
{chunk}
--- HẾT ĐOẠN ---
"""


def format_transcript_for_prompt(segments: list[TranscriptSegment]) -> str:
    lines = []
    for seg in segments:
        speaker = seg.speaker if seg.speaker != "unknown" else "Người nói"
        lines.append(f"[{speaker}] {seg.text}")
    return "\n".join(lines)


def _split_transcript_into_chunks(transcript_text: str, limit: int = CHUNK_CHAR_LIMIT) -> list[str]:
    """Cắt theo dòng (mỗi dòng là 1 lượt nói) để không cắt ngang câu — gom
    dòng cho tới khi gần chạm giới hạn ký tự thì bắt đầu đoạn mới."""
    lines = transcript_text.split("\n")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        if current and current_len + len(line) > limit:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks or [transcript_text]


def _ollama_generate(model: str, prompt: str, on_progress: Callable[[float], None] | None = None) -> str:
    """Gọi Ollama /api/generate (stream), trả về text đầy đủ khi xong.
    on_progress (nếu có) được gọi với % 0-100 theo số "token" ước lượng đã
    nhận — caller tự quy đổi sang thang % tổng thể của mình."""
    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": model, "prompt": prompt, "stream": True},
            stream=True,
            # connect timeout ngắn, read timeout RẤT dài: token đầu tiên chỉ về
            # sau khi Ollama nạp xong model + xử lý hết prompt (prompt eval) —
            # trên CPU yếu bước này có thể mất nhiều phút TRƯỚC KHI có ký tự
            # nào chảy về, nên timeout phải đủ rộng để không cắt ngang job.
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
            f"Model '{model}' có thể chưa được tải về máy. Chi tiết: {e}"
        ) from e

    full_text = ""
    approx_total_tokens = max(200, len(prompt) // 8)  # ước tính thô để ra %
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
            on_progress(pct)
        if chunk.get("done"):
            break

    return full_text.strip()


def summarize_meeting(
    segments: list[TranscriptSegment],
    ollama_model: str = "llama3.2:3b",
    on_progress: Callable[[float, str], None] | None = None,
) -> str:
    """Trả về biên bản dạng markdown. Ném OllamaNotRunning nếu server chưa
    chạy — orchestrator sẽ bắt lỗi này để hiển thị hướng dẫn cụ thể thay
    vì thông báo lỗi chung chung."""
    transcript_text = format_transcript_for_prompt(segments)

    # QUAN TRỌNG: KHÔNG được giả định model đã có sẵn ở đây. Màn hình Cài đặt
    # ("Lưu lựa chọn" model tóm tắt) chỉ LƯU TÊN model người dùng chọn, không
    # tự tải về -- model chỉ thực sự được tải đúng 1 lần lúc onboarding, cho
    # ĐÚNG model được đề xuất lúc đó. Nếu người dùng đổi sang model khác sau
    # onboarding (hoặc đổi ổ lưu trữ khiến model cũ không còn thấy nữa), model
    # mới/đang trỏ tới chưa từng được tải -> lỗi thật đã gặp: "Model
    # 'llama3.2:1b' có thể chưa được tải về máy... 404 Client Error: Not
    # Found for url: .../api/generate". Tự kiểm tra + tải (nếu thiếu) ngay ở
    # đây, có tiến trình %, để job không bao giờ crash vì lý do này nữa.
    if on_progress:
        on_progress(0, f"Đang kiểm tra model {ollama_model}...")

    try:
        for progress in ollama_manager.ensure_model_stream(ollama_model):
            if on_progress:
                pct = min(15.0, progress["percent"] * 0.15)
                msg = progress["message"] or f"Đang tải model {ollama_model}..."
                on_progress(pct, msg)
    except ollama_manager.OllamaUnreachable as e:
        raise OllamaNotRunning(
            f"Không tải được model '{ollama_model}'. {e}"
        ) from e

    chunks = _split_transcript_into_chunks(transcript_text)

    if len(chunks) <= 1:
        # Cuộc họp ngắn, transcript đã nằm gọn trong 1 đoạn -- không cần
        # bước "map" trung gian, tóm tắt thẳng như trước (nhanh hơn).
        condensed = transcript_text
        base_pct = 15.0
    else:
        digests: list[str] = []
        n = len(chunks)
        for i, chunk in enumerate(chunks):
            if on_progress:
                on_progress(15.0 + (i / n) * 55.0, f"Đang đọc phần {i + 1}/{n} cuộc họp...")
            digest = _ollama_generate(
                ollama_model, CHUNK_DIGEST_PROMPT_TEMPLATE.format(chunk=chunk)
            )
            digests.append(f"[Phần {i + 1}/{n}]\n{digest}")
        condensed = "\n\n".join(digests)
        base_pct = 70.0

    if on_progress:
        on_progress(base_pct, f"Đang tổng hợp biên bản bằng {ollama_model}...")

    prompt = MEETING_MINUTES_PROMPT_TEMPLATE.format(transcript=condensed)
    remaining = 100.0 - base_pct

    def _final_progress(pct: float) -> None:
        if on_progress:
            on_progress(base_pct + (pct / 100.0) * remaining, "Đang sinh biên bản...")

    full_text = _ollama_generate(ollama_model, prompt, on_progress=_final_progress)

    if on_progress:
        on_progress(100, "Hoàn tất biên bản")

    if not full_text.strip():
        raise SummarizeError("Ollama trả về kết quả rỗng — thử lại hoặc đổi model.")

    return full_text
