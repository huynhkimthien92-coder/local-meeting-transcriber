"""Test nhanh module docx_export bằng dữ liệu giả — không cần Whisper/Ollama.
Chạy: python3 -m tests.test_docx_export
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline.models import MeetingJob, TranscriptSegment, JobStage
from app.export.docx_export import export_to_docx


def make_fake_job() -> MeetingJob:
    job = MeetingJob.new(source_audio_path="fake.wav", title="Họp kế hoạch Q4")
    job.stage = JobStage.DONE
    job.segments = [
        TranscriptSegment(start=0.0, end=4.2, text="Chào mọi người, mình bắt đầu họp nhé.", speaker="SPEAKER_00"),
        TranscriptSegment(start=4.5, end=9.1, text="Vâng, tuần này mình cần chốt kế hoạch Q4.", speaker="SPEAKER_01"),
        TranscriptSegment(start=9.5, end=15.0, text="Mình đề xuất giao anh Nam làm trưởng nhóm, hạn chót thứ 6 tuần sau.", speaker="SPEAKER_00"),
    ]
    job.speaker_names = {"SPEAKER_00": "Thiên", "SPEAKER_01": "Lan"}
    job.summary_markdown = """## Mục tiêu cuộc họp
Chốt kế hoạch công việc quý 4.

## Nội dung trao đổi chính
- Thảo luận kế hoạch Q4
- Phân công người phụ trách

## Quyết định
- Anh Nam làm trưởng nhóm dự án Q4

## Việc cần làm
| Việc cần làm | Người phụ trách | Hạn chót |
|---|---|---|
| Lập kế hoạch chi tiết Q4 | Nam | Thứ 6 tuần sau |
"""
    return job


if __name__ == "__main__":
    job = make_fake_job()
    out = export_to_docx(job, "/tmp/claude-0/test_output/bien_ban_test.docx")
    print(f"OK -> {out} ({out.stat().st_size} bytes)")
