"""
Phát hiện cấu hình máy (RAM, CPU, GPU) và đề xuất model phù hợp.

Đây là mảnh ghép giải quyết rủi ro lớn nhất đã nêu trong blueprint:
"LLM local (Ollama) cần RAM 8GB+ để chạy ổn" và "Whisper local chậm trên
máy không có GPU". Thay vì để người dùng tự chọn model (họ không biết
"small" hay "medium" nghĩa là gì), app tự đề xuất — và tự CẢNH BÁO thay
vì crash im lặng khi máy quá yếu.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import os
import platform
import shutil
import subprocess


@dataclass
class HardwareProfile:
    ram_gb: float
    cpu_cores: int
    has_gpu: bool
    gpu_name: str | None
    os_name: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ModelRecommendation:
    whisper_model: str      # tiny | base | small | medium
    ollama_model: str       # vd: "llama3.2:3b", "qwen2.5:7b"
    tier_label: str         # nhãn hiển thị cho người dùng, tiếng Việt
    warning: str | None     # cảnh báo nếu máy dưới mức khuyến nghị

    def to_dict(self) -> dict:
        return asdict(self)


def detect_hardware() -> HardwareProfile:
    ram_gb = _detect_ram_gb()
    cpu_cores = os.cpu_count() or 1
    has_gpu, gpu_name = _detect_gpu()
    return HardwareProfile(
        ram_gb=round(ram_gb, 1),
        cpu_cores=cpu_cores,
        has_gpu=has_gpu,
        gpu_name=gpu_name,
        os_name=platform.system(),
    )


def _detect_ram_gb() -> float:
    try:
        # Linux: đọc /proc/meminfo là cách đáng tin cậy nhất, không cần thư viện ngoài
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return kb / (1024 * 1024)
    except FileNotFoundError:
        pass
    try:
        import psutil  # nếu có sẵn (macOS/Windows nên bundle psutil)
        return psutil.virtual_memory().total / (1024 ** 3)
    except ImportError:
        pass
    return 4.0  # giả định an toàn (thấp) nếu không phát hiện được, để không hứa quá tay


def _detect_gpu() -> tuple[bool, str | None]:
    # Kiểm tra nhanh NVIDIA (phổ biến nhất cho máy người dùng có GPU)
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            out = subprocess.run(
                [nvidia_smi, "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=3,
            )
            name = out.stdout.strip().splitlines()[0] if out.stdout.strip() else None
            if name:
                return True, name
        except Exception:
            pass
    # macOS Apple Silicon: coi như có "GPU" theo nghĩa có Metal/MPS tăng tốc
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return True, "Apple Silicon (Metal)"
    return False, None


def recommend_models(hw: HardwareProfile) -> ModelRecommendation:
    """Quyết định model dựa trên RAM VÀ có GPU hay không.

    Điểm quan trọng (rút ra từ test thật trên máy CPU-only): RAM chỉ quyết
    định model có NẠP ĐƯỢC vào bộ nhớ hay không, nhưng tốc độ SINH của LLM
    (bước tóm tắt) phụ thuộc gần như hoàn toàn vào có GPU hay không — trên
    CPU, model 3B chỉ ra ~3 token/giây, khiến một biên bản ngắn cũng mất
    7-10 phút, cảm giác như app bị treo.

    Đa số người dùng thường (laptop văn phòng, không GPU rời) sẽ rơi vào
    nhánh CPU-only bên dưới dù RAM có 8-16GB, nên KHÔNG được đề xuất model
    to chỉ vì đủ RAM — phải ưu tiên model nhỏ (nhanh) làm mặc định, người
    nào chấp nhận chờ lâu hơn để đổi lấy chất lượng tốt hơn thì tự chọn
    trong Cài đặt (xem app/settings.py: ollama_model_override)."""
    if hw.has_gpu:
        if hw.ram_gb >= 16:
            return ModelRecommendation(
                whisper_model="medium",
                ollama_model="qwen2.5:7b",
                tier_label=f"Máy mạnh (GPU: {hw.gpu_name}) — độ chính xác cao nhất",
                warning=None,
            )
        if hw.ram_gb >= 8:
            return ModelRecommendation(
                whisper_model="small",
                ollama_model="llama3.2:3b",
                tier_label=f"Có GPU ({hw.gpu_name}) — cân bằng tốc độ/độ chính xác",
                warning=None,
            )
        return ModelRecommendation(
            whisper_model="base",
            ollama_model="llama3.2:1b",
            tier_label=f"Có GPU ({hw.gpu_name}) nhưng RAM thấp — ưu tiên tốc độ",
            warning=(
                f"Máy có GPU nhưng chỉ {hw.ram_gb} GB RAM. Dùng model nhỏ để đảm bảo "
                f"chạy ổn định."
            ),
        )

    # --- Không phát hiện GPU rời — đây là trường hợp PHỔ BIẾN NHẤT với người
    # dùng thường, nên phải là nhánh được tối ưu tốt nhất, không phải nhánh
    # "dự phòng". Ollama model luôn chọn loại nhỏ (1B) để bước tóm tắt ra
    # kết quả trong khoảng 1-3 phút thay vì 7-10+ phút. ---
    if hw.ram_gb >= 8:
        return ModelRecommendation(
            whisper_model="small",
            ollama_model="llama3.2:1b",
            tier_label="Máy không có GPU rời — ưu tiên tốc độ tóm tắt",
            warning=(
                "Không phát hiện GPU rời trên máy này. Bước nhận diện lời nói vẫn "
                "chạy tốt trên CPU, nhưng bước sinh biên bản bằng LLM sẽ RẤT chậm "
                "nếu dùng model lớn (có thể mất hàng chục phút cho một cuộc họp "
                "ngắn) — vì vậy app dùng model tóm tắt nhỏ (llama3.2:1b) làm mặc "
                "định để xử lý trong vài phút. Có thể đổi sang model lớn hơn (chậm "
                "hơn nhiều, nhưng biên bản chi tiết hơn) trong màn hình Cài đặt."
            ),
        )
    if hw.ram_gb >= 4:
        return ModelRecommendation(
            whisper_model="base",
            ollama_model="llama3.2:1b",
            tier_label="Máy yếu, không GPU — ưu tiên chạy được",
            warning=(
                f"Máy chỉ có {hw.ram_gb} GB RAM và không có GPU rời. App vẫn chạy "
                f"được nhưng cuộc họp dài (>60 phút) hoặc nhiều ứng dụng mở cùng lúc "
                f"có thể làm xử lý chậm hoặc treo. Khuyến nghị đóng bớt ứng dụng khác "
                f"khi xử lý."
            ),
        )
    return ModelRecommendation(
        whisper_model="tiny",
        ollama_model="llama3.2:1b",
        tier_label="Máy dưới mức khuyến nghị",
        warning=(
            f"Máy chỉ có {hw.ram_gb} GB RAM — dưới mức tối thiểu khuyến nghị (4GB). "
            f"App sẽ dùng model nhỏ nhất để cố chạy được, nhưng độ chính xác transcript "
            f"và bản tóm tắt có thể không đạt yêu cầu. Cân nhắc xử lý cuộc họp ngắn hơn "
            f"hoặc chia nhỏ file audio trước khi nạp vào app."
        ),
    )
