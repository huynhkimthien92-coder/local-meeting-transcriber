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
# riêng từng đoạn ("map").
# QUAN TRỌNG (tối ưu tốc độ, lỗi thật đã gặp: xử lý cuộc họp 52 phút mất hơn
# 2 tiếng trên máy CPU yếu không GPU): CHUNK_CHAR_LIMIT càng lớn thì càng ÍT
# lần gọi Ollama (đỡ tốn thời gian "nạp" prompt lặp lại mỗi lần gọi), nhưng
# vẫn phải đủ NHỎ để prompt + phần model sinh ra nằm gọn trong cửa sổ ngữ
# cảnh 4096 token (xem _ollama_generate). Đã tăng nhẹ so với ban đầu (6000
# -> 8000 ký tự) để giảm số lần gọi mà vẫn còn dư khoảng cách an toàn.
CHUNK_CHAR_LIMIT = 8000  # ~2000 từ tiếng Việt mỗi đoạn

CHUNK_DIGEST_PROMPT_TEMPLATE = """\
Đây là MỘT PHẦN (không phải toàn bộ) bản ghi lời nói của 1 cuộc họp, đã có \
tên người nói. Hãy liệt kê THẬT NGẮN GỌN (mỗi gạch đầu dòng tối đa 1 câu, \
diễn giải lại bằng lời của bạn -- KHÔNG chép nguyên văn từng câu trong \
transcript), dạng gạch đầu dòng, các ý chính / quyết định / việc cần làm ĐÃ \
NÓI TRONG ĐOẠN NÀY (giữ nguyên tên riêng, số liệu nếu có). KHÔNG bịa thêm, \
KHÔNG cố tóm tắt cả cuộc họp — chỉ đoạn dưới đây.

--- ĐOẠN TRANSCRIPT ---
{chunk}
--- HẾT ĐOẠN ---
"""

# QUAN TRỌNG (lỗi thật đã gặp lần 2, sau khi đã sửa lỗi cắt context ở trên):
# dù prompt cuối đã nằm gọn trong cửa sổ ngữ cảnh (vd chỉ ~2000 token), model
# NHỎ (llama3.2:1b, dùng cho máy yếu không GPU) vẫn có thể "bỏ cuộc" giữa
# chừng khi phải viết LẠI TOÀN BỘ biên bản có cấu trúc (4 phần) từ nhiều
# đoạn digest cùng lúc -- log thực tế cho thấy model chỉ sinh ra ĐÚNG 68
# token rồi dừng hẳn (không phải do timeout/cắt context), ra một đoạn văn
# ngắn, lạc đề, không liên quan tới nội dung cuộc họp. Đây là giới hạn khả
# năng làm theo hướng dẫn phức tạp của model 1B, không phải lỗi code.
#
# Giải pháp: KHÔNG giao cho model việc viết lại toàn bộ nội dung -- phần
# "Nội dung trao đổi chính" (phần quan trọng nhất, hay bị "quá sơ sài" nhất)
# được GHÉP TRỰC TIẾP từ các đoạn digest đã tóm tắt ở bước map, không qua
# model nữa -- luôn đầy đủ, không bao giờ bị model làm hỏng/bỏ sót. Model chỉ
# còn phải làm việc NHẸ hơn nhiều: rút ra Mục tiêu / Quyết định / Việc cần
# làm từ các đoạn digest đó -- và nếu model vẫn không theo đúng format (ví
# dụ lại bỏ cuộc sớm), có phần dự phòng để biên bản KHÔNG BAO GIỜ chỉ còn 1
# đoạn văn ngắn/lạc đề như đã gặp -- tệ nhất là thiếu vài dòng, chứ nội dung
# chính vẫn luôn đầy đủ và đúng.
FINAL_SYNTHESIS_PROMPT_TEMPLATE = """\
Dưới đây là các đoạn tóm tắt (mỗi đoạn ứng với 1 phần của MỘT cuộc họp dài, \
đánh số theo đúng thứ tự thời gian đã diễn ra). Dựa vào TOÀN BỘ các đoạn \
này, hãy viết đúng 3 phần sau bằng tiếng Việt, dùng markdown, PHẢI có đủ \
3 tiêu đề bắt đầu bằng "##" đúng như dưới đây, KHÔNG viết thêm phần nào khác \
và KHÔNG liệt kê lại chi tiết nội dung (phần đó đã có sẵn ở chỗ khác):

## Mục tiêu cuộc họp
(1-2 câu, suy ra từ toàn bộ các đoạn tóm tắt)

## Quyết định
(gạch đầu dòng các quyết định đã chốt, xuyên suốt tất cả các đoạn — nếu \
không có quyết định nào rõ ràng thì ghi "Không có quyết định cụ thể được chốt")

## Việc cần làm
(liệt kê dạng bảng: Việc cần làm | Người phụ trách | Hạn chót (nếu có nhắc đến) \
— nếu không có việc cụ thể nào thì ghi 1 dòng "Không có việc cụ thể được giao | chưa rõ | chưa rõ")

Chỉ dựa trên nội dung đã cho, KHÔNG bịa thêm thông tin không có trong đó.

--- CÁC ĐOẠN TÓM TẮT ---
{condensed}
--- HẾT ---
"""

