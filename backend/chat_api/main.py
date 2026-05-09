"""
FastAPI chat bridge for the Layer 1 SafetyAgent.

Owns one warm SafetyAgent instance for the lifetime of the process. Concurrent
requests serialize through an asyncio.Lock because the LLM child subprocess
processes one prompt at a time over a single Pipe.

Run:
    # real GPU mode (requires 3 MIG slices, see agents/safety_agent.py)
    uvicorn backend.chat_api.main:app --reload --port 8001

    # mock mode (no GPU, fake streaming for UI development)
    CHAT_API_MOCK=1 uvicorn backend.chat_api.main:app --reload --port 8001

Endpoints (stable surface = /api/v1/*):
    GET  /api/v1/health
    GET  /api/v1/tables
    POST /api/v1/tables/select
    WS   /api/v1/ws/chat
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from .models import (
    HealthResponse,
    TableInfo,
    TableListResponse,
    TableSelectRequest,
    TableSelectResponse,
)

logger = logging.getLogger("chat_api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# backend/chat_api/main.py -> project root is parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[2]
LANCEDB_DIR = PROJECT_ROOT / "data" / "lancedb"
MOCK_MODE = os.environ.get("CHAT_API_MOCK", "0") == "1"


def _list_tables() -> list[Path]:
    if not LANCEDB_DIR.exists():
        return []
    return sorted(p for p in LANCEDB_DIR.glob("*.lance") if p.is_dir())


# ---------------------------------------------------------------------------
# Agent state
# ---------------------------------------------------------------------------


class AgentState:
    """Holds the warm SafetyAgent and serializes access to its LLM subprocess."""

    def __init__(self) -> None:
        self.agent = None  # SafetyAgent | MockAgent | None
        self.active_table: Optional[Path] = None
        self.lock = asyncio.Lock()

    def open_real_agent(self, table_path: Path) -> None:
        from agents.safety_agent import SafetyAgent

        logger.info("Loading SafetyAgent on %s ...", table_path)
        t0 = time.monotonic()
        self.agent = SafetyAgent.open(table_path)
        self.active_table = table_path
        logger.info("SafetyAgent ready in %.1fs", time.monotonic() - t0)

    def open_mock_agent(self, table_path: Optional[Path]) -> None:
        self.agent = MockAgent()
        self.active_table = table_path
        logger.info("Mock agent ready (mock mode active)")

    def switch(self, table_path: Path) -> None:
        if self.agent is None:
            raise RuntimeError("Agent not loaded yet")
        if hasattr(self.agent, "switch_table"):
            self.agent.switch_table(table_path)
        self.active_table = table_path

    def close(self) -> None:
        if self.agent is not None and hasattr(self.agent, "close"):
            try:
                self.agent.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error closing agent: %s", exc)


class MockAgent:
    """Fake agent for UI development without GPU. Streams a canned answer token by token."""

    def retrieve(self, query: str, k: int = 100, top_n: int = 15) -> list[dict]:
        return [
            {
                "section": "MOCK / Section 4.2",
                "chunk_type": "text",
                "text": "This is mock context returned by the chat_api MockAgent. "
                "Set CHAT_API_MOCK=0 to use the real SafetyAgent.",
                "_rerank_score": 0.92,
            }
        ]

    def generate_stream(self, query: str, chunks: list[dict]):
        canned = (
            f"(mock response) You asked: {query!r}\n\n"
            "The chat_api backend is running in CHAT_API_MOCK mode, which streams a "
            "canned answer instead of invoking the real LLM. This lets you iterate on "
            "the chat UI without booting the 3-stage GPU pipeline.\n\n"
            "Switch CHAT_API_MOCK=0 (or unset it) and restart uvicorn to use the real "
            "SafetyAgent against an indexed LanceDB table."
        )
        for word in canned.split(" "):
            yield word + " "

    def switch_table(self, table_path: Path) -> None:
        pass

    def close(self) -> None:
        pass


state = AgentState()


# ---------------------------------------------------------------------------
# Lifespan: warm-load the agent on startup
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    tables = _list_tables()
    initial = tables[0] if tables else None

    if MOCK_MODE:
        state.open_mock_agent(initial)
    elif initial is None:
        logger.warning(
            "No LanceDB tables found in %s. Starting without an agent. "
            "Index a table or set CHAT_API_MOCK=1 for UI dev.",
            LANCEDB_DIR,
        )
    else:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, state.open_real_agent, initial)

    try:
        yield
    finally:
        state.close()


app = FastAPI(
    title="x1025 Maritime Intelligence — Chat API",
    description="WebSocket bridge that streams Layer 1 SafetyAgent answers to the web chat UI.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?|https://[a-z0-9.-]+\.trycloudflare\.com",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# REST
# ---------------------------------------------------------------------------


@app.get("/api/v1/health", response_model=HealthResponse, tags=["Meta"])
def health() -> HealthResponse:
    return HealthResponse(
        status="ok" if state.agent is not None else "loading",
        agent_loaded=state.agent is not None,
        active_table=str(state.active_table) if state.active_table else None,
        mock=MOCK_MODE,
    )


@app.get("/api/v1/tables", response_model=TableListResponse, tags=["Tables"])
def list_tables() -> TableListResponse:
    paths = _list_tables()
    active = str(state.active_table) if state.active_table else None
    return TableListResponse(
        tables=[
            TableInfo(name=p.stem, path=str(p), is_active=(str(p) == active))
            for p in paths
        ],
        active=active,
    )


@app.post("/api/v1/tables/select", response_model=TableSelectResponse, tags=["Tables"])
async def select_table(req: TableSelectRequest) -> TableSelectResponse:
    target = Path(req.path).resolve()
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail=f"Table not found: {req.path}")
    if target.parent.resolve() != LANCEDB_DIR.resolve():
        raise HTTPException(status_code=400, detail="Table must live under data/lancedb/")

    async with state.lock:
        if state.agent is None:
            if MOCK_MODE:
                state.open_mock_agent(target)
            else:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, state.open_real_agent, target)
        else:
            await asyncio.get_running_loop().run_in_executor(None, state.switch, target)

    return TableSelectResponse(active=str(state.active_table))


# ---------------------------------------------------------------------------
# WebSocket: stream answer tokens
# ---------------------------------------------------------------------------


@app.websocket("/api/v1/ws/chat")
async def ws_chat(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            payload = await websocket.receive_json()
            question = (payload or {}).get("question", "").strip()
            k = int((payload or {}).get("k") or 100)
            top_n = int((payload or {}).get("top_n") or 15)

            if not question:
                await websocket.send_json({"type": "error", "message": "empty question"})
                continue

            if state.agent is None:
                await websocket.send_json({
                    "type": "error",
                    "message": "Agent not loaded. POST /api/v1/tables/select first or run in CHAT_API_MOCK=1.",
                })
                continue

            await _stream_answer(websocket, question, k, top_n)
    except WebSocketDisconnect:
        return


async def _stream_answer(websocket: WebSocket, question: str, k: int, top_n: int) -> None:
    """Run retrieve + generate, push tokens as they're produced."""
    loop = asyncio.get_running_loop()

    async with state.lock:
        await websocket.send_json({
            "type": "start",
            "table": str(state.active_table) if state.active_table else None,
        })

        try:
            chunks = await loop.run_in_executor(
                None, lambda: state.agent.retrieve(question, k=k, top_n=top_n)
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("retrieve() failed")
            await websocket.send_json({"type": "error", "message": f"retrieve failed: {exc}"})
            return

        await websocket.send_json({
            "type": "sources",
            "chunks": [_chunk_summary(c) for c in chunks],
        })

        # The LLM pipe is sync. Pull chunks in a worker thread and forward.
        queue: asyncio.Queue = asyncio.Queue()
        SENTINEL = object()

        def producer() -> None:
            try:
                for token in state.agent.generate_stream(question, chunks):
                    asyncio.run_coroutine_threadsafe(queue.put(token), loop)
            except Exception as exc:  # noqa: BLE001
                asyncio.run_coroutine_threadsafe(queue.put(("__error__", str(exc))), loop)
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(SENTINEL), loop)

        loop.run_in_executor(None, producer)

        try:
            while True:
                item = await queue.get()
                if item is SENTINEL:
                    break
                if isinstance(item, tuple) and item and item[0] == "__error__":
                    await websocket.send_json({"type": "error", "message": item[1]})
                    return
                await websocket.send_json({"type": "token", "text": item})
        except WebSocketDisconnect:
            return

        await websocket.send_json({"type": "end"})


