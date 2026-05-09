"use client";

import { useEffect, useRef, useState } from "react";
import { Compass } from "lucide-react";

import { InputBar } from "@/components/input-bar";
import { MessageBubble } from "@/components/message-bubble";
import { useChat } from "@/lib/use-chat";

const STARTER_PROMPTS = [
  "What is the SCRAM procedure for the reactor?",
  "Summarize emergency cooling system requirements.",
  "How does the safety analysis address loss-of-coolant scenarios?",
  "List the ISM Code obligations referenced in the manual.",
];

export function Chat() {
  const { messages, status, isStreaming, send } = useChat();
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Auto-scroll to bottom on new messages / streaming tokens.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const onSubmit = () => {
    if (!draft.trim() || isStreaming) return;
    send(draft);
    setDraft("");
  };

  const empty = messages.length === 0;

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-border px-6 py-3">
        <div className="flex items-center gap-2">
          <Compass className="h-4 w-4 text-muted-foreground" />
          <h1 className="text-sm font-medium">Procedural / ISM Specialist</h1>
        </div>
        <ConnectionPill status={status} />
      </header>

      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl px-6 py-8">
          {empty ? (
            <EmptyState
              onPick={(p) => {
                setDraft(p);
              }}
            />
          ) : (
            <div className="space-y-6">
              {messages.map((m) => (
                <MessageBubble key={m.id} message={m} />
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="border-t border-border bg-background/80 px-6 py-4 backdrop-blur">
        <InputBar
          value={draft}
          onChange={setDraft}
          onSubmit={onSubmit}
          disabled={isStreaming || status !== "open"}
          isStreaming={isStreaming}
          placeholder={
            status !== "open"
              ? "Connecting to chat_api…"
              : "Ask about the manual…"
          }
        />
      </div>
    </div>
  );
}

function ConnectionPill({ status }: { status: "connecting" | "open" | "closed" }) {
  const map = {
    connecting: { label: "Connecting", color: "bg-yellow-400" },
    open: { label: "Connected", color: "bg-emerald-400" },
    closed: { label: "Disconnected", color: "bg-red-400" },
  } as const;
  const { label, color } = map[status];
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground">
      <span className={`h-1.5 w-1.5 rounded-full ${color}`} />
      {label}
    </span>
  );
}

function EmptyState({ onPick }: { onPick: (p: string) => void }) {
  return (
    <div className="flex flex-col items-center justify-center pt-16 text-center">
      <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-emerald-500/10 text-emerald-400">
        <Compass className="h-6 w-6" />
      </div>
      <h2 className="text-2xl font-semibold tracking-tight">
        How can I help with the manual?
      </h2>
      <p className="mt-2 max-w-md text-sm text-muted-foreground">
        Layer 1 of the x1025 stack: hybrid retrieval, cross-encoder reranking,
        and a strictly-grounded local LLM. Pick a manual in the sidebar to begin.
      </p>

      <div className="mt-10 grid w-full max-w-2xl grid-cols-1 gap-2 sm:grid-cols-2">
        {STARTER_PROMPTS.map((p) => (
          <button
            key={p}
            onClick={() => onPick(p)}
            className="rounded-lg border border-border bg-card px-4 py-3 text-left text-sm text-muted-foreground transition-colors hover:border-ring hover:bg-accent hover:text-foreground"
          >
            {p}
          </button>
        ))}
      </div>
    </div>
  );
}
