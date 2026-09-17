# Local Meeting Transcriber (v2 — Desktop App cho người dùng thường)

> Pipeline local: Whisper chuyển audio thành text, LLM tóm tắt thành biên bản chuẩn — đóng gói thành ứng dụng desktop thân thiện, không cần chạy lệnh. Ưu tiên free/open-source.

**Thời gian dự kiến:** 6-7 tuần (thực tế hơn bản gốc 2-3 tuần vì có thêm UX + packaging)

## Mục tiêu gốc
Một công cụ chạy local nhận file âm thanh ghi âm dài của cuộc họp, biến thành biên bản cuộc họp chuyên nghiệp, tiêu chuẩn — **người dùng thông thường chỉ cần mở app, kéo file vào, chờ, và tải biên bản về. Không mở terminal, không gõ lệnh.**

_Thời hạn mong muốn: linh hoạt · Ưu tiên chi phí thấp / miễn phí_

## Những gì đã thay đổi so với bản gốc và tại sao

| Vấn đề ở bản gốc | Sửa trong v2 |
|---|---|
| UI/UX chỉ là 1 task cuối Giai đoạn 3, gộp chung với CLI | Tách thành Giai đoạn 0 riêng, làm trước khi code pipeline |
| Không có kế hoạch đóng gói app desktop | Thêm hẳn Giai đoạn 4: Packaging & Onboarding |
| Không xử lý việc tải model lần đầu (vài GB) | Thiết kế onboarding wizard tự chọn model theo cấu hình máy |
| Không có UI sửa lỗi diarization | Thêm task thiết kế UI gán lại người nói bằng kéo-thả |
| Không có xử lý file dài chạy nền | Thêm task background processing + thông báo hoàn tất |
| Timeline 2-3 tuần không thực tế | Nâng lên 6-7 tuần, chia rõ theo giai đoạn |

## Giai đoạn 0: UX Research & Thiết kế trải nghiệm (4 ngày)

**Mục tiêu:** Thiết kế toàn bộ hành trình người dùng trước khi viết code — tránh việc UI trở thành lớp vỏ dán vào sau.

- [ ] **UX Researcher** _(Design)_ — Xác định persona người dùng và luồng sử dụng chính
  - Đầu ra: User flow (mở app → nạp file/ghi âm trực tiếp → xử lý → xem/sửa kết quả → xuất file)
  - Đầu ra: Danh sách pain point cần giải quyết (chờ lâu, sai tên người nói, không biết máy có đủ mạnh không)
  - Hồ sơ: https://github.com/msitarzewski/agency-agents/blob/main/design/design-ux-researcher.md
  - Prompt kích hoạt:
    ```
    Kích hoạt UX Researcher.

    Bối cảnh dự án: một ứng dụng desktop chạy local nhận file âm thanh ghi âm dài của cuộc họp biến thành biên bản cuộc họp chuyên nghiệp, tiêu chuẩn — dành cho người dùng thông thường, không cần chạy lệnh
    Giai đoạn: UX Research & Thiết kế trải nghiệm — Xác định persona và luồng sử dụng chính
    Vai trò của bạn: Xác định persona người dùng và luồng sử dụng chính

    Hãy thực hiện:
    - User flow đầy đủ
    - Danh sách pain point cần giải quyết
    ```

- [ ] **UI Designer** _(Design)_ — Wireframe và mockup giao diện chính
  - Đầu ra: Màn hình onboarding (chọn model, tải model, kiểm tra cấu hình máy)
  - Đầu ra: Màn hình xử lý (thanh tiến trình, ước tính thời gian còn lại)
  - Đầu ra: Màn hình kết quả (transcript có timestamp, gán tên người nói kéo-thả, nút xuất DOCX/PDF)
  - Đầu ra: Màn hình thư viện biên bản cũ (tìm kiếm, mở lại)
  - Hồ sơ: https://github.com/msitarzewski/agency-agents/blob/main/design/design-ui-designer.md
  - Prompt kích hoạt:
    ```
    Kích hoạt UI Designer.

    Bối cảnh dự án: một ứng dụng desktop chạy local nhận file âm thanh ghi âm dài của cuộc họp biến thành biên bản cuộc họp chuyên nghiệp, tiêu chuẩn — dành cho người dùng thông thường, không cần chạy lệnh
    Giai đoạn: UX Research & Thiết kế trải nghiệm — Wireframe và mockup giao diện chính
    Vai trò của bạn: Wireframe và mockup giao diện chính

    Hãy thực hiện:
    - Wireframe cho các màn hình: onboarding, xử lý, kết quả, thư viện
    ```