def _chunk_summary(chunk: dict) -> dict:
    """Trim retrieval chunk to the fields the UI needs."""
    text = chunk.get("text", "") or ""
    return {
        "section": chunk.get("section", ""),
        "chunk_type": chunk.get("chunk_type", "text"),
        "rerank_score": float(chunk.get("_rerank_score", 0.0)),
        "preview": text[:280] + ("..." if len(text) > 280 else ""),
    }


@app.get("/", include_in_schema=False)
def root() -> dict:
    return {
        "service": "x1025 chat_api",
        "docs": "/docs",
        "health": "/api/v1/health",
        "minimal_chat": "/chat",
    }


# Throwaway minimal chat UI — served same-origin so there are no CORS / tunnel-domain
# games. Intended for end-to-end validation while the polished Next.js UI is parked.
_MINIMAL_CHAT_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>x1025 — minimal chat (debug)</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font: 14px/1.5 system-ui, sans-serif; background: #0c0d10; color: #e7e8ea; height: 100vh; display: flex; flex-direction: column; }
  header { padding: 10px 16px; border-bottom: 1px solid #23262d; display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
  header h1 { margin: 0; font-size: 13px; font-weight: 500; color: #c8cbd0; }
  .pill { display: inline-flex; align-items: center; gap: 6px; padding: 2px 8px; border: 1px solid #23262d; border-radius: 999px; font-size: 11px; color: #9aa0a8; }
  .dot { width: 6px; height: 6px; border-radius: 50%; background: #facc15; }
  .pill.open .dot { background: #34d399; }
  .pill.closed .dot { background: #f87171; }
  #meta { margin-left: auto; font-size: 11px; color: #6b7079; }
  main { flex: 1; overflow-y: auto; padding: 20px 16px; max-width: 880px; width: 100%; margin: 0 auto; }
  .turn { margin-bottom: 18px; }
  .role { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: #6b7079; margin-bottom: 4px; }
  .role.assistant { color: #34d399; }
  .body { white-space: pre-wrap; word-wrap: break-word; }
  .sources { margin-top: 8px; padding: 8px 10px; background: #15171c; border: 1px solid #23262d; border-radius: 6px; font-size: 12px; color: #9aa0a8; }
  .sources .src { margin: 4px 0; }
  .sources .label { color: #c8cbd0; font-weight: 500; }
  .err { color: #f87171; }
  footer { border-top: 1px solid #23262d; padding: 12px 16px; flex-shrink: 0; }
  .input-row { max-width: 880px; margin: 0 auto; display: flex; gap: 8px; }
  textarea { flex: 1; resize: none; padding: 10px 12px; background: #15171c; color: inherit; border: 1px solid #23262d; border-radius: 8px; font: inherit; min-height: 44px; max-height: 160px; }
  textarea:focus { outline: none; border-color: #34d399; }
  button { padding: 0 16px; background: #34d399; color: #0c0d10; border: 0; border-radius: 8px; font-weight: 600; cursor: pointer; }
  button:disabled { background: #2a2d33; color: #5a6068; cursor: not-allowed; }
</style>
</head>
<body>
<header>
  <h1>x1025 — minimal chat (debug)</h1>
  <span class="pill" id="pill"><span class="dot"></span><span id="pillLabel">Connecting</span></span>
  <span id="meta"></span>
</header>
<main id="thread"></main>
<footer>
  <div class="input-row">
    <textarea id="input" rows="1" placeholder="Connecting…" disabled></textarea>
    <button id="send" disabled>Send</button>
  </div>
</footer>
<script>
(() => {
  const pill = document.getElementById("pill");
  const pillLabel = document.getElementById("pillLabel");
  const meta = document.getElementById("meta");
  const thread = document.getElementById("thread");
  const input = document.getElementById("input");
  const send = document.getElementById("send");

  let ws = null;
  let assistantBody = null;
  let isStreaming = false;

  function setStatus(label, klass) {
    pill.className = "pill " + klass;
    pillLabel.textContent = label;
    const ready = klass === "open" && !isStreaming;
    input.disabled = !ready;
    send.disabled = !ready;
    input.placeholder = klass === "open" ? "Ask about the manual…" : (label + "…");
  }

  function appendTurn(role, text) {
    const turn = document.createElement("div");
    turn.className = "turn";
    const r = document.createElement("div");
    r.className = "role " + role;
    r.textContent = role === "user" ? "You" : "Assistant";
    const b = document.createElement("div");
    b.className = "body";
    b.textContent = text;
    turn.appendChild(r);
    turn.appendChild(b);
    thread.appendChild(turn);
    thread.scrollTop = thread.scrollHeight;
    return { turn, body: b };
  }

  function appendSources(turn, chunks) {
    if (!chunks || !chunks.length) return;
    const wrap = document.createElement("div");
    wrap.className = "sources";
    chunks.forEach((c, i) => {
      const row = document.createElement("div");
      row.className = "src";
      const label = document.createElement("span");
      label.className = "label";
      label.textContent = `[${i + 1}] ${c.section || "(no section)"} `;
      row.appendChild(label);
      row.appendChild(document.createTextNode(`(rerank ${(c.rerank_score ?? 0).toFixed(3)}) ${c.preview || ""}`));
      wrap.appendChild(row);
    });
    turn.appendChild(wrap);
  }

  function appendError(text) {
    const e = document.createElement("div");
    e.className = "turn err";
    e.textContent = "error: " + text;
    thread.appendChild(e);
  }

  async function loadHealth() {
    try {
      const res = await fetch("/api/v1/health");
      const data = await res.json();
      const flag = data.mock ? "MOCK" : "LIVE";
      meta.textContent = `${flag} · ${data.active_table || "(no table)"}`;
    } catch (e) {
      meta.textContent = "(health unavailable)";
    }
  }

  function connect() {
    setStatus("Connecting", "connecting");
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${proto}//${location.host}/api/v1/ws/chat`);
    ws.onopen = () => setStatus("Connected", "open");
    ws.onclose = () => {
      setStatus("Disconnected", "closed");
      isStreaming = false;
      setTimeout(connect, 1500);
    };
    ws.onerror = () => {};
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.type === "start") return;
      if (m.type === "sources" && assistantBody) {
        appendSources(assistantBody.turn, m.chunks);
        return;
      }
      if (m.type === "token" && assistantBody) {
        assistantBody.body.textContent += m.text;
        thread.scrollTop = thread.scrollHeight;
        return;
      }
      if (m.type === "end") {
        isStreaming = false;
        assistantBody = null;
        setStatus("Connected", "open");
        return;
      }
      if (m.type === "error") {
        isStreaming = false;
        assistantBody = null;
        appendError(m.message || "(no message)");
        setStatus("Connected", "open");
        return;
      }
    };
  }

  function submit() {
    const q = input.value.trim();
    if (!q || isStreaming || !ws || ws.readyState !== WebSocket.OPEN) return;
    appendTurn("user", q);
    assistantBody = appendTurn("assistant", "");
    isStreaming = true;
    input.disabled = true;
    send.disabled = true;
    input.value = "";
    ws.send(JSON.stringify({ type: "question", question: q }));
  }

  send.addEventListener("click", submit);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  });

  loadHealth();
  connect();
})();
</script>
</body>
</html>
"""


@app.get("/chat", include_in_schema=False, response_class=HTMLResponse)
def minimal_chat() -> HTMLResponse:
    return HTMLResponse(_MINIMAL_CHAT_HTML)
