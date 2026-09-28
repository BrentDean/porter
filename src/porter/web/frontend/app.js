"use strict";

const SESSION_KEY = "porter.web.session_id";

const transcript = document.querySelector("#transcript");
const composer = document.querySelector("#composer");
const promptInput = document.querySelector("#prompt");
const sendButton = document.querySelector("#send-button");

function getSessionId() {
  let sessionId = sessionStorage.getItem(SESSION_KEY);
  if (!sessionId) {
    sessionId = crypto.randomUUID();
    sessionStorage.setItem(SESSION_KEY, sessionId);
  }
  return sessionId;
}

let sessionId = getSessionId();

function normalizeCommand(text) {
  return text.trim().toLowerCase().replace(/\s+/g, " ");
}

function scrollToLatest() {
  transcript.scrollTop = transcript.scrollHeight;
}

function appendMessage(role, text, metadata = null) {
  const message = document.createElement("article");
  message.classList.add("message", `message-${role}`);

  const label = document.createElement("div");
  label.className = "message-label";
  label.textContent = role === "user" ? "You" : role === "porter" ? "Porter" : "Notice";
  message.appendChild(label);

  const body = document.createElement("p");
  body.textContent = text;
  message.appendChild(body);

  if (metadata) {
    const meta = document.createElement("div");
    meta.className = "message-meta";
    meta.textContent = metadata;
    message.appendChild(meta);
  }

  transcript.appendChild(message);
  scrollToLatest();
  return message;
}

function routeMetadata(payload) {
  if (payload.path === "inference") {
    const provider = payload.provider || "local AI";
    return payload.model ? `${provider}/${payload.model}` : provider;
  }
  if (payload.path === "tool" && payload.tool) {
    return `tool: ${payload.tool}`;
  }
  return payload.path || "porter";
}

function setBusy(busy) {
  sendButton.disabled = busy;
  sendButton.textContent = busy ? "Sending…" : "Send";
}

async function readJson(response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

async function sendRequest(text) {
  setBusy(true);
  try {
    const response = await fetch("/api/v1/requests", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        text,
        session_id: sessionId,
      }),
    });
    const payload = await readJson(response);

    if (response.ok && payload) {
      appendMessage("porter", payload.text, routeMetadata(payload));
      return;
    }

    if (response.status === 403 && payload && payload.error === "action_not_authorized") {
      const detail = payload.detail ? ` ${payload.detail}` : "";
      appendMessage(
        "error",
        `This web interface is not authorized for that action.${detail}`
      );
      return;
    }

    if (response.status === 503 && payload && payload.error === "no_provider_available") {
      appendMessage("error", "Local AI is currently unavailable.");
      return;
    }

    appendMessage("error", "Porter could not complete that request.");
  } catch {
    appendMessage("error", "Could not reach the local Porter service.");
  } finally {
    setBusy(false);
    promptInput.focus();
  }
}

async function clearContext() {
  setBusy(true);
  try {
    const response = await fetch(`/api/v1/sessions/${encodeURIComponent(sessionId)}`, {
      method: "DELETE",
    });
    if (!response.ok) {
      appendMessage("error", "Porter could not clear the conversation context.");
      return;
    }

    sessionStorage.removeItem(SESSION_KEY);
    sessionId = getSessionId();
    appendMessage("system", "Conversation context cleared.");
  } catch {
    appendMessage("error", "Could not reach the local Porter service.");
  } finally {
    setBusy(false);
    promptInput.focus();
  }
}

composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = promptInput.value.trim();
  if (!text || sendButton.disabled) {
    return;
  }

  promptInput.value = "";
  if (normalizeCommand(text) === "clear context") {
    await clearContext();
    return;
  }

  appendMessage("user", text);
  await sendRequest(text);
});

promptInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    composer.requestSubmit();
  }
});

promptInput.focus();
