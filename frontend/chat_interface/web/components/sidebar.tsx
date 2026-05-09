"use client";

import { useEffect, useState } from "react";
import { Anchor, Database, Plus, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { fetchHealth, fetchTables, selectTable, type TableInfo } from "@/lib/api";
import { cn } from "@/lib/utils";

interface SidebarProps {
  onNewChat: () => void;
}

export function Sidebar({ onNewChat }: SidebarProps) {
  const [tables, setTables] = useState<TableInfo[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [mock, setMock] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(false);
  const [busyPath, setBusyPath] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [health, list] = await Promise.all([
        fetchHealth().catch(() => null),
        fetchTables(),
      ]);
      setTables(list.tables);
      setActive(list.active);
      setMock(health?.mock ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "failed to load");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const onSelect = async (path: string) => {
    if (busyPath || path === active) return;
    setBusyPath(path);
    setError(null);
    try {
      const res = await selectTable(path);
      setActive(res.active);
      setTables((prev) =>
        prev.map((t) => ({ ...t, is_active: t.path === res.active })),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "failed to switch");
    } finally {
      setBusyPath(null);
    }
  };

  return (
    <aside className="flex h-full w-72 shrink-0 flex-col border-r border-border bg-card">
      <div className="flex items-center gap-2 px-4 py-4">
        <Anchor className="h-5 w-5 text-primary" />
        <div className="leading-tight">
          <div className="text-sm font-semibold">x1025 Maritime</div>
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
            Intelligence — Layer 1
          </div>
        </div>
      </div>

      <Separator />

      <div className="px-3 py-3">
        <Button
          variant="secondary"
          className="w-full justify-start gap-2"
          onClick={onNewChat}
        >
          <Plus className="h-4 w-4" /> New chat
        </Button>
      </div>

      <Separator />

      <div className="flex items-center justify-between px-4 py-3">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-muted-foreground">
          <Database className="h-3.5 w-3.5" />
          Knowledge base
        </div>
        <button
          aria-label="Refresh tables"
          onClick={() => void load()}
          className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
        </button>
      </div>

      <ScrollArea className="flex-1 px-2">
        {error && (
          <div className="mx-2 mb-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive-foreground">
            {error}
          </div>
        )}
        {!error && tables.length === 0 && !loading && (
          <div className="mx-2 mt-1 rounded-md border border-dashed border-border px-3 py-3 text-xs leading-relaxed text-muted-foreground">
            No tables in <code className="rounded bg-muted px-1">data/lancedb/</code>.
            Index a manual via{" "}
            <code className="rounded bg-muted px-1">
              python -m backend.storage.lancedb_client …
            </code>{" "}
            or run the API in mock mode.
          </div>
        )}
        <ul className="space-y-0.5 px-1 pb-3">
          {tables.map((t) => {
            const isActive = t.path === active;
            const isBusy = busyPath === t.path;
            return (
              <li key={t.path}>
                <button
                  disabled={isBusy}
                  onClick={() => void onSelect(t.path)}
                  className={cn(
                    "group flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm transition-colors",
                    isActive
                      ? "bg-accent text-accent-foreground"
                      : "text-muted-foreground hover:bg-accent/40 hover:text-foreground",
                  )}
                >
                  <span className="truncate">{t.name}</span>
                  {isActive && (
                    <span className="ml-2 rounded-full bg-primary/20 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-primary-foreground/90">
                      active
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      </ScrollArea>

      <Separator />
      <div className="px-4 py-3 text-[11px] leading-relaxed text-muted-foreground">
        {mock === true && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-yellow-500/10 px-2 py-0.5 text-yellow-400">
            <span className="h-1.5 w-1.5 rounded-full bg-yellow-400" />
            Mock mode — UI dev only
          </span>
        )}
        {mock === false && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2 py-0.5 text-emerald-400">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
            Live agent
          </span>
        )}
        {mock === null && <span>API offline</span>}
      </div>
    </aside>
  );
}