## Giai đoạn 1: Kiến trúc Pipeline & Lựa chọn Stack (3 ngày)

**Mục tiêu:** Chọn stack miễn phí, thiết kế luồng xử lý end-to-end, và **quyết định công nghệ đóng gói app desktop ngay từ đầu** (ảnh hưởng lớn đến cách viết pipeline).

- [ ] **Software Architect** _(Engineering)_ — Thiết kế kiến trúc pipeline local Whisper+LLM, tích hợp app desktop
  - Đầu ra: Sơ đồ pipeline (audio → Whisper → diarization → LLM tóm tắt → export)
  - Đầu ra: Quyết định stack: Electron hay Tauri (Tauri nhẹ hơn, phù hợp app AI local vì binary nhỏ hơn); Python backend chạy như sidecar process
  - Hồ sơ: https://github.com/msitarzewski/agency-agents/blob/main/engineering/engineering-software-architect.md
  - Prompt kích hoạt:
    ```
    Kích hoạt Software Architect.

    Bối cảnh dự án: một ứng dụng desktop chạy local nhận file âm thanh ghi âm dài của cuộc họp biến thành biên bản cuộc họp chuyên nghiệp, tiêu chuẩn — dành cho người dùng thông thường, không cần chạy lệnh
    Giai đoạn: Kiến trúc Pipeline & Lựa chọn Stack — Chọn stack miễn phí, thiết kế luồng xử lý end-to-end, quyết định công nghệ đóng gói app desktop
    Vai trò của bạn: Thiết kế kiến trúc pipeline local Whisper+LLM, tích hợp app desktop

    Hãy thực hiện:
    - Sơ đồ pipeline
    - Quyết định stack (Electron vs Tauri, Python sidecar)
    ```

- [ ] **Voice AI Integration Engineer** _(Engineering)_ — Đánh giá Whisper model size vs. độ chính xác vs. yêu cầu phần cứng
  - Đầu ra: Bảng so sánh Whisper tiers (tiny/base/small/medium) kèm RAM/thời gian xử lý ước tính
  - Đầu ra: Cấu hình diarization (pyannote hoặc whisperX) + kế hoạch fallback khi độ chính xác thấp
  - Hồ sơ: https://github.com/msitarzewski/agency-agents/blob/main/engineering/engineering-voice-ai-integration-engineer.md
  - Prompt kích hoạt:
    ```
    Kích hoạt Voice AI Integration Engineer.

    Bối cảnh dự án: một ứng dụng desktop chạy local nhận file âm thanh ghi âm dài của cuộc họp biến thành biên bản cuộc họp chuyên nghiệp, tiêu chuẩn — dành cho người dùng thông thường, không cần chạy lệnh
    Giai đoạn: Kiến trúc Pipeline & Lựa chọn Stack — Đánh giá Whisper model size vs. độ chính xác vs. yêu cầu phần cứng
    Vai trò của bạn: Đánh giá Whisper model size vs. độ chính xác vs. yêu cầu phần cứng

    Hãy thực hiện:
    - Bảng so sánh Whisper tiers kèm RAM/thời gian ước tính
    - Cấu hình diarization + kế hoạch fallback
    ```

## Giai đoạn 2: Xây dựng Core Pipeline (1.5 tuần)

**Mục tiêu:** Cài đặt Whisper, diarization, và LLM tóm tắt offline — viết như module có thể gọi từ app, không phải script CLI độc lập.