# Dùng khi cuộc họp NGẮN (không cần chia đoạn) -- vẫn giữ prompt đầy đủ 4
# phần như cũ vì lúc này model chỉ phải đọc transcript gốc 1 lần, việc nhẹ
# hơn nhiều so với việc phải "viết lại" từ nhiều đoạn digest đã tóm tắt.
MEETING_MINUTES_PROMPT_TEMPLATE = """\
Bạn là trợ lý thư ký chuyên nghiệp. Dưới đây là bản ghi lời nói (transcript) \
của một cuộc họp, đã có tên người nói. Hãy viết biên bản cuộc họp CHUẨN, \
súc tích, bằng tiếng Việt, theo đúng cấu trúc sau (dùng markdown):

## Mục tiêu cuộc họp
(1-2 câu tóm tắt mục tiêu chính, suy ra từ nội dung trao đổi)

## Nội dung trao đổi chính
(gạch đầu dòng các điểm quan trọng đã bàn, theo thứ tự thời gian, bao quát \
TOÀN BỘ nội dung đã cho, không chỉ phần đầu)

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


def _extract_section(text: str, keyword: str) -> str | None:
    """Tìm đoạn bắt đầu từ dòng heading có chứa `keyword` (không phân biệt
    hoa/thường, chấp nhận cả dạng model tự ý dùng "**Tiêu đề:**" thay vì
    "## Tiêu đề") tới heading tiếp theo hoặc hết văn bản. Trả None nếu không
    tìm thấy -- dùng để phát hiện khi model nhỏ KHÔNG theo đúng format yêu
    cầu (lỗi thật đã gặp: model 1B bỏ cuộc giữa chừng, ra 1 đoạn văn ngắn
    không có tiêu đề nào), để còn có fallback an toàn thay vì hiển thị
    nguyên văn kết quả sai/thiếu đó cho người dùng."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        is_heading = stripped.startswith("#") or (stripped.startswith("**") and "*" in stripped[2:])
        if is_heading and keyword.lower() in stripped.lower():
            start = i
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        s = lines[j].strip()
        if s.startswith("#") or (s.startswith("**") and "*" in s[2:]):
            end = j
            break
    section = "\n".join(lines[start:end]).strip()
    return section or None


