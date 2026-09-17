"""
Cài đặt cấp app (không phải cấp từng cuộc họp) — lưu ra 1 file JSON đơn
giản trong storage/. Hiện chỉ có 2 giá trị nhưng tách file riêng để dễ
mở rộng (vd: model mặc định, thư mục lưu biên bản...) mà không phải sửa
lại MeetingJob.

Quyết định thiết kế quan trọng (theo yêu cầu của Thiên): nhận diện người
nói (diarization) MẶC ĐỊNH TẮT, vì việc setup Hugging Face token là rào
cản lớn với người dùng thường. App vẫn chạy đầy đủ transcribe + tóm tắt
mà không cần bước này. Ai muốn phân biệt người nói thì tự bật trong màn
hình Cài đặt, có hướng dẫn dẫn dắt từng bước (xem /api/settings/*).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import json

SETTINGS_PATH = Path(__file__).resolve().parents[1] / "storage" / "settings.json"


@dataclass
class AppSettings:
    diarization_enabled: bool = False   # mặc định TẮT — xem docstring ở trên
    hf_token: str | None = None
    # Ghi đè model tóm tắt (Ollama) mà app tự đề xuất theo phần cứng — None
    # nghĩa là "dùng đề xuất tự động" (mặc định, ưu tiên tốc độ khi máy
    # không có GPU, xem pipeline/hardware.py). Người dùng nâng cao muốn biên
    # bản chi tiết hơn và chấp nhận chờ lâu hơn có thể tự chọn model lớn hơn
    # (vd. "llama3.2:3b", "qwen2.5:7b") trong màn hình Cài đặt.
    ollama_model_override: str | None = None

    def to_dict(self, mask_token: bool = True) -> dict:
        d = asdict(self)
        if mask_token and d.get("hf_token"):
            token = d["hf_token"]
            d["hf_token_set"] = True
            d["hf_token"] = token[:4] + "…" + token[-4:] if len(token) > 8 else "••••"
        else:
            d["hf_token_set"] = bool(d.get("hf_token"))
        return d


def load_settings() -> AppSettings:
    if not SETTINGS_PATH.exists():
        return AppSettings()
    try:
        data = json.loads(SETTINGS_PATH.read_text())
        return AppSettings(**data)
    except (json.JSONDecodeError, TypeError):
        return AppSettings()


def save_settings(settings: AppSettings) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2))
