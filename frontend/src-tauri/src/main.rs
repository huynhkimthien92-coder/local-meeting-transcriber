// Vỏ desktop Tauri: khởi động 2 sidecar ngầm khi app mở, và tắt khi app đóng
// — người dùng không bao giờ thấy terminal hay biết Python/Ollama chạy phía
// sau (xem docs/packaging-notes.md, Phương án 2 đã chọn):
//   1. "meeting-backend" — backend Python đóng gói (PyInstaller).
//   2. "ollama" — AI engine đóng gói kèm app (KHÔNG bắt người dùng tự cài
//      Ollama). Model AI (vài trăm MB - vài GB) vẫn tải lần đầu mở app,
//      nhưng qua UI onboarding có progress bar (xem app/api/server.py:
//      /api/onboarding/prepare-ai), không phải lệnh CLI.
use tauri::Manager;
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandEvent;

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let shell = app.shell();

            // Thư mục lưu model Ollama tải về — phải là thư mục CÓ QUYỀN GHI
            // (app data dir), không phải thư mục cài đặt app (thường chỉ đọc
            // trên Windows/macOS sau khi cài). Model tồn tại lại đây, không
            // đóng gói sẵn trong installer (xem docs/packaging-notes.md mục 3).
            let app_data_dir = app
                .path()
                .app_data_dir()
                .expect("Không lấy được thư mục dữ liệu app");
            let ollama_models_dir = app_data_dir.join("ollama-models");
            std::fs::create_dir_all(&ollama_models_dir)
                .expect("Không tạo được thư mục lưu model AI");

            // "ollama" là binary Ollama gốc (tải từ ollama.com/download, đổi
            // tên theo target triple), khai báo trong tauri.conf.json ->
            // bundle.externalBin, y hệt cách làm với meeting-backend.
            let (mut ollama_rx, _ollama_child) = shell
                .sidecar("ollama")
                .expect("Không tìm thấy sidecar ollama — xem docs/packaging-notes.md mục 2")
                .env("OLLAMA_HOST", "127.0.0.1:11434")
                .env("OLLAMA_MODELS", ollama_models_dir.to_string_lossy().to_string())
                .args(["serve"])
                .spawn()
                .expect("Không khởi động được AI engine local");

            tauri::async_runtime::spawn(async move {
                while let Some(event) = ollama_rx.recv().await {
                    match event {
                        CommandEvent::Stdout(line) => {
                            println!("[ai-engine] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Stderr(line) => {
                            eprintln!("[ai-engine:err] {}", String::from_utf8_lossy(&line));
                        }
                        _ => {}
                    }
                }
            });

            // "meeting-backend" là binary Python đã đóng gói (PyInstaller),
            // khai báo trong tauri.conf.json -> bundle.externalBin. Backend tự
            // chờ/retry khi gọi Ollama nên không cần đồng bộ thứ tự khởi động
            // ở đây — 2 sidecar khởi động song song là đủ.
            let (mut rx, _child) = shell
                .sidecar("meeting-backend")
                .expect("Không tìm thấy sidecar meeting-backend — chạy scripts/build_backend.sh trước")
                .spawn()
                .expect("Không khởi động được backend local");

            // Log output của backend ra console dev để debug; bản release
            // có thể ghi ra file log trong thư mục app data thay vì stdout.
            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(line) => {
                            println!("[backend] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Stderr(line) => {
                            eprintln!("[backend:err] {}", String::from_utf8_lossy(&line));
                        }
                        _ => {}
                    }
                }
            });

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("Lỗi khi chạy ứng dụng Tauri");
}
