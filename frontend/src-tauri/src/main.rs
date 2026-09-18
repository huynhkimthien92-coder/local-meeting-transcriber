// Vỏ desktop Tauri: khởi động 2 sidecar ngầm khi app mở, và tắt khi app đóng
// — người dùng không bao giờ thấy terminal hay biết Python/Ollama chạy phía
// sau (xem docs/packaging-notes.md, Phương án 2 đã chọn):
//   1. "meeting-backend" — backend Python đóng gói (PyInstaller).
//   2. "ollama" — AI engine đóng gói kèm app (KHÔNG bắt người dùng tự cài
//      Ollama). Model AI (vài trăm MB - vài GB) vẫn tải lần đầu mở app,
//      nhưng qua UI onboarding có progress bar (xem app/api/server.py:
//      /api/onboarding/prepare-ai), không phải lệnh CLI.
use std::fs;
use std::path::PathBuf;
use std::sync::Mutex;
use tauri::Manager;
use tauri_plugin_dialog::DialogExt;
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

// QUAN TRỌNG: app_data_dir() của Tauri LUÔN nằm dưới hồ sơ người dùng
// Windows (C:\Users\<tên>\AppData\Roaming\...), KHÔNG PHỤ THUỘC vào việc
// người dùng cài app ở ổ nào (lỗi thật đã gặp: cài app ở ổ D: nhưng model
// AI Ollama vẫn tải về ổ C: rồi báo hết dung lượng "not enough space on
// disk") -- đây là quy ước chung của Windows/macOS/Linux, không phải bug
// của app, nhưng gây khó cho người dùng có ổ C: nhỏ.
//
// Giải pháp: dùng 1 file "đánh dấu" nhỏ (data-location.txt, vài chục byte,
// vẫn nằm ở app_data_dir -- không đáng kể) LƯU ĐƯỜNG DẪN THẬT mà người dùng
// chọn qua màn hình Cài đặt. Nếu file này tồn tại và có nội dung, dùng
// đường dẫn đó làm nơi lưu model AI + dữ liệu backend; nếu không, mặc định
// vẫn dùng app_data_dir như cũ (không phá vỡ hành vi hiện tại).
fn data_marker_path(app: &tauri::AppHandle) -> PathBuf {
    let base = app
        .path()
        .app_data_dir()
        .expect("Không lấy được thư mục dữ liệu app");
    base.join("data-location.txt")
}

fn resolve_data_root(app: &tauri::AppHandle) -> PathBuf {
    let marker = data_marker_path(app);
    if let Ok(content) = fs::read_to_string(&marker) {
        let trimmed = content.trim();
        if !trimmed.is_empty() {
            return PathBuf::from(trimmed);
        }
    }
    app.path()
        .app_data_dir()
        .expect("Không lấy được thư mục dữ liệu app")
}

/// Cho màn hình Cài đặt hiển thị nơi đang lưu model AI + dữ liệu app.
#[tauri::command]
fn get_data_dir(app: tauri::AppHandle) -> String {
    resolve_data_root(&app).to_string_lossy().to_string()
}

/// Mở hộp thoại chọn thư mục hệ điều hành, lưu lựa chọn vào file đánh dấu.
/// CHỈ áp dụng cho lần khởi động app TIẾP THEO (2 sidecar đã khởi động sẵn
/// với đường dẫn cũ lúc app đang mở) -- frontend nhắc người dùng khởi động
/// lại app sau khi đổi. Dữ liệu/model đã tải ở vị trí CŨ không tự động di
/// chuyển sang chỗ mới (tránh rủi ro copy nhầm/hỏng file nhiều GB) -- người
/// dùng cần tự chuyển tay nếu muốn giữ lại, hoặc chấp nhận tải lại model.
#[tauri::command]
fn pick_data_dir(app: tauri::AppHandle) -> Option<String> {
    let folder = app.dialog().file().blocking_pick_folder()?;
    // .into_path() thay vì .to_string() -- chuyển đúng về PathBuf hệ điều
    // hành (tránh trường hợp FilePath là dạng URL bị format khác đường dẫn
    // thường), rồi mới đổi ra chuỗi để ghi vào file đánh dấu.
    let path_str = folder.into_path().ok()?.to_string_lossy().to_string();
    let marker = data_marker_path(&app);
    if let Some(parent) = marker.parent() {
        let _ = fs::create_dir_all(parent);
    }
    fs::write(&marker, &path_str).ok()?;
    Some(path_str)
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![get_data_dir, pick_data_dir])
        .setup(|app| {
            let shell = app.shell();

            // Thư mục GỐC lưu dữ liệu (model Ollama + dữ liệu backend) --
            // mặc định là app_data_dir (C:...), nhưng người dùng có thể đổi
            // sang ổ khác qua màn hình Cài đặt (xem resolve_data_root ở trên,
            // lỗi thật đã gặp: ổ C: hết dung lượng vì model AI + backend
            // buộc phải nằm ở AppData bất kể cài app ở ổ nào).
            let data_root = resolve_data_root(app.handle());

            // Thư mục lưu model Ollama tải về — phải là thư mục CÓ QUYỀN GHI
            // và ỔN ĐỊNH, không phải thư mục cài đặt app (thường chỉ đọc
            // trên Windows/macOS sau khi cài). Model tồn tại lại đây, không
            // đóng gói sẵn trong installer (xem docs/packaging-notes.md mục 3).
            let ollama_models_dir = data_root.join("ollama-models");
            std::fs::create_dir_all(&ollama_models_dir)
                .expect("Không tạo được thư mục lưu model AI");

            // Thư mục dữ liệu của BACKEND (job đã lưu, file ghi âm upload,
            // file .docx xuất ra, settings.json) -- cùng lý do với
            // ollama_models_dir ở trên: phải là thư mục CÓ QUYỀN GHI và ỔN
            // ĐỊNH, không phải nơi backend.exe được giải nén ra chạy.
            // Backend (xem backend/app/paths.py) đọc biến môi trường
            // MEETING_DATA_DIR này; nếu thiếu, backend tự rơi về đường dẫn
            // cạnh file code -- mà với PyInstaller --onefile đó là 1 thư mục
            // TẠM bị xoá mỗi lần tắt app -> lỗi thật đã gặp: mất hết biên
            // bản đã lưu + cài đặt sau khi tắt/mở lại app.
            let backend_data_dir = data_root.join("backend-data");
            std::fs::create_dir_all(&backend_data_dir)
                .expect("Không tạo được thư mục dữ liệu backend");

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
            // PYTHONUTF8=1: ép Python luôn coi UTF-8 là bảng mã mặc định cho
            // MỌI thao tác đọc/ghi file và stdout/stderr, bất kể bảng mã hệ
            // thống Windows đang đặt là gì (thường là cp1252, không có tiếng
            // Việt). Đây là lớp bảo vệ chung, phòng những chỗ đọc/ghi text
            // chưa được chỉ định encoding="utf-8" tường minh trong code
            // Python (lỗi thật đã gặp trên Windows: "UnicodeEncodeError:
            // 'charmap' codec can't encode character..." khi lưu job có
            // tiêu đề/nội dung tiếng Việt có dấu).
            let (mut rx, backend_child) = shell
                .sidecar("meeting-backend")
                .expect("Không tìm thấy sidecar meeting-backend — chạy scripts/build_backend.sh trước")
                .env("PYTHONUTF8", "1")
                .env("MEETING_DATA_DIR", backend_data_dir.to_string_lossy().to_string())
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