- [ ] **Rapid Prototyper** _(Engineering)_ — Build module Python xử lý Whisper + Ollama local, chạy nền không block UI
  - Đầu ra: Module xử lý audio dạng API nội bộ (nhận file, trả tiến trình %, trả kết quả)
  - Đầu ra: Transcript thô có speaker + timestamp
  - Hồ sơ: https://github.com/msitarzewski/agency-agents/blob/main/engineering/engineering-rapid-prototyper.md
  - Prompt kích hoạt:
    ```
    Kích hoạt Rapid Prototyper.

    Bối cảnh dự án: một ứng dụng desktop chạy local nhận file âm thanh ghi âm dài của cuộc họp biến thành biên bản cuộc họp chuyên nghiệp, tiêu chuẩn — dành cho người dùng thông thường, không cần chạy lệnh
    Giai đoạn: Xây dựng Core Pipeline — Cài đặt Whisper, diarization, LLM tóm tắt offline, chạy nền không block UI
    Vai trò của bạn: Build module Python xử lý Whisper + Ollama local, chạy nền không block UI

    Hãy thực hiện:
    - Module xử lý audio dạng API nội bộ (nhận file, trả tiến trình %, trả kết quả)
    - Transcript thô có speaker + timestamp
    ```

- [ ] **Prompt Engineer** _(Engineering)_ — Thiết kế prompt tóm tắt biên bản chuẩn miễn phí
  - Đầu ra: Prompt template biên bản (mục tiêu cuộc họp, quyết định, việc cần làm, người phụ trách)
  - Đầu ra: Output mẫu
  - Hồ sơ: https://github.com/msitarzewski/agency-agents/blob/main/engineering/engineering-prompt-engineer.md
  - Prompt kích hoạt:
    ```
    Kích hoạt Prompt Engineer.

    Bối cảnh dự án: một ứng dụng desktop chạy local nhận file âm thanh ghi âm dài của cuộc họp biến thành biên bản cuộc họp chuyên nghiệp, tiêu chuẩn — dành cho người dùng thông thường, không cần chạy lệnh
    Giai đoạn: Xây dựng Core Pipeline — Thiết kế prompt tóm tắt biên bản chuẩn miễn phí
    Vai trò của bạn: Thiết kế prompt tóm tắt biên bản chuẩn miễn phí

    Hãy thực hiện:
    - Prompt template biên bản (mục tiêu, quyết định, việc cần làm, người phụ trách)
    - Output mẫu
    ```

- [ ] **AI Engineer** _(Engineering)_ — Tích hợp Ollama/LLM local để sinh biên bản, tự chọn model theo RAM máy
  - Đầu ra: Module sinh biên bản
  - Đầu ra: Logic tự phát hiện RAM/CPU và đề xuất model phù hợp (không để app crash im lặng trên máy yếu)
  - Hồ sơ: https://github.com/msitarzewski/agency-agents/blob/main/engineering/engineering-ai-engineer.md
  - Prompt kích hoạt:
    ```
    Kích hoạt AI Engineer.

    Bối cảnh dự án: một ứng dụng desktop chạy local nhận file âm thanh ghi âm dài của cuộc họp biến thành biên bản cuộc họp chuyên nghiệp, tiêu chuẩn — dành cho người dùng thông thường, không cần chạy lệnh
    Giai đoạn: Xây dựng Core Pipeline — Tích hợp Ollama/LLM local, tự chọn model theo RAM máy
    Vai trò của bạn: Tích hợp Ollama/LLM local để sinh biên bản, tự chọn model theo RAM máy

    Hãy thực hiện:
    - Module sinh biên bản
    - Logic tự phát hiện RAM/CPU và đề xuất model phù hợp
    ```

## Giai đoạn 3: Xây dựng App Desktop theo thiết kế UX (1.5 tuần)

**Mục tiêu:** Build giao diện thật theo wireframe ở Giai đoạn 0 — không phải "web local đơn giản" ngẫu hứng.

