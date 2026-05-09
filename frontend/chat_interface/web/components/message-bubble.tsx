"use client";

import { useState } from "react";
import { AlertCircle, BookOpen, ChevronDown, User } from "lucide-react";

import { Separator } from "@/components/ui/separator";
import type { Message } from "@/lib/types";
import { cn } from "@/lib/utils";

interface MessageBubbleProps {
  message: Message;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  if (message.role === "user") return <UserMessage message={message} />;
  return <AssistantMessage message={message} />;
}

function UserMessage({ message }: MessageBubbleProps) {
  return (
    <div className="msg-enter flex justify-end">
      <div className="flex max-w-[85%] items-start gap-3">
        <div className="rounded-2xl rounded-tr-sm bg-primary px-4 py-3 text-sm text-primary-foreground shadow-sm">
          <p className="whitespace-pre-wrap leading-relaxed">{message.content}</p>
        </div>
        <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-secondary text-secondary-foreground">
          <User className="h-3.5 w-3.5" />
        </div>
      </div>
    </div>
  );
}

function AssistantMessage({ message }: MessageBubbleProps) {
  const [showSources, setShowSources] = useState(false);
  const sources = message.sources ?? [];

  return (
    <div className="msg-enter flex gap-3">
      <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-400">
        <span className="text-xs font-semibold">x</span>
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-xs font-medium text-muted-foreground">
          Safety Specialist
        </div>

        {message.content && (
          <div
            className={cn(
              "mt-1 whitespace-pre-wrap text-sm leading-relaxed text-foreground",
              message.streaming && "streaming-cursor",
            )}
          >
            {message.content}
          </div>
        )}

        {!message.content && message.streaming && !message.error && (
          <div className="mt-2 flex items-center gap-2 text-sm text-muted-foreground">
            <ThinkingDots />
            <span>{sources.length ? "Generating answer…" : "Searching the manual…"}</span>
          </div>
        )}

        {message.error && (
          <div className="mt-2 flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive-foreground">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span className="leading-relaxed">{message.error}</span>
          </div>
        )}

        {sources.length > 0 && (
          <div className="mt-3 rounded-lg border border-border bg-card/50">
            <button
              onClick={() => setShowSources((v) => !v)}
              className="flex w-full items-center justify-between gap-2 px-3 py-2 text-xs text-muted-foreground hover:text-foreground"
            >
              <span className="inline-flex items-center gap-2">
                <BookOpen className="h-3.5 w-3.5" />
                {sources.length} source{sources.length === 1 ? "" : "s"}
              </span>
              <ChevronDown
                className={cn(
                  "h-3.5 w-3.5 transition-transform",
                  showSources && "rotate-180",
                )}
              />
            </button>
            {showSources && (
              <div className="border-t border-border p-2">
                <ul className="space-y-2">
                  {sources.map((s, i) => (
                    <li
                      key={i}
                      className="rounded-md bg-background/60 px-3 py-2 text-xs leading-relaxed"
                    >
                      <div className="mb-1 flex items-center justify-between text-muted-foreground">
                        <span className="truncate font-medium text-foreground">
                          {s.section || "(no section)"}
                        </span>
                        <span className="ml-2 shrink-0 rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">
                          {s.rerank_score.toFixed(3)}
                        </span>
                      </div>
                      <p className="text-muted-foreground">{s.preview}</p>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function ThinkingDots() {
  return (
    <span className="inline-flex gap-1">
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted-foreground [animation-delay:0ms]" />
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted-foreground [animation-delay:150ms]" />
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted-foreground [animation-delay:300ms]" />
    </span>
  );
}
