"use client";

import { useEffect, useRef } from "react";
import { ArrowUp, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

interface InputBarProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  disabled?: boolean;
  isStreaming?: boolean;
  placeholder?: string;
}

export function InputBar({
  value,
  onChange,
  onSubmit,
  disabled,
  isStreaming,
  placeholder,
}: InputBarProps) {
  const ref = useRef<HTMLTextAreaElement | null>(null);

  // Autosize the textarea (capped at ~6 rows).
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  }, [value]);

  const handleKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!disabled && value.trim()) onSubmit();
    }
  };

  return (
    <div className="mx-auto w-full max-w-3xl">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!disabled && value.trim()) onSubmit();
        }}
        className="relative rounded-2xl border border-border bg-card shadow-lg shadow-black/20 focus-within:border-ring"
      >
        <Textarea
          ref={ref}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKey}
          placeholder={placeholder ?? "Ask about the manual…"}
          rows={1}
          className="min-h-[56px] max-h-[200px] w-full resize-none border-0 bg-transparent py-4 pl-4 pr-14 text-sm leading-relaxed shadow-none focus-visible:ring-0 focus-visible:ring-offset-0"
        />
        <div className="absolute bottom-2 right-2">
          <Button
            type="submit"
            size="icon"
            disabled={disabled || !value.trim()}
            className="h-9 w-9 rounded-xl"
            aria-label="Send"
          >
            {isStreaming ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <ArrowUp className="h-4 w-4" />
            )}
          </Button>
        </div>
      </form>
      <p className="mt-2 text-center text-[11px] text-muted-foreground">
        Answers are grounded only in the active manual. Press Enter to send,
        Shift+Enter for a newline.
      </p>
    </div>
  );
}