- [ ] **Frontend Developer** _(Engineering)_ — Build giao diện desktop theo mockup, kết nối với module pipeline
  - Đầu ra: Màn hình kéo-thả file / ghi âm trực tiếp
  - Đầu ra: Thanh tiến trình xử lý thời gian thực + thông báo hệ thống khi xong (để user làm việc khác trong lúc chờ)
  - Đầu ra: Giao diện sửa transcript và gán lại tên người nói bằng kéo-thả
  - Đầu ra: Thư viện biên bản cũ có tìm kiếm
  - Hồ sơ: https://github.com/msitarzewski/agency-agents/blob/main/engineering/engineering-frontend-developer.md
  - Prompt kích hoạt:
    ```
    Kích hoạt Frontend Developer.

    Bối cảnh dự án: một ứng dụng desktop chạy local nhận file âm thanh ghi âm dài của cuộc họp biến thành biên bản cuộc họp chuyên nghiệp, tiêu chuẩn — dành cho người dùng thông thường, không cần chạy lệnh
    Giai đoạn: Xây dựng App Desktop theo thiết kế UX — Build giao diện thật theo mockup, kết nối với module pipeline
    Vai trò của bạn: Build giao diện desktop theo mockup, kết nối với module pipeline

    Hãy thực hiện:
    - Màn hình kéo-thả file / ghi âm trực tiếp
    - Thanh tiến trình xử lý thời gian thực + thông báo hệ thống khi xong
    - Giao diện sửa transcript và gán lại tên người nói bằng kéo-thả
    - Thư viện biên bản cũ có tìm kiếm
    ```

- [ ] **Document Generator** _(Specialized)_ — Export biên bản ra DOCX/PDF theo template chuẩn
  - Đầu ra: Template biên bản DOCX chuyên nghiệp
  - Đầu ra: Nút xuất trực tiếp từ giao diện (không qua script riêng)
  - Hồ sơ: https://github.com/msitarzewski/agency-agents/blob/main/specialized/specialized-document-generator.md
  - Prompt kích hoạt:
    ```
    Kích hoạt Document Generator.

    Bối cảnh dự án: một ứng dụng desktop chạy local nhận file âm thanh ghi âm dài của cuộc họp biến thành biên bản cuộc họp chuyên nghiệp, tiêu chuẩn — dành cho người dùng thông thường, không cần chạy lệnh
    Giai đoạn: Xây dựng App Desktop theo thiết kế UX — Export biên bản ra DOCX/PDF theo template chuẩn
    Vai trò của bạn: Export biên bản ra DOCX/PDF theo template chuẩn

    Hãy thực hiện:
    - Template biên bản DOCX chuyên nghiệp
    - Nút xuất trực tiếp từ giao diện
    ```

## Giai đoạn 4: Packaging, Onboarding & Phân phối (1 tuần)

**Mục tiêu:** Đây là giai đoạn *hoàn toàn thiếu* ở bản gốc — biến pipeline thành thứ người dùng thường cài được bằng vài cú click.

- [ ] **DevOps Automator** _(Engineering)_ — Đóng gói app thành installer cho Windows/macOS
  - Đầu ra: File cài đặt .exe/.dmg, không yêu cầu Python/Ollama cài sẵn thủ công
  - Đầu ra: Cơ chế tự động tải model AI lần đầu chạy (kèm thanh tiến trình tải, cho phép tạm dừng/tiếp tục)
  - Hồ sơ: https://github.com/msitarzewski/agency-agents/blob/main/engineering/engineering-devops-automator.md
  - Prompt kích hoạt:
    ```
    Kích hoạt DevOps Automator.

    Bối cảnh dự án: một ứng dụng desktop chạy local nhận file âm thanh ghi âm dài của cuộc họp biến thành biên bản cuộc họp chuyên nghiệp, tiêu chuẩn — dành cho người dùng thông thường, không cần chạy lệnh
    Giai đoạn: Packaging, Onboarding & Phân phối — Đóng gói app thành installer cho Windows/macOS
    Vai trò của bạn: Đóng gói app thành installer cho Windows/macOS

    Hãy thực hiện:
    - File cài đặt .exe/.dmg, không yêu cầu Python/Ollama cài sẵn thủ công
    - Cơ chế tự động tải model AI lần đầu chạy
    ```

