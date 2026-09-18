// Toàn bộ logic frontend — vanilla JS, không dùng framework để giữ app
// nhẹ (quan trọng vì mục tiêu là chạy tốt cả trên máy yếu, theo đúng rủi
// ro "máy văn phòng cấu hình thấp" đã nêu trong blueprint).

const API_BASE = "http://127.0.0.1:8756";

const state = {
  currentJobId: null,
  currentJob: null,
  selectedFile: null,
  settings: { diarization_enabled: false, hf_token_set: false },
};

// ---------- Điều hướng giữa các màn hình ----------
function showView(viewId) {
  document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
  document.getElementById(viewId).classList.remove("hidden");
}

document.getElementById("nav-home").addEventListener("click", () => {
  setActiveNav("nav-home");
  showView("view-home");
});
document.getElementById("nav-library").addEventListener("click", () => {
  setActiveNav("nav-library");
  showView("view-library");
  loadLibrary();
});
document.getElementById("nav-settings").addEventListener("click", () => {
  setActiveNav("nav-settings");
  showView("view-settings");
  loadSettings();
});

function setActiveNav(id) {
  document.querySelectorAll(".nav-btn").forEach((b) => b.classList.remove("active"));
  document.getElementById(id).classList.add("active");
}

// ---------- Onboarding: kiểm tra cấu hình máy ----------
async function runOnboardingCheck() {
  try {
    const res = await fetch(`${API_BASE}/api/hardware`);
    const data = await res.json();
    document.getElementById("hw-check-status").classList.add("hidden");
    document.getElementById("hw-result").classList.remove("hidden");

    document.getElementById("hw-ram").textContent = `${data.hardware.ram_gb} GB`;
    document.getElementById("hw-cpu").textContent = `${data.hardware.cpu_cores} nhân`;
    document.getElementById("hw-gpu").textContent = data.hardware.has_gpu
      ? data.hardware.gpu_name || "Có"
      : "Không có";

    document.getElementById("hw-tier").textContent = data.recommendation.tier_label;

    if (data.recommendation.warning) {
      const box = document.getElementById("hw-warning");
      box.textContent = "⚠️ " + data.recommendation.warning;
      box.classList.remove("hidden");
    }
  } catch (err) {
    document.getElementById("hw-check-status").textContent =
      "Không kết nối được tới bộ xử lý local. Thử khởi động lại ứng dụng.";
  }
}

document.getElementById("btn-onboarding-continue").addEventListener("click", () => {
  document.getElementById("hw-result").classList.add("hidden");
  prepareAiThenEnterApp();
});

// ---------- Onboarding bước 2: chuẩn bị AI ngầm (tải model tóm tắt nếu
// chưa có) — người dùng chỉ thấy "đang chuẩn bị", không biết Ollama tồn
// tại (xem app/pipeline/ollama_manager.py). Chạy 1 lần duy nhất thực sự
// (model tải xong nằm lại trên đĩa), nhưng vẫn kiểm tra lại mỗi lần mở
// app phòng khi lần trước bị đóng ứng dụng giữa chừng lúc đang tải. ---
async function prepareAiThenEnterApp() {
  const panel = document.getElementById("ai-prep");
  const bar = document.getElementById("ai-prep-bar");
  const status = document.getElementById("ai-prep-status");
  panel.classList.remove("hidden");

  await new Promise((resolve) => {
    function connect() {
      const es = new EventSource(`${API_BASE}/api/onboarding/prepare-ai`);
      es.onmessage = (ev) => {
        const data = JSON.parse(ev.data);
        bar.style.width = `${data.percent}%`;
        status.textContent = data.error
          ? `⚠️ ${data.message}`
          : (data.message || "Đang chuẩn bị...");
        if (data.done) {
          es.close();
          resolve();
        }
      };
      es.onerror = () => {
        // Sidecar AI có thể chưa kịp khởi động (đúng lúc mở app) — thử lại
        // sau 2 giây thay vì chặn người dùng đứng hình ở màn hình chờ.
        es.close();
        status.textContent = "Đang thử kết nối lại...";
        setTimeout(connect, 2000);
      };
    }
    connect();
  });

  localStorage.setItem("onboarding_done", "1");
  panel.classList.add("hidden");
  setActiveNav("nav-home");
  showView("view-home");
}

// ---------- Màn hình chính: chọn / kéo-thả file ----------
const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("file-input");

document.getElementById("btn-choose-file").addEventListener("click", () => fileInput.click());

fileInput.addEventListener("change", (e) => {
  if (e.target.files.length) handleFileSelected(e.target.files[0]);
});

