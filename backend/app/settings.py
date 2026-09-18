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
import json

from .paths import DATA_DIR

# QUAN TRỌNG: dùng DATA_DIR dùng chung (xem app/paths.py) thay vì tự tính
# theo Path(__file__) -- xem giải thích chi tiết trong app/paths.py (lỗi
# thật đã gặp: cài đặt bị reset về mặc định mỗi lần mở lại app sau khi
# đóng gói PyInstaller).
SETTINGS_PATH = DATA_DIR / "settings.json"


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
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return AppSettings(**data)
    except (json.JSONDecodeError, TypeError):
        return AppSettings()


def save_settings(settings: AppSettings) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    # QUAN TRỌNG: PHẢI chỉ định encoding="utf-8" tường minh. Nếu không,
    # Python trên Windows sẽ dùng bảng mã mặc định của hệ thống (thường là
    # cp1252, không có tiếng Việt) để ghi/đọc file -> lỗi thật đã gặp:
    # "UnicodeEncodeError: 'charmap' codec can't encode character..." khi
    # tiêu đề cuộc họp hoặc nội dung có dấu tiếng Việt (vd "ộ", "ế"...).
    # Trên Linux/macOS mặc định đã là UTF-8 nên không lộ lỗi lúc test ở đó.
    SETTINGS_PATH.write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8"
    )