- [ ] **UI Designer** _(Design)_ — Thiết kế màn hình onboarding lần đầu chạy app
  - Đầu ra: Wizard 3 bước: kiểm tra cấu hình máy → chọn/tải model phù hợp → hướng dẫn nhanh cách dùng
  - Hồ sơ: https://github.com/msitarzewski/agency-agents/blob/main/design/design-ui-designer.md
  - Prompt kích hoạt:
    ```
    Kích hoạt UI Designer.

    Bối cảnh dự án: một ứng dụng desktop chạy local nhận file âm thanh ghi âm dài của cuộc họp biến thành biên bản cuộc họp chuyên nghiệp, tiêu chuẩn — dành cho người dùng thông thường, không cần chạy lệnh
    Giai đoạn: Packaging, Onboarding & Phân phối — Thiết kế màn hình onboarding lần đầu chạy app
    Vai trò của bạn: Thiết kế màn hình onboarding lần đầu chạy app

    Hãy thực hiện:
    - Wizard 3 bước: kiểm tra cấu hình máy → chọn/tải model phù hợp → hướng dẫn nhanh cách dùng
    ```

## Giai đoạn 5: QA & Xử lý rủi ro (4 ngày)

**Mục tiêu:** Kiểm thử với file dài thật, đảm bảo app không "đứng hình" hay crash im lặng.

- [ ] **Rapid Prototyper** _(Engineering)_ — Test với file ghi âm 1-2 tiếng, nhiều người nói
  - Đầu ra: Báo cáo hiệu năng theo cấu hình máy khác nhau (máy yếu/trung bình/mạnh)
  - Đầu ra: Xử lý lỗi khi hết RAM, khi audio chất lượng kém, khi mất điện giữa chừng (resume xử lý)
  - Hồ sơ: https://github.com/msitarzewski/agency-agents/blob/main/engineering/engineering-rapid-prototyper.md
  - Prompt kích hoạt:
    ```
    Kích hoạt Rapid Prototyper.

    Bối cảnh dự án: một ứng dụng desktop chạy local nhận file âm thanh ghi âm dài của cuộc họp biến thành biên bản cuộc họp chuyên nghiệp, tiêu chuẩn — dành cho người dùng thông thường, không cần chạy lệnh
    Giai đoạn: QA & Xử lý rủi ro — Test với file ghi âm dài, nhiều người nói, đảm bảo app không đứng hình hay crash im lặng
    Vai trò của bạn: Test với file ghi âm 1-2 tiếng, nhiều người nói

    Hãy thực hiện:
    - Báo cáo hiệu năng theo cấu hình máy khác nhau
    - Xử lý lỗi khi hết RAM, audio kém, mất điện giữa chừng (resume xử lý)
    ```

## Rủi ro chính cần lưu ý (đã cập nhật)

- Whisper local chậm trên máy không có GPU → cần chọn model tier tự động, cảnh báo thời gian ước tính trước khi bắt đầu
- LLM local (Ollama) cần RAM 8GB+ → app phải phát hiện và tự hạ cấp model, không được crash im lặng
- Diarization speaker miễn phí độ chính xác thấp với nhiều người → **bắt buộc** có UI sửa tay, không thể chỉ dựa vào tự động
- Đóng gói app AI local đa nền tảng (Windows/macOS) phức tạp và tốn thời gian hơn ước tính ban đầu — nên ưu tiên 1 nền tảng trước (gợi ý: Windows, vì môi trường làm việc phổ biến ở VN)
- Kích thước installer lớn (model vài GB) → cân nhắc tải model sau khi cài thay vì đóng gói sẵn trong installer

---
_Cập nhật bởi phân tích thẳng thắn dựa trên bản gốc "Bản Vẽ Sản Xuất" · 17/9/2026_