["dragenter", "dragover"].forEach((evt) =>
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropzone.classList.add("drag-over");
  })
);
["dragleave", "drop"].forEach((evt) =>
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropzone.classList.remove("drag-over");
  })
);
dropzone.addEventListener("drop", (e) => {
  const file = e.dataTransfer.files[0];
  if (file) handleFileSelected(file);
});

async function handleFileSelected(file) {
  state.selectedFile = file;
  document.getElementById("btn-start").classList.remove("hidden");
  renderDiarizationStatusNote();

  const box = document.getElementById("estimate-box");
  box.classList.remove("hidden");
  box.textContent = "Đang ước tính thời gian xử lý...";

  // Ước tính thời lượng audio ở phía trình duyệt bằng thẻ <audio>, để gọi
  // /api/estimate và cho người dùng biết TRƯỚC khi bắt đầu — thay vì để
  // họ bấm xong rồi mới biết phải chờ bao lâu.
  const durationSec = await getAudioDuration(file);
  try {
    const res = await fetch(`${API_BASE}/api/estimate?duration_seconds=${durationSec}`);
    const data = await res.json();
    const mins = Math.round(data.estimated_seconds / 60);
    box.textContent = `File dài khoảng ${Math.round(durationSec / 60)} phút. Ước tính xử lý mất khoảng ${mins} phút.`;
  } catch {
    box.textContent = `File dài khoảng ${Math.round(durationSec / 60)} phút.`;
  }
}

function getAudioDuration(file) {
  return new Promise((resolve) => {
    const audio = document.createElement("audio");
    audio.preload = "metadata";
    audio.onloadedmetadata = () => resolve(audio.duration || 0);
    audio.onerror = () => resolve(0);
    audio.src = URL.createObjectURL(file);
  });
}

document.getElementById("btn-start").addEventListener("click", startProcessing);

async function startProcessing() {
  if (!state.selectedFile) return;

  const title = document.getElementById("meeting-title").value || "Cuộc họp chưa đặt tên";
  const form = new FormData();
  form.append("file", state.selectedFile);
  form.append("title", title);

  showView("view-processing");
  updateProgress(0, "queued", "Đang tải file lên...");

  const res = await fetch(`${API_BASE}/api/jobs`, { method: "POST", body: form });
  if (!res.ok) {
    updateProgress(0, "error", "Không tạo được job xử lý. Kiểm tra backend đã chạy chưa.");
    return;
  }
  const data = await res.json();
  state.currentJobId = data.job_id;
  subscribeToProgress(data.job_id);
}

function subscribeToProgress(jobId) {
  const evtSource = new EventSource(`${API_BASE}/api/jobs/${jobId}/events`);
  evtSource.onmessage = (e) => {
    const event = JSON.parse(e.data);
    updateProgress(event.percent, event.stage, event.message);
    if (event.stage === "done") {
      evtSource.close();
      loadResults(jobId);
    }
    if (event.stage === "error") {
      evtSource.close();
    }
  };
  evtSource.onerror = () => {
    evtSource.close();
  };
}

const STAGE_LABELS = {
  queued: "Đang chờ...",
  loading_model: "Đang nạp model...",
  transcribing: "Đang nhận diện lời nói",
  diarizing: "Đang nhận diện người nói",
  summarizing: "Đang sinh biên bản",
  done: "Hoàn tất",
  error: "Có lỗi xảy ra",
};

function updateProgress(pct, stage, message) {
  document.getElementById("progress-bar").style.width = `${pct}%`;
  document.getElementById("progress-pct").textContent = `${Math.round(pct)}%`;
  document.getElementById("processing-title").textContent = STAGE_LABELS[stage] || "Đang xử lý...";
  document.getElementById("progress-message").textContent = message;
}

// ---------- Màn hình kết quả ----------
async function loadResults(jobId) {
  // QUAN TRỌNG: bọc try/catch -- trước đây nếu fetch lỗi (vd job.json hỏng,
  // backend chưa kịp khởi động), lỗi sẽ âm thầm biến mất (unhandled promise
  // rejection) và màn hình KHÔNG chuyển sang view-results, KHÔNG báo gì cho
  // người dùng biết -- trông y hệt "bấm không mở được".
  try {
    const res = await fetch(`${API_BASE}/api/jobs/${jobId}`);
    if (!res.ok) {
      throw new Error(`Server trả về lỗi ${res.status}`);
    }
    const job = await res.json();
    state.currentJob = job;
    renderResults(job);
    showView("view-results");
  } catch (err) {
    alert(`Không mở được biên bản này: ${err.message}`);
  }
}

