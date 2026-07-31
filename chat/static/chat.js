// ── токены ────────────────────────────────────────────────────────────────


// ── auth modal ────────────────────────────────────────────────────────────
let allChats = [];
let currentChatId = null;
let ws = null;

// ── инициализация ─────────────────────────────────────────────────────────
(async () => {
    const ok = await refreshAccessToken();
    if (!ok) { showAuthModal(); return; }
    await loadChats();
    const withId = new URLSearchParams(location.search).get("with");
    if (withId) await openChat(withId);
})();

// ── список чатов ──────────────────────────────────────────────────────────
async function loadChats() {
    const res = await apiFetch("/my/chats");
    if (!res) { document.getElementById("chatList").innerHTML = `<div class="empty-state">ошибка загрузки</div>`; return; }
    const data = await res.json();
    allChats = data.chats || [];
    renderChats(allChats);
}

function renderChats(chats) {
    const el = document.getElementById("chatList");
    if (!chats.length) {
        el.innerHTML = `<div class="empty-state">Диалогов пока нет. Нажми «+ новый».</div>`;
        return;
    }
    el.innerHTML = chats.map(c => {
        const initials = (c.other_name || "?").slice(0, 2).toUpperCase();
        const preview = c.last_message
            ? (c.last_message.sender_id === myId ? "Вы: " : "") + escapeHtml(c.last_message.text).slice(0, 60)
            : "нет сообщений";
        const time = c.last_message
            ? new Date(c.last_message.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
            : "";
        return `<div class="chat-item" onclick="openChat('${c.other_id}')">
            <div class="avatar">${initials}</div>
            <div class="chat-info">
                <div class="chat-name">${escapeHtml(c.other_name)}</div>
                <div class="chat-preview">${preview}</div>
            </div>
            <div class="chat-time">${time}</div>
        </div>`;
    }).join("");
}

function filterChats() {
    const q = document.getElementById("searchInput").value.toLowerCase();
    renderChats(allChats.filter(c => c.other_name.toLowerCase().includes(q)));
}

// ── открыть чат ───────────────────────────────────────────────────────────
async function openChat(targetId) {
    closeModal();
    document.getElementById("modalError").style.display = "none";

    const res = await apiFetch(`/chat/open?with_id=${encodeURIComponent(targetId)}`);
    if (!res || !res.ok) { showModalError("Пользователь не найден"); return; }

    currentChatId = (await res.json()).chat_id;
    const found = allChats.find(c => c.other_id === targetId);
    const name = found ? found.other_name : targetId.slice(0, 8) + "…";
    document.getElementById("topbarTitle").textContent = name;
    document.getElementById("backBtn").style.display = "block";

    showScreen("chatScreen");
    connectWs(currentChatId);
    document.getElementById("textInput").focus();
}

// ── WebSocket ─────────────────────────────────────────────────────────────
function connectWs(chatId) {
    if (ws) ws.close();
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws/chat/${chatId}?token=${encodeURIComponent(accessToken)}`);

    const st = document.getElementById("wsStatus");
    ws.onopen = () => { st.textContent = "online"; st.style.color = "#16a34a"; };
    ws.onclose = () => { st.textContent = ""; st.style = ""; };
    ws.onerror = () => { st.textContent = "ошибка"; st.style.color = "#e53e3e"; };

    ws.onmessage = (e) => {
        const data = JSON.parse(e.data);
        if (data.type === "history") {
            const msgEl = document.getElementById("messages");
            msgEl.innerHTML = "";
            if (!data.messages.length) msgEl.innerHTML = `<div class="empty-state">Сообщений пока нет</div>`;
            else data.messages.forEach((m, i) => addMessage(m, data.messages[i - 1] ?? null));
        }
        if (data.type === "message") {
            const msgEl = document.getElementById("messages");
            const ph = msgEl.querySelector(".empty-state");
            if (ph) ph.remove();
            // Последнее сообщение в списке — чтобы определить группировку
            const lastWrap = msgEl.querySelector(".msg-wrap:last-child");
            const lastSenderId = lastWrap?.dataset.senderId ?? null;
            addMessage(data.message, lastSenderId ? { sender_id: lastSenderId } : null);
        }
    };
}

/*
function renderAttachments(attachments, isMine) {
    if (!attachments || !attachments.length) return "";
    return `<div class="attachments">${attachments.map(a => {
        const icon = attachmentIcon(a.mime);
        const label = escapeHtml(a.original_name || a.url);
        return `<a class="attachment-link" href="${escapeHtml(a.url)}" target="_blank" rel="noopener">
            <span class="icon">${icon}</span>${label}
        </a>`;
    }).join("")}</div>`;
}*/


function addMessage(msg, prevMsg) {
    const isMine = msg.sender_id === myId;
    const isSameAuthor = prevMsg && prevMsg.sender_id === msg.sender_id;
    const time = new Date(msg.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const msgEl = document.getElementById("messages");
    const wrap = document.createElement("div");

    wrap.className = `msg-wrap ${isMine ? "mine" : "theirs"}${isSameAuthor ? " hide-meta" : " group-start"}`;
    wrap.dataset.senderId = msg.sender_id;

    const attachmentsHtml = renderAttachments(msg.attachments, isMine);

    wrap.innerHTML = `<div class="bubble">
        ${msg.text ? escapeHtml(msg.text) : ""}
        ${attachmentsHtml}
        <div class="bubble-meta">${isMine ? time : escapeHtml(msg.sender) + " · " + time}</div>
    </div>`;

    msgEl.appendChild(wrap);
    msgEl.scrollTop = msgEl.scrollHeight;
}


// ── отправка ──────────────────────────────────────────────────────────────
async function sendMessage() {
    if (!ensureLoggedIn()) return;
    const input = document.getElementById("msgInput");
    const text = input.value.trim();
    if (!text && pendingAttachments.length === 0) return;
    if (!currentChatId) return;

    input.value = "";
    const attachments = [...pendingAttachments];
    pendingAttachments = [];
    renderPendingChips();

    const res = await apiFetch(`/chat/${currentChatId}/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, attachments }),
    });

    if (!res) {
        accessToken = null;
        myId = null;
        showAuthModal();
    }
}

