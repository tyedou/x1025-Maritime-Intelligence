# Chat API

Thin FastAPI bridge between the web chat UI (`frontend/chat_interface/web/`) and
the Layer 1 `SafetyAgent`. Streams LLM tokens over WebSocket so the browser
renders them live.

## Run modes

### Real GPU mode
Requires the same hardware as `agents/safety_agent.py` (3 H200 MIG slices).
The agent loads on startup against the first table found in `data/lancedb/`.

```bash
uvicorn backend.chat_api.main:app --reload --port 8001
```

### Mock mode (UI development)
Streams a canned answer instead of invoking the real LLM. Use this to iterate
on the chat UI without booting the GPU pipeline.

```bash
CHAT_API_MOCK=1 uvicorn backend.chat_api.main:app --reload --port 8001
```

## Endpoints

| Method | Path                       | Purpose                                     |
|--------|----------------------------|---------------------------------------------|
| GET    | `/api/v1/health`           | Service status, active table, mock flag     |
| GET    | `/api/v1/tables`           | List `data/lancedb/*.lance`                 |
| POST   | `/api/v1/tables/select`    | Switch active table (mirrors CLI `switch`)  |
| WS     | `/api/v1/ws/chat`          | Send `{question, k?, top_n?}`, receive `start` → `sources` → `token`* → `end` |

## WebSocket protocol

**Client → server**

```json
{ "type": "question", "question": "...", "k": 100, "top_n": 15 }
```

**Server → client (in order)**

```json
{ "type": "start",   "table": "/abs/path/to/table.lance" }
{ "type": "sources", "chunks": [{ "section": "...", "preview": "...", "rerank_score": 0.91 }, ...] }
{ "type": "token",   "text": "partial " }
{ "type": "token",   "text": "answer " }
{ "type": "end" }
```

Errors are returned as `{ "type": "error", "message": "..." }` and the connection
stays open (you can ask another question).

## Concurrency

The LLM child subprocess accepts one prompt at a time. Concurrent requests
serialize through an `asyncio.Lock` — fine for single-user demos. If multi-user
becomes a goal, swap the lock for a queue and a worker pool.