def _ollama_generate(
    model: str,
    prompt: str,
    on_progress: Callable[[float], None] | None = None,
    num_predict: int = 900,
) -> str:
    """Gọi Ollama /api/generate (stream), trả về text đầy đủ khi xong.
    on_progress (nếu có) được gọi với % 0-100 theo số "token" ước lượng đã
    nhận — caller tự quy đổi sang thang % tổng thể của mình.

    QUAN TRỌNG (lỗi thật đã gặp): model nhỏ (1B) đôi khi rơi vào LẶP VÒNG
    LẶP -- thay vì dừng đúng lúc (vài trăm token cho 1 đoạn tóm tắt ngắn),
    nó sinh liên tục hàng nghìn token (log thực tế: 1 lần sinh tới 3395-3787
    token) cho tới khi TRÀN cửa sổ ngữ cảnh (n_ctx=4096) và bị Ollama cắt
    ngang giữa chừng -- vừa làm kết quả không đúng định dạng (mất phần cuối,
    hỏng cả các tiêu đề "##"), vừa tốn thêm 10+ phút vô ích trên máy yếu.
    num_predict giới hạn cứng số token model được sinh mỗi lần gọi -- chặn
    đứng vòng lặp sớm thay vì để nó tự tràn context, và repeat_penalty cao
    hơn mặc định của Ollama (1.1) để giảm khả năng lặp ngay từ đầu."""
    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": True,
                "options": {
                    "num_predict": num_predict,
                    "repeat_penalty": 1.3,
                    "repeat_last_n": 256,
                },
            },
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
        # bước "map" trung gian, tóm tắt thẳng như trước (nhanh hơn, và model
        # chỉ phải đọc + viết 1 lần nên ít rủi ro "bỏ cuộc" hơn).
        if on_progress:
            on_progress(15.0, f"Đang tổng hợp biên bản bằng {ollama_model}...")

        def _short_progress(pct: float) -> None:
            if on_progress:
                on_progress(15.0 + (pct / 100.0) * 85.0, "Đang sinh biên bản...")

        full_text = _ollama_generate(
            ollama_model,
            MEETING_MINUTES_PROMPT_TEMPLATE.format(transcript=transcript_text),
            on_progress=_short_progress,
            # Cuộc họp ngắn nhưng phải viết đủ 4 phần (kể cả "Nội dung trao
            # đổi chính" đầy đủ) -- cho phép dài hơn digest thường.
            num_predict=1500,
        )
        if on_progress:
            on_progress(100, "Hoàn tất biên bản")
        if not full_text.strip():
            raise SummarizeError("Ollama trả về kết quả rỗng — thử lại hoặc đổi model.")
        return full_text

    # Cuộc họp dài -- bước "map": tóm tắt riêng từng đoạn.
    digests: list[str] = []
    n = len(chunks)
    for i, chunk in enumerate(chunks):
        if on_progress:
            on_progress(15.0 + (i / n) * 55.0, f"Đang đọc phần {i + 1}/{n} cuộc họp...")
        digest = _ollama_generate(
            ollama_model,
            CHUNK_DIGEST_PROMPT_TEMPLATE.format(chunk=chunk),
            # QUAN TRỌNG (tối ưu tốc độ): log thực tế cho thấy digest của
            # model 1B thường KHÔNG cô đọng nhiều -- gần như chép lại từng
            # câu của transcript gốc thay vì tóm tắt thật sự, khiến bước
            # "map" (sinh chữ, tốc độ chỉ ~6-9 token/giây trên CPU yếu) tốn
            # rất nhiều thời gian. Hạ trần xuống 500 (từ 900) để ép model
            # dừng sớm hơn, cắt đáng kể thời gian sinh mỗi đoạn -- không mất
            # nội dung vì transcript gốc của đoạn vẫn luôn còn nguyên trong
            # Phụ lục của biên bản.
            num_predict=500,
        )
        if not digest or len(digest) < 15:
            # Model không tóm tắt được đoạn này (hiếm, nhưng không được để
            # mất trắng nội dung đoạn đó khỏi biên bản) -- vẫn giữ nguyên
            # văn transcript gốc của đoạn làm "digest" thay thế.
            digest = chunk
        digests.append(f"**Phần {i + 1}/{n}**\n{digest}")
    condensed = "\n\n".join(digests)

    # "Nội dung trao đổi chính" GHÉP TRỰC TIẾP từ các đoạn digest -- KHÔNG
    # qua thêm 1 lần gọi model nữa để "viết lại toàn bộ", vì đó chính xác là
    # bước model nhỏ (1B) đã bỏ cuộc giữa chừng trong lần gặp lỗi thật. Ghép
    # trực tiếp đảm bảo phần quan trọng nhất của biên bản luôn đầy đủ, đúng
    # thứ tự, không phụ thuộc khả năng model.
    content_section = "## Nội dung trao đổi chính\n" + condensed

    base_pct = 70.0
    if on_progress:
        on_progress(base_pct, f"Đang tổng hợp mục tiêu/quyết định bằng {ollama_model}...")

    remaining = 100.0 - base_pct

    def _final_progress(pct: float) -> None:
        if on_progress:
            on_progress(base_pct + (pct / 100.0) * remaining, "Đang tổng hợp biên bản...")

    synth_prompt = FINAL_SYNTHESIS_PROMPT_TEMPLATE.format(condensed=condensed)
    synth_text = _ollama_generate(
        ollama_model,
        synth_prompt,
        on_progress=_final_progress,
        # Chỉ cần 3 mục ngắn (Mục tiêu/Quyết định/Việc cần làm), không phải
        # viết lại nội dung -- log thực tế cho thấy khi KHÔNG chặn, model có
        # thể lặp tới 3787 token rồi bị cắt cụt mất định dạng. Hạ tiếp xuống
        # 500 (từ 700, tối ưu tốc độ) -- vẫn đủ cho 3 mục ngắn, tránh lặp
        # lan man và sinh nhanh hơn trên CPU yếu.
        num_predict=500,
    )

    muc_tieu_section = _extract_section(synth_text, "Mục tiêu")
    quyet_dinh_section = _extract_section(synth_text, "Quyết định")
    viec_can_lam_section = _extract_section(synth_text, "Việc cần làm")

    # Dự phòng: nếu model không theo đúng format (kể cả bỏ cuộc/ra nội dung
    # lạc đề như lỗi thật đã gặp), KHÔNG hiển thị nguyên văn kết quả sai đó
    # -- dùng câu mặc định rõ ràng, để người dùng biết phần này chưa tự động
    # trích xuất được, thay vì đọc nhầm 1 đoạn văn không liên quan.
    if not muc_tieu_section:
        muc_tieu_section = (
            "## Mục tiêu cuộc họp\n"
            "(Không tự động tóm tắt được mục tiêu — xem phần Nội dung trao đổi chính bên dưới.)"
        )
    if not quyet_dinh_section:
        quyet_dinh_section = (
            "## Quyết định\n"
            "Không tự động trích xuất được — xem phần Nội dung trao đổi chính bên dưới."
        )
    if not viec_can_lam_section:
        viec_can_lam_section = "## Việc cần làm\nchưa rõ"

    if on_progress:
        on_progress(100, "Hoàn tất biên bản")

    return f"{muc_tieu_section}\n\n{content_section}\n\n{quyet_dinh_section}\n\n{viec_can_lam_section}"