// ── навигация ─────────────────────────────────────────────────────────────
function showScreen(id) {
    document.querySelectorAll(".screen").forEach(s => s.classList.remove("active"));
    document.getElementById(id).classList.add("active");
}

function goToList() {
    if (ws) { ws.close(); ws = null; }
    currentChatId = null;
    pendingAttachments = [];
    renderPendingChips();
    document.getElementById("topbarTitle").textContent = "";
    document.getElementById("backBtn").style.display = "none";
    document.getElementById("wsStatus").textContent = "";
    loadChats();
    showScreen("listScreen");
}

// ── модалка нового чата ───────────────────────────────────────────────────
function openModal() {
    if (!ensureLoggedIn()) return;
    document.getElementById("targetIdInput").value = "";
    document.getElementById("modalError").style.display = "none";
    document.getElementById("modal").classList.add("open");
    setTimeout(() => document.getElementById("targetIdInput").focus(), 50);
}
function closeModal() { document.getElementById("modal").classList.remove("open"); }
function showModalError(msg) {
    const el = document.getElementById("modalError");
    el.textContent = msg;
    el.style.display = "block";
    document.getElementById("modal").classList.add("open");
}
async function startNewChat() {
    const id = document.getElementById("targetIdInput").value.trim();
    if (!id) return;
    await openChat(id);
    await loadChats();
}

document.getElementById("textInput").addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});

document.getElementById("targetIdInput").addEventListener("keydown", e => {
    if (e.key === "Enter") startNewChat();
    if (e.key === "Escape") closeModal();
});
document.getElementById("modal").addEventListener("click", e => {
    if (e.target === document.getElementById("modal")) closeModal();
});