"""Test thật module transcribe.py với file audio giọng nói thật (espeak-ng),
model 'tiny' để tải nhanh. Không mock — gọi thẳng faster-whisper."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline.transcribe import transcribe_audio

def progress_cb(pct, msg):
    print(f"  [{pct:5.1f}%] {msg}")

if __name__ == "__main__":
    result = transcribe_audio(
        "/tmp/claude-0/test_audio/sample16k.wav",
        model_size="tiny",
        on_progress=progress_cb,
    )
    print(f"\nNgôn ngữ phát hiện: {result.detected_language}")
    print(f"Thời lượng: {result.duration_seconds:.1f}s")
    print("Các đoạn:")
    for seg in result.segments:
        print(f"  [{seg.start:.1f}-{seg.end:.1f}] {seg.text}")
