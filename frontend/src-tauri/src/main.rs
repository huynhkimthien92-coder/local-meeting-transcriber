// Vỏ desktop Tauri: khởi động 2 sidecar ngầm khi app mở, và tắt khi app đóng
// — người dùng không bao giờ thấy terminal hay biết Python/Ollama chạy phía
// sau (xem docs/packaging-notes.md, Phương án 2 đã chọn):
//   1. "meeting-backend" — backend Python đóng gói (PyInstaller).
//   2. "ollama" — AI engine đóng gói kèm app (KHÔNG bắt người dùng tự cài
//      Ollama). Model AI (vài trăm MB - vài GB) vẫn tải lần đầu mở app,
//      nhưng qua UI onboarding có progress bar (xem app/api/server.py:
//      /api/onboarding/prepare-ai), không phải lệnh CLI.
use std::sync::Mutex;
use tauri::Manager;
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::process::CommandEvent;
use tauri_plugin_shell::ShellExt;

// Giữ lại 2 process con (Ollama + backend) để có thể tắt hẳn chúng khi app
// đóng. Nếu không làm việc này, đóng cửa sổ app trên Windows đôi khi KHÔNG
// tắt luôn 2 tiến trình con — chúng vẫn chạy ngầm, chiếm sẵn cổng
// (127.0.0.1:11434 và :8756) -> lần mở app SAU đó báo lỗi
// "Only one usage of each socket address..." vì cổng đã bị chiếm bởi chính
// lần chạy trước còn sót lại. Đây là lỗi thật đã gặp, không phải giả định.
struct SidecarChildren {
    ollama: Mutex<Option<CommandChild>>,
    backend: Mutex<Option<CommandChild>>,
}

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
            //
            // Dùng cổng RIÊNG (39217) thay vì cổng mặc định 11434 của Ollama:
            // nhiều máy người dùng (đặc biệt dân kỹ thuật) có thể đã tự cài
            // sẵn Ollama chạy nền ở cổng 11434 -> nếu dùng chung cổng đó,
            // sidecar Ollama đóng gói kèm app sẽ không bind được cổng và lỗi
            // y như log Thiên gặp. Đổi sang cổng riêng để không bao giờ đụng
            // độ với bất kỳ cài đặt Ollama nào khác trên máy.
            //
            // OLLAMA_LIBRARY_PATH: "ollama.exe" chỉ là vỏ điều khiển — phần
            // thực sự chạy model (llama-server + các thư viện backend CPU/
            // GPU) nằm trong thư mục con "lib/ollama/" đi kèm khi tải Ollama
            // chính thức. externalBin của Tauri chỉ mang được đúng 1 file
            // thực thi, không mang theo thư mục "lib" này -> phải đóng gói
            // "lib/" riêng qua bundle.resources (xem tauri.conf.json) rồi trỏ
            // OLLAMA_LIBRARY_PATH vào đúng thư mục resource đó, để Ollama tìm
            // thấy "lib/ollama/llama-server(.exe)" lúc chạy thật (lỗi thật đã
            // gặp: "llama-server binary not found").
            let resource_dir = app
                .path()
                .resource_dir()
                .expect("Không lấy được thư mục resources của app");
            let (mut ollama_rx, ollama_child) = shell
                .sidecar("ollama")
                .expect("Không tìm thấy sidecar ollama — xem docs/packaging-notes.md mục 2")
                .env("OLLAMA_HOST", "127.0.0.1:39217")
                .env("OLLAMA_LIBRARY_PATH", resource_dir.to_string_lossy().to_string())
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
            let (mut rx, backend_child) = shell
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

            app.manage(SidecarChildren {
                ollama: Mutex::new(Some(ollama_child)),
                backend: Mutex::new(Some(backend_child)),
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Lỗi khi chạy ứng dụng Tauri")
        .run(|app_handle, event| {
            // Tắt hẳn 2 sidecar khi app thoát (đóng cửa sổ cuối cùng hoặc
            // thoát hẳn) -> tránh để sót tiến trình ngầm chiếm cổng cho lần
            // mở app kế tiếp (xem giải thích ở SidecarChildren phía trên).
            if let tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit = event {
                if let Some(children) = app_handle.try_state::<SidecarChildren>() {
                    if let Ok(mut guard) = children.ollama.lock() {
                        if let Some(child) = guard.take() {
                            let _ = child.kill();
                        }
                    }
                    if let Ok(mut guard) = children.backend.lock() {
                        if let Some(child) = guard.take() {
                            let _ = child.kill();
                        }
                    }
                }
            }
        });
}
