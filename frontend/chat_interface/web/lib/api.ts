/**
 * REST client for the chat_api backend (default http://localhost:8001).
 * Override with NEXT_PUBLIC_CHAT_API_URL.
 */

const API_URL =
  process.env.NEXT_PUBLIC_CHAT_API_URL ?? "http://localhost:8001";

export interface TableInfo {
  name: string;
  path: string;
  is_active: boolean;
}

export interface TableListResponse {
  tables: TableInfo[];
  active: string | null;
}

export interface HealthResponse {
  status: "ok" | "loading" | "error";
  agent_loaded: boolean;
  active_table: string | null;
  mock: boolean;
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_URL}/api/v1/health`);
  if (!res.ok) throw new Error(`health ${res.status}`);
  return res.json();
}

export async function fetchTables(): Promise<TableListResponse> {
  const res = await fetch(`${API_URL}/api/v1/tables`);
  if (!res.ok) throw new Error(`tables ${res.status}`);
  return res.json();
}

export async function selectTable(path: string): Promise<{ active: string }> {
  const res = await fetch(`${API_URL}/api/v1/tables/select`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`select ${res.status}: ${body}`);
  }
  return res.json();
}

export function chatWebSocketUrl(): string {
  const httpUrl = new URL(API_URL);
  const wsProto = httpUrl.protocol === "https:" ? "wss:" : "ws:";
  return `${wsProto}//${httpUrl.host}/api/v1/ws/chat`;
}
