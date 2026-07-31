let accessToken = null;
let myId = null;
let pendingAttachments = [];

function escapeHtml(s) {
    return String(s).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

// ── токены / авторизация ─────────────────────────────────────────────────
function parseJwtPayload(token) {
    try { return JSON.parse(atob(token.split(".")[1])); } catch { return null; }
}

async function refreshAccessToken() {
    const res = await fetch("/auth/refresh", { method: "POST", credentials: "include" });
    if (!res.ok) return false;
    const data = await res.json();
    accessToken = data.access_token;
    myId = parseJwtPayload(accessToken)?.sub ?? null;

    const nameEl = document.getElementById("my-name");
    if (nameEl) {
        nameEl.textContent = data.name.length > 15
            ? data.name.substring(0, 12) + "..."
            : data.name;
    }

    return true;
}

async function apiFetch(url, options = {}) {
    if (!accessToken) {
        const ok = await refreshAccessToken();
        if (!ok) return null;
    }
    const doReq = () => fetch(url, {
        ...options,
        credentials: "include",
        headers: { ...options.headers, "Authorization": `Bearer ${accessToken}` },
    });
    let res = await doReq();
    if (res.status === 401) {
        const ok = await refreshAccessToken();
        if (!ok) return null;
        res = await doReq();
    }
    return res;
}

function isLoggedIn() { return accessToken !== null && myId !== null; }

// ── auth-модалка ("нужен аккаунт") ───────────────────────────────────────
function showAuthModal() {
    const overlay = document.getElementById("authOverlay");
    if (overlay) overlay.classList.add("visible");
}
function hideAuthModal() {
    const overlay = document.getElementById("authOverlay");
    if (overlay) overlay.classList.remove("visible");
}
function ensureLoggedIn() {
    if (isLoggedIn()) return true;
    showAuthModal();
    return false;
}

document.addEventListener("DOMContentLoaded", () => {
    const overlay = document.getElementById("authOverlay");
    if (overlay) {
        overlay.addEventListener("click", (e) => { if (e.target === overlay) hideAuthModal(); });
    }
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && overlay?.classList.contains("visible")) hideAuthModal();
    });
});

// ── вложения: рендер ──────────────────────────────────────────────────────
function attachmentIcon(mime) {
    if (!mime) return "📄";
    if (mime.startsWith("image/")) return "🖼";
    if (mime.startsWith("audio/")) return "🎵";
    if (mime.startsWith("video/")) return "🎬";
    return "📄";
}

function renderCommonAttachementLink(url, icon, label) {
    return `
        <a class="attachment-file"
           href="${escapeHtml(url)}"
           target="_blank"
           rel="noopener">
            <span>${icon}</span>
            <span>${label}</span>
        </a>
    `;
}

function renderAudioAttachments(att) {
    const url = escapeHtml(att.url);
    if (att.mime?.startsWith("audio/")) {
        return `<audio src="${url}" controls></audio>`;
    }
    return null;
}

function renderImageOrVideoAttachements(att) {
    const url = escapeHtml(att.url);

    if (att.mime?.startsWith("image/")) {
        return `
            <a href="${url}" target="_blank">
                <img
                    class="attachment-image"
                    src="${url}"
                    loading="lazy"
                    alt="">
            </a>
        `;
    }

    if (att.mime?.startsWith("video/")) {
        return `
            <video
                class="attachment-video"
                controls
                preload="metadata">
                <source src="${url}" type="${att.mime}">
            </video>
        `;
    }

    return null;
}

function renderAttachments(attachments) {
    if (!attachments?.length) return "";

    return `
        <div class="attachments">
            ${attachments.map(att => {
                const media = renderImageOrVideoAttachements(att);
                const audio = renderAudioAttachments(att);
                if (media) return media;
                if (audio) return audio;
                return renderCommonAttachementLink(
                    att.url,
                    attachmentIcon(att.mime),
                    escapeHtml(att.original_name || att.url)
                );
            }).join("")}
        </div>
    `;
}

// ── загрузка файлов (скрепка) ────────────────────────────────────────────
function handleFileSelect(event) {
    const files = Array.from(event.target.files);
    event.target.value = ""; // сбросить, чтобы можно было выбрать тот же файл снова
    files.forEach(uploadFile);
}

