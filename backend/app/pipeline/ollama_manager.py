"""
Quản lý vòng đời Ollama theo hướng "người dùng không biết Ollama tồn tại"
(Phương án 2 đã chọn — xem docs/packaging-notes.md mục 2):

- Bản đóng gói thật sẽ bundle Ollama làm sidecar thứ 2 (xem
  frontend/src-tauri/src/main.rs), tự khởi động cùng app — không phải
  người dùng tự cài/tự chạy `ollama serve`.
- Nhưng file MODEL (vài trăm MB - vài GB) thì KHÔNG đóng gói sẵn trong
  installer (installer sẽ quá nặng) — tải về lần đầu mở app, có progress
  bar rõ ràng trong onboarding, không phải lỗi âm thầm lúc xử lý cuộc họp
  đầu tiên như trước đây.

Module này cung cấp các hàm backend cần để làm đúng việc đó: kiểm tra
Ollama đã sẵn sàng chưa, model nào đã có, và tải model kèm tiến trình %.
"""
from __future__ import annotations

from typing import Callable, Iterator
import json

import requests

OLLAMA_BASE_URL = "http://localhost:11434"


class OllamaUnreachable(RuntimeError):
    """Sidecar Ollama chưa kịp khởi động hoặc chưa được bundle đúng cách.
    Khác với summarize.OllamaNotRunning (lỗi lúc xử lý cuộc họp), lỗi này
    xảy ra lúc onboarding — cần thông báo khác vì người dùng chưa từng biết
    Ollama tồn tại, không nên nhắc tên "Ollama" ra UI."""


def is_running(timeout: float = 2.0) -> bool:
    try:
        res = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=timeout)
        return res.status_code == 200
    except requests.exceptions.RequestException:
        return False


def list_local_models(timeout: float = 5.0) -> list[str]:
    """Trả về danh sách tên model đã có sẵn (vd: ["llama3.2:1b"]).
    Rỗng nếu Ollama chưa chạy hoặc chưa tải model nào."""
    try:
        res = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=timeout)
        res.raise_for_status()
        return [m["name"] for m in res.json().get("models", [])]
    except requests.exceptions.RequestException:
        return []


def has_model(model: str) -> bool:
    # Ollama trả tên kèm hậu tố "latest" đôi khi khác cách người dùng gõ
    # (vd "llama3.2:1b" vs "llama3.2:1b" đã khớp, nhưng phòng trường hợp
    # thiếu tag mặc định) — so khớp cả dạng có/không ":latest".
    local = set(list_local_models())
    return model in local or f"{model}:latest" in local


def ensure_model_stream(model: str) -> Iterator[dict]:
    """Generator: tải model nếu chưa có, yield từng bước tiến trình dạng
    {"percent": float, "message": str, "done": bool}. Nếu model đã có sẵn,
    yield ngay 1 sự kiện done=True — để UI luôn xử lý cùng 1 luồng dù có
    tải hay không (đơn giản hoá phía frontend)."""
    if not is_running():
        raise OllamaUnreachable(
            "Chưa sẵn sàng — thử lại sau giây lát. Nếu vẫn vậy, khởi động lại ứng dụng."
        )

    if has_model(model):
        yield {"percent": 100.0, "message": "Đã sẵn sàng.", "done": True}
        return

    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/pull",
            json={"name": model, "stream": True},
            stream=True,
            timeout=(5, 3600),  # tải model lần đầu có thể mất nhiều phút tuỳ mạng
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise OllamaUnreachable(f"Không tải được — kiểm tra kết nối mạng rồi thử lại. ({e})") from e

    for line in response.iter_lines():
        if not line:
            continue
        chunk = json.loads(line)
        status = chunk.get("status", "")
        total = chunk.get("total")
        completed = chunk.get("completed")
        if total and completed is not None:
            percent = min(99.0, (completed / total) * 100)
        elif status in ("success",):
            percent = 100.0
        else:
            percent = 0.0
        yield {"percent": round(percent, 1), "message": status, "done": status == "success"}