function renderResults(job) {
  document.getElementById("summary-content").innerHTML = simpleMarkdownToHtml(job.summary_markdown || "");
  renderSpeakerLegend(job);
  renderTranscript(job);
}

function renderSpeakerLegend(job) {
  const uniqueSpeakers = [...new Set(job.segments.map((s) => s.speaker))];
  const legend = document.getElementById("speaker-legend");
  legend.innerHTML = "";
  uniqueSpeakers.forEach((spk) => {
    const chip = document.createElement("span");
    chip.className = "speaker-chip";
    chip.textContent = job.speaker_names[spk] || spk;
    chip.dataset.speakerKey = spk;
    chip.addEventListener("click", () => renameSpeaker(spk));
    legend.appendChild(chip);
  });
}

async function renameSpeaker(speakerKey) {
  const currentName = state.currentJob.speaker_names[speakerKey] || speakerKey;
  const newName = prompt("Đổi tên người nói:", currentName);
  if (!newName) return;

  state.currentJob.speaker_names[speakerKey] = newName;
  renderResults(state.currentJob);

  await fetch(`${API_BASE}/api/jobs/${state.currentJob.job_id}/speakers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(state.currentJob.speaker_names),
  });
}

function renderTranscript(job) {
  const list = document.getElementById("transcript-list");
  list.innerHTML = "";
  job.segments.forEach((seg) => {
    const row = document.createElement("div");
    row.className = "transcript-seg";
    const displayName = job.speaker_names[seg.speaker] || seg.speaker;
    row.innerHTML = `<span class="ts">${formatTs(seg.start)}</span><span class="spk" data-key="${seg.speaker}">${displayName}:</span> ${escapeHtml(seg.text)}`;
    row.querySelector(".spk").addEventListener("click", () => renameSpeaker(seg.speaker));
    list.appendChild(row);
  });
}

function formatTs(seconds) {
  const m = Math.floor(seconds / 60).toString().padStart(2, "0");
  const s = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function simpleMarkdownToHtml(md) {
  // Parser tối giản chỉ đủ cho cấu trúc cố định do prompt tóm tắt sinh ra
  // (## heading, gạch đầu dòng -, bảng |). Đồng bộ với backend/app/export/docx_export.py.
  return md
    .split("\n")
    .map((line) => {
      if (line.startsWith("## ")) return `<h3>${escapeHtml(line.slice(3))}</h3>`;
      if (line.startsWith("- ")) return `<div>• ${escapeHtml(line.slice(2))}</div>`;
      if (line.trim() === "") return "<br/>";
      return `<div>${escapeHtml(line)}</div>`;
    })
    .join("");
}

document.getElementById("btn-export").addEventListener("click", async () => {
  if (!state.currentJob) return;
  const res = await fetch(`${API_BASE}/api/jobs/${state.currentJob.job_id}/export?fmt=docx`, {
    method: "POST",
  });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${state.currentJob.title}.docx`;
  a.click();
});

// ---------- Thư viện biên bản cũ ----------
async function loadLibrary() {
  const res = await fetch(`${API_BASE}/api/jobs`);
  const jobs = await res.json();
  renderLibrary(jobs);
}

function renderLibrary(jobs) {
  const list = document.getElementById("library-list");
  list.innerHTML = "";
  if (jobs.length === 0) {
    list.innerHTML = '<div class="muted">Chưa có biên bản nào. Bắt đầu một cuộc họp mới ở Trang chủ.</div>';
    return;
  }
  jobs.forEach((job) => {
    const item = document.createElement("div");
    item.className = "library-item";
    const statusClass = job.stage === "done" ? "status-done" : job.stage === "error" ? "status-error" : "";
    item.innerHTML = `
      <div>
        <div>${escapeHtml(job.title)}</div>
        <div class="muted small">${job.created_at}</div>
      </div>
      <div class="${statusClass}">${STAGE_LABELS[job.stage] || job.stage}</div>
    `;
    // QUAN TRỌNG: trước đây chỉ xử lý click khi job.stage === "done" -- bấm
    // vào job bị lỗi hoặc đang xử lý dở thì KHÔNG có phản ứng gì cả, không
    // báo lý do -- đây chính là lỗi thật "không mở được mục trong thư viện"
    // (thường xảy ra với các job còn sót lại từ lần chạy trước bị lỗi, hoặc
    // job bị ngắt giữa chừng). Giờ bấm mục nào cũng có phản hồi rõ ràng.
    item.addEventListener("click", () => {
      if (job.stage === "done") {
        state.currentJobId = job.job_id;
        loadResults(job.job_id);
      } else if (job.stage === "error") {
        alert(
          `Cuộc họp "${job.title}" xử lý bị lỗi:\n\n${job.error_message || "Không rõ nguyên nhân."}\n\n` +
          `Bạn có thể xoá mục này và thử lại với file ghi âm gốc.`
        );
      } else {
        alert(
          `Cuộc họp "${job.title}" chưa xử lý xong (${STAGE_LABELS[job.stage] || job.stage}). ` +
          `Nếu app đã đóng giữa chừng lúc xử lý, hãy thử tạo lại từ Trang chủ với file ghi âm gốc.`
        );
      }
    });
    list.appendChild(item);
  });
}