async function uploadFile(file) {
    const statusEl = document.getElementById("uploadStatus");
    if (statusEl) {
        statusEl.style.display = "block";
        statusEl.textContent = `Загрузка ${file.name}…`;
    }

    const formData = new FormData();
    formData.append("file", file);

    const res = await apiFetch("/upload", { method: "POST", body: formData });
    if (!res || !res.ok) {
        const err = res ? (await res.json().catch(() => ({}))).detail : "ошибка сети";
        if (statusEl) {
            statusEl.textContent = `Ошибка: ${err || "не удалось загрузить"}`;
            setTimeout(() => { statusEl.style.display = "none"; }, 3000);
        }
        return;
    }

    const data = await res.json();
    pendingAttachments.push({ url: data.url, mime: data.mime, original_name: data.original_name });
    renderPendingChips();
    if (statusEl) statusEl.style.display = "none";
}

function renderPendingChips() {
    const el = document.getElementById("pendingFiles");
    if (!el) return;
    el.innerHTML = pendingAttachments.map((a, i) => {
        const icon = attachmentIcon(a.mime);
        return `<div class="pending-chip">
            <span>${icon}</span>
            <span>${escapeHtml(a.original_name || a.url)}</span>
            <button class="remove" onclick="removePending(${i})">✕</button>
        </div>`;
    }).join("");
}

function removePending(idx) {
    pendingAttachments.splice(idx, 1);
    renderPendingChips();
}

// ── запись голосовых сообщений ───────────────────────────────────────────
let vmRecorder = null;
let vmChunks = [];
let vmIsRecording = false;

function showMicDeniedModal() {
    if (document.getElementById("micDeniedOverlay")) return; // уже открыта
    const overlay = document.createElement("div");
    overlay.id = "micDeniedOverlay";
    overlay.innerHTML = `
        <div class="box">
            <h3>Нет доступа к микрофону</h3>
            <p>
                Похоже, доступ к микрофону заблокирован в настройках браузера для этого сайта.
                Разреши его в настройках сайта (обычно иконка 🔒 или ⓘ рядом с адресной строкой) и обнови страницу.
            </p>
            <button onclick="this.closest('#micDeniedOverlay').remove()">Понятно</button>
        </div>
    `;
    overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });
    document.body.appendChild(overlay);
}

async function requestMicAccess() {
    let permissionState = "prompt";
    try {
        const status = await navigator.permissions.query({ name: "microphone" });
        permissionState = status.state; // "granted" | "denied" | "prompt"
    } catch {
        // Permissions API недоступен (Safari/Firefox) — попробуем getUserMedia напрямую
    }

    if (permissionState === "denied") {
        showMicDeniedModal();
        return null;
    }

    try {
        return await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
        showMicDeniedModal();
        return null;
    }
}

async function startRecording() {
    const stream = await requestMicAccess();
    if (!stream) return false;

    vmRecorder = new MediaRecorder(stream);
    vmChunks = [];

    vmRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) vmChunks.push(e.data);
    };

    vmRecorder.onstop = async () => {
        // Останавливаем треки — гасит индикатор микрофона во вкладке браузера
        stream.getTracks().forEach(track => track.stop());
        const blob = new Blob(vmChunks, { type: "audio/mp3" });
        vmChunks = [];
        await uploadRecordedVoice(blob);
    };

    vmRecorder.start();
    return true;
}

async function uploadRecordedVoice(blob) {
    const statusEl = document.getElementById("uploadStatus");
    if (statusEl) {
        statusEl.style.display = "block";
        statusEl.textContent = "Загрузка голосового…";
    }

    const formData = new FormData();
    formData.append("file", blob, `voice_${Date.now()}.mp3`);

    const res = await apiFetch("/upload", { method: "POST", body: formData });
    if (!res || !res.ok) {
        if (statusEl) {
            statusEl.textContent = "Ошибка загрузки голосового";
            setTimeout(() => { statusEl.style.display = "none"; }, 3000);
        }
        return;
    }

    const data = await res.json();
    pendingAttachments.push({ url: data.url, mime: data.mime, original_name: data.original_name });
    renderPendingChips();
    if (statusEl) statusEl.style.display = "none";
}

document.addEventListener("DOMContentLoaded", () => {
    const recordVMButton = document.getElementById("recordVM");
    if (!recordVMButton) return; // на странице нет кнопки записи ГС — ничего не вешаем

    recordVMButton.onclick = async function () {
        if (!ensureLoggedIn()) return;

        if (!vmIsRecording) {
            const started = await startRecording();
            if (started) {
                vmIsRecording = true;
                recordVMButton.textContent = "⏹";
                recordVMButton.title = "Остановить запись";
                recordVMButton.classList.add("recording");
            }
        } else {
            vmRecorder.stop();
            vmIsRecording = false;
            recordVMButton.textContent = "🎙";
            recordVMButton.title = "Записать ГС";
            recordVMButton.classList.remove("recording");
        }
    };
});