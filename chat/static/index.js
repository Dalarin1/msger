const messagesEl = document.getElementById("messages");
const statusEl   = document.getElementById("status");
const input      = document.getElementById("textInput");

function add(msg) {
    const div = document.createElement("div");
    div.className = "msg";
    div.innerHTML = `
        <div class="meta">
            <span class="sender" onclick="location.href='/chat?with=${msg.sender_id}'">${escapeHtml(msg.sender)}</span>
        </div>
        ${msg.text ? `<div class="text">${escapeHtml(msg.text)}</div>` : ""}
        ${renderAttachments(msg.attachments)}`;
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

// WebSocket
const proto = location.protocol === "https:" ? "wss" : "ws";
const ws = new WebSocket(`${proto}://${location.host}/ws`);
ws.onopen  = () => { statusEl.textContent = "online"; };
ws.onclose = () => { statusEl.textContent = "offline"; };
ws.onerror = () => { statusEl.textContent = "error"; };
ws.onmessage = (e) => {
    const data = JSON.parse(e.data);
    if (data.type === "history") { messagesEl.innerHTML = ""; data.messages.forEach(add); }
    if (data.type === "message") add(data.message);
};

// Отправка
async function send() {
    const text = input.value.trim();
    if (!text && pendingAttachments.length === 0) return;
    if (!ensureLoggedIn()) return;

    input.value = "";
    const attachments = [...pendingAttachments];
    pendingAttachments = [];
    renderPendingChips();

    const res = await apiFetch("/send_msg", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, attachments }),
    });

    if (!res) {
        accessToken = null;
        ensureLoggedIn();
    }
}

input.addEventListener("keydown", e => { if (e.key === "Enter") send(); });
document.getElementById("sendBtn").addEventListener("click", send);

(async () => { await refreshAccessToken(); })();