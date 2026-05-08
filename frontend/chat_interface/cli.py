"""
Interactive chat CLI (interim).

Loads the SafetyAgent (NV-Embed + Qwen3-Reranker in parent, Qwen3.6-35B-A3B Q6_K
in a child subprocess pinned to one MIG slice) ONCE, then runs an input loop with
warm models.

Commands inside the chat:
    switch  -- pick a different manual (models stay loaded)
    quit    -- exit (also: q, exit, Ctrl+D, Ctrl+C)

NOTE: This is the interim Python CLI used while the agent backend stabilizes.
The production user-facing chat experience will be the TypeScript/React UI under
`frontend/chat_interface/` once that's built.

Run from project root:
    python -m frontend.chat_interface.cli
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# frontend/chat_interface/cli.py -> project root is parents[2]
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env")
os.environ.setdefault("LANCE_LOG", "ERROR")

from agents.safety_agent import SafetyAgent

__all__ = ["chat"]

_DB_DIR = _PROJECT_ROOT / "data" / "lancedb"


def _list_manuals() -> list:
    if not _DB_DIR.is_dir():
        sys.exit(f"Error: {_DB_DIR} not found.")
    manuals = sorted(t.name[:-6] for t in _DB_DIR.iterdir() if t.is_dir() and t.name.endswith(".lance"))
    if not manuals:
        sys.exit(f"Error: No tables in {_DB_DIR}.")
    return manuals


def _pick_manual(manuals: list) -> str:
    print("\nAvailable manuals:")
    for i, name in enumerate(manuals, 1):
        print(f"  {i}. {name}")
    while True:
        try:
            choice = input(f"\nPick a manual (1-{len(manuals)}, or q to quit): ").strip()
        except (EOFError, KeyboardInterrupt):
            sys.exit(0)
        if choice.lower() in {"q", "quit", "exit"}:
            sys.exit(0)
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(manuals):
                return manuals[idx]
        except ValueError:
            pass
        print(f"Invalid. Pick a number between 1 and {len(manuals)}.")


def chat():
    manuals = _list_manuals()
    table_name = _pick_manual(manuals)

    print(f"\nLoading models for '{table_name}' (~3 min on first run)...")
    agent = SafetyAgent.open(_DB_DIR / f"{table_name}.lance")
    print("\nReady. Type a question. Commands: 'switch' / 'quit'.")

    try:
        while True:
            try:
                query = input(f"\n[{table_name}] > ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not query:
                continue
            if query.lower() in {"q", "quit", "exit"}:
                break
            if query.lower() == "switch":
                table_name = _pick_manual(manuals)
                agent.switch_table(_DB_DIR / f"{table_name}.lance")
                continue

            print("  Retrieving + reranking...", flush=True)
            chunks = agent.retrieve(query, k=50, top_n=5)
            print("  Generating...\n", flush=True)
            print(agent.generate(query, chunks))
    finally:
        agent.close()
        print("\nGoodbye.")


if __name__ == "__main__":
    chat()