document.getElementById("library-search").addEventListener("input", async (e) => {
  const q = e.target.value.toLowerCase();
  const res = await fetch(`${API_BASE}/api/jobs`);
  const jobs = await res.json();
  renderLibrary(jobs.filter((j) => j.title.toLowerCase().includes(q)));
});

// ---------- Cài đặt: bật/tắt nhận diện người nói + luồng dẫn dắt HF token ----------
// Mặc định TẮT (xem backend/app/settings.py) — người dùng không cần biết
// khái niệm "Hugging Face token" tồn tại nếu họ không chủ động bật tính
// năng này. Đây là quyết định UX để tránh bắt người dùng thường tự setup
// một thứ họ không hiểu chỉ để dùng được app.

async function loadSettings() {
  const res = await fetch(`${API_BASE}/api/settings`);
  state.settings = await res.json();
  document.getElementById("toggle-diarization").checked = state.settings.diarization_enabled;
  document.getElementById("diarization-guide").classList.toggle("hidden", !state.settings.diarization_enabled);
  if (state.settings.hf_token_set) {
    document.getElementById("hf-token-input").placeholder = "Đã lưu token (nhập token mới để thay)";
  }
  document.getElementById("select-ollama-model").value = state.settings.ollama_model_override || "";
  await renderOllamaModelCurrent();
  await loadDataDirCurrent();
}

// ---------- Nơi lưu model AI + dữ liệu app ----------
// Windows luôn lưu ở ổ C: (AppData) mặc định bất kể cài app ở ổ nào (lỗi
// thật đã gặp: hết dung lượng ổ C: khi tải model AI ~1.4GB dù app cài ở ổ
// D:). Gọi qua lệnh Tauri (invoke), KHÔNG qua backend Python -- vì đây là
// đường dẫn Tauri tự quản lý cho 2 sidecar (main.rs), backend không biết gì
// về việc này.
function tauriInvoke(cmd, args) {
  // withGlobalTauri: true trong tauri.conf.json -> window.__TAURI__ luôn có
  // sẵn trong app đóng gói thật. Kiểm tra tồn tại phòng trường hợp mở thẳng
  // file HTML này bằng trình duyệt thường lúc dev/test giao diện (không có
  // Tauri) -- tránh lỗi "window.__TAURI__ undefined" chặn cả trang.
  if (!window.__TAURI__) return Promise.reject(new Error("Không chạy trong Tauri"));
  return window.__TAURI__.core.invoke(cmd, args);
}

async function loadDataDirCurrent() {
  const el = document.getElementById("data-dir-current");
  if (!el) return;
  try {
    el.textContent = await tauriInvoke("get_data_dir");
  } catch {
    el.textContent = "(không xác định)";
  }
}

document.getElementById("btn-change-data-dir")?.addEventListener("click", async () => {
  const note = document.getElementById("data-dir-note");
  try {
    const newPath = await tauriInvoke("pick_data_dir");
    if (!newPath) return; // người dùng bấm Huỷ trong hộp thoại chọn thư mục
    await loadDataDirCurrent();
    note.textContent =
      `Đã đổi. Dữ liệu CŨ (model AI đã tải, biên bản đã lưu...) vẫn nằm ở vị trí trước đó, không tự chuyển. ` +
      `Đóng hẳn app rồi mở lại để dùng thư mục mới — nếu chưa có model AI ở đó, app sẽ tải lại.`;
    note.classList.remove("hidden");
  } catch (err) {
    note.textContent = `Không đổi được thư mục: ${err.message || err}`;
    note.classList.remove("hidden");
  }
});

async function renderOllamaModelCurrent() {
  const box = document.getElementById("ollama-model-current");
  if (!box) return;
  if (state.settings.ollama_model_override) {
    box.textContent = `Đang dùng: ${state.settings.ollama_model_override} (tự chọn, ghi đè đề xuất tự động).`;
    return;
  }
  try {
    const res = await fetch(`${API_BASE}/api/hardware`);
    const data = await res.json();
    box.textContent = `Đang dùng: ${data.recommendation.ollama_model} (tự động, theo cấu hình máy này).`;
  } catch {
    box.textContent = "Đang dùng: tự động theo cấu hình máy.";
  }
}

