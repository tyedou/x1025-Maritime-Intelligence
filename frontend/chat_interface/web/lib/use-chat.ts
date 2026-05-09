"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { chatWebSocketUrl } from "./api";
import type { Message, SourceChunk, WsServerMsg } from "./types";

const RECONNECT_MS = 1500;

type Status = "connecting" | "open" | "closed";

export interface UseChatResult {
  messages: Message[];
  status: Status;
  isStreaming: boolean;
  send: (question: string) => void;
  reset: () => void;
}

export function useChat(): UseChatResult {
  const [messages, setMessages] = useState<Message[]>([]);
  const [status, setStatus] = useState<Status>("connecting");
  const [isStreaming, setIsStreaming] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const activeAssistantId = useRef<string | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const shouldReconnect = useRef(true);

  const handleServerMessage = useCallback((msg: WsServerMsg) => {
    if (msg.type === "start") {
      // Nothing to do — assistant message was created when send() was called.
      return;
    }

    if (msg.type === "sources") {
      const id = activeAssistantId.current;
      if (!id) return;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === id ? { ...m, sources: msg.chunks as SourceChunk[] } : m,
        ),
      );
      return;
    }

    if (msg.type === "token") {
      const id = activeAssistantId.current;
      if (!id) return;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === id ? { ...m, content: m.content + msg.text } : m,
        ),
      );
      return;
    }

    if (msg.type === "end") {
      const id = activeAssistantId.current;
      activeAssistantId.current = null;
      setIsStreaming(false);
      if (id) {
        setMessages((prev) =>
          prev.map((m) => (m.id === id ? { ...m, streaming: false } : m)),
        );
      }
      return;
    }

    if (msg.type === "error") {
      const id = activeAssistantId.current;
      activeAssistantId.current = null;
      setIsStreaming(false);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === id
            ? { ...m, streaming: false, error: msg.message }
            : m,
        ),
      );
      return;
    }
  }, []);

  const connect = useCallback(() => {
    if (typeof window === "undefined") return;
    if (
      wsRef.current &&
      (wsRef.current.readyState === WebSocket.OPEN ||
        wsRef.current.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    setStatus("connecting");
    const ws = new WebSocket(chatWebSocketUrl());
    wsRef.current = ws;

    ws.onopen = () => setStatus("open");
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data) as WsServerMsg;
        handleServerMessage(data);
      } catch (err) {
        console.error("ws parse error", err);
      }
    };
    ws.onclose = () => {
      setStatus("closed");
      setIsStreaming(false);
      if (shouldReconnect.current) {
        reconnectTimer.current = setTimeout(connect, RECONNECT_MS);
      }
    };
    ws.onerror = () => {
      // onclose will fire next; reconnect is handled there.
    };
  }, [handleServerMessage]);

  useEffect(() => {
    shouldReconnect.current = true;
    connect();
    return () => {
      shouldReconnect.current = false;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [connect]);

  const send = useCallback(
    (question: string) => {
      const trimmed = question.trim();
      if (!trimmed) return;
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      if (isStreaming) return;

      const userId = crypto.randomUUID();
      const assistantId = crypto.randomUUID();
      activeAssistantId.current = assistantId;
      setIsStreaming(true);

      setMessages((prev) => [
        ...prev,
        { id: userId, role: "user", content: trimmed },
        { id: assistantId, role: "assistant", content: "", streaming: true },
      ]);

      ws.send(JSON.stringify({ type: "question", question: trimmed }));
    },
    [isStreaming],
  );

  const reset = useCallback(() => {
    setMessages([]);
    activeAssistantId.current = null;
    setIsStreaming(false);
  }, []);

  return { messages, status, isStreaming, send, reset };
}
