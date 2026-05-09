# Web chat interface

Next.js 14 + TypeScript + Tailwind + shadcn-style components. Streams answers
from the `backend/chat_api` FastAPI bridge, which wraps the Layer 1 `SafetyAgent`.

## First-time setup

Node 20 is installed via the `x1025` conda env (see top-level README).

```bash
cd frontend/chat_interface/web
npm install
```

## Run (UI dev — no GPU required)

In one shell, boot the backend in mock mode:

```bash
CHAT_API_MOCK=1 uvicorn backend.chat_api.main:app --reload --port 8001
```

In another shell, start the Next.js dev server:

```bash
cd frontend/chat_interface/web
npm run dev
```

Open `http://localhost:3000`. VS Code Remote-SSH auto-forwards the port to your
local browser.

## Run (real GPU mode)

Same as above, but drop `CHAT_API_MOCK=1`. Requires 3 H200 MIG slices and at
least one indexed table in `data/lancedb/`. The agent loads on backend startup
against the first table found; switch tables from the sidebar.

## Layout

```
app/
  layout.tsx       Dark-mode shell, fonts, global CSS
  page.tsx         Mounts <Sidebar/> + <Chat/>
  globals.css      Tailwind + design tokens (HSL custom properties)
components/
  chat.tsx           Top-level chat surface (header, scroll thread, input)
  sidebar.tsx        Knowledge-base picker, mock/live status, "new chat"
  message-bubble.tsx User vs assistant rendering, streaming cursor, sources
  input-bar.tsx      Auto-sizing textarea, Enter to send, Shift+Enter newline
  ui/                shadcn-style primitives (Button, Textarea, ScrollArea, Separator)
lib/
  api.ts       REST client (health, tables, select)
  use-chat.ts  WebSocket hook with auto-reconnect, streaming state
  types.ts     Message + WS protocol types
  utils.ts     cn() helper
```

## Configuration

`NEXT_PUBLIC_CHAT_API_URL` (default `http://localhost:8001`) controls where the
UI looks for the backend. Copy `.env.local.example` to `.env.local` to override.

## How streaming works

The `useChat` hook opens a WebSocket to `/api/v1/ws/chat` and translates the
backend's message envelope (`start` → `sources` → `token`* → `end`) into React
state. Each token append re-renders only the active assistant bubble; auto-scroll
follows the bottom of the thread.

The connection auto-reconnects every 1.5s if the backend goes down. The "New
chat" button remounts `<Chat/>`, clearing history and re-opening the socket.