document.getElementById("btn-save-ollama-model").addEventListener("click", async () => {
  const model = document.getElementById("select-ollama-model").value;
  const form = new URLSearchParams({ model });
  const res = await fetch(`${API_BASE}/api/settings/ollama-model`, { method: "POST", body: form });
  state.settings = await res.json();
  await renderOllamaModelCurrent();
});

document.getElementById("toggle-diarization").addEventListener("change", async (e) => {
  const enabled = e.target.checked;
  document.getElementById("diarization-guide").classList.toggle("hidden", !enabled);
  const form = new URLSearchParams({ enabled: String(enabled) });
  const res = await fetch(`${API_BASE}/api/settings/diarization`, { method: "POST", body: form });
  state.settings = await res.json();
  renderDiarizationStatusNote();
});

document.querySelectorAll(".btn-open-link").forEach((btn) => {
  btn.addEventListener("click", () => openExternalLink(btn.dataset.url));
});

function openExternalLink(url) {
  // Chạy trong Tauri: dùng plugin shell để mở trình duyệt mặc định của máy
  // (không phải trình duyệt trong app). Fallback window.open cho lúc dev
  // thử trực tiếp bằng trình duyệt thường (npm run dev trước khi có Tauri).
  if (window.__TAURI__ && window.__TAURI__.shell && window.__TAURI__.shell.open) {
    window.__TAURI__.shell.open(url);
  } else {
    window.open(url, "_blank");
  }
}

document.getElementById("btn-save-token").addEventListener("click", async () => {
  const input = document.getElementById("hf-token-input");
  const token = input.value.trim();
  const resultBox = document.getElementById("token-test-result");
  if (!token) {
    resultBox.textContent = "Dán token vào ô trên trước đã.";
    resultBox.className = "small";
    return;
  }
  const form = new URLSearchParams({ hf_token: token });
  await fetch(`${API_BASE}/api/settings/hf-token`, { method: "POST", body: form });
  input.value = "";
  input.placeholder = "Đã lưu token (nhập token mới để thay)";
  resultBox.textContent = "Đã lưu. Bấm 'Kiểm tra' để xác nhận token dùng được.";
  resultBox.className = "small";
});

document.getElementById("btn-test-token").addEventListener("click", async () => {
  const resultBox = document.getElementById("token-test-result");
  resultBox.textContent = "Đang kiểm tra...";
  resultBox.className = "small";
  const res = await fetch(`${API_BASE}/api/settings/hf-token/test`, { method: "POST" });
  const data = await res.json();
  resultBox.textContent = (data.ok ? "✅ " : "❌ ") + data.message;
  resultBox.className = data.ok ? "small" : "small warning-text";
});

function renderDiarizationStatusNote() {
  const note = document.getElementById("diarization-status-note");
  if (!note) return;
  if (state.settings.diarization_enabled) {
    note.textContent = "🎙️ Nhận diện người nói: đang bật.";
  } else {
    note.textContent = "🎙️ Nhận diện người nói: đang tắt — biên bản sẽ không phân biệt ai nói câu nào. Bật ở mục Cài đặt nếu cần.";
  }
}

// ---------- Khởi động ----------
(async function init() {
  loadSettings(); // tải nhẹ ở nền để có sẵn state.settings.diarization_enabled
                   // khi người dùng chọn file ở Trang chủ, không cần đợi mở màn Cài đặt trước
  if (!localStorage.getItem("onboarding_done")) {
    showView("view-onboarding");
    runOnboardingCheck();
    return;
  }
  // Đã qua onboarding trước đây, nhưng vẫn kiểm tra nhanh AI đã sẵn sàng
  // chưa — phòng trường hợp lần trước đóng app giữa lúc đang tải model.
  // Bình thường sẽ rất nhanh (model đã có sẵn từ lần trước) nên không gây
  // cảm giác chờ ở lần mở app tiếp theo.
  try {
    const res = await fetch(`${API_BASE}/api/onboarding/ai-ready`);
    const data = await res.json();
    if (data.engine_running && data.model_ready) {
      setActiveNav("nav-home");
      showView("view-home");
      return;
    }
  } catch {
    // không kết nối được — vẫn thử luồng chuẩn bị AI bên dưới, nó sẽ tự
    // hiển thị trạng thái và thử lại.
  }
  showView("view-onboarding");
  document.getElementById("hw-check-status").classList.add("hidden");
  prepareAiThenEnterApp();
})();
