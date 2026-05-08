"""
Layer 1 — Procedural / ISM Safety Specialist.

Owns the full Layer 1 RAG pipeline for technical maritime safety documents:

    embed query   ->  hybrid search (LanceDB)  ->  cross-encoder rerank
                                                 ->  Qwen3.6-35B-A3B (Q6_K) generate

Embedder + LanceDB primitives live in `backend/storage/lancedb_client.py`
and are shared with the ingestion write path. The reranker (Qwen3-Reranker-0.6B)
and the LLM subprocess are owned here.

Slice layout (each H200 MIG slice ~34.9 GB):
    cuda:0  -- NV-Embed-v2          (~15.7 GB) [parent, in lancedb_client]
    cuda:1  -- Qwen3-Reranker       (~16.4 GB) [parent, here]
    slice 2 -- Qwen3.6-35B-A3B Q6_K (~28-30 GB) [child subprocess, here]

The LLM is isolated in a `multiprocessing.spawn` child with CUDA_VISIBLE_DEVICES
pinned to a single MIG UUID — required because llama.cpp dedupes devices by PCI
BDF and all MIG slices share one BDF.

Override the slice index with the LLM_MIG_UUID env var.

Run as a CLI:
    # one-shot
    python -m agents.safety_agent data/lancedb/<folder>_lancedb.lance "your question"
    # retrieval only (no LLM)
    python -m agents.safety_agent --retrieve-only data/lancedb/<...>.lance "your query"

Importable:
    from agents.safety_agent import SafetyAgent
    agent = SafetyAgent.open(Path("data/lancedb/foo_lancedb.lance"))
    answer = agent.query("question")
    agent.switch_table(Path("data/lancedb/bar_lancedb.lance"))
    agent.close()
"""

import argparse
import multiprocessing as mp
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# agents/safety_agent.py -> project root is parents[1]
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_PROJECT_ROOT / ".env")
os.environ.setdefault("LANCE_LOG", "ERROR")

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from backend.storage.lancedb_client import (
    embed_query,
    hybrid_search,
    load_embed_model,
    open_table,
)

__all__ = ["SafetyAgent"]

# ---------------------------------------------------------------------------
# Reranker (Qwen3-Reranker-0.6B, cross-encoder, parent process cuda:1)
# ---------------------------------------------------------------------------

_RERANKER_ID = "Qwen/Qwen3-Reranker-0.6B"
_RERANK_PROMPT = (
    '<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct provided. '
    'Note that the answer can only be "yes" or "no".<|im_end|>\n'
    '<|im_start|>user\n'
    '<Instruct>: Given a technical question about a technical manual or report, assess whether the document contains '
    'relevant information to answer the question.\n'
    '<Query>: {query}\n<Document>: {document}<|im_end|>\n'
    '<|im_start|>assistant\n<think>\n\n</think>\n\n'
)

def _load_reranker():
    tokenizer = AutoTokenizer.from_pretrained(_RERANKER_ID, trust_remote_code=True, padding_side="left")
    device = "cuda:1" if torch.cuda.device_count() > 1 else "cuda:0"
    model = AutoModelForCausalLM.from_pretrained(_RERANKER_ID, torch_dtype=torch.float16, device_map=device).eval()
    return model, tokenizer, tokenizer.convert_tokens_to_ids("yes"), tokenizer.convert_tokens_to_ids("no")

def _rerank(reranker, query: str, candidates: list, top_n: int, batch_size: int = 16) -> list:
    model, tokenizer, yes_id, no_id = reranker
    prompts = [_RERANK_PROMPT.format(query=query, document=c["text"]) for c in candidates]
    scores = []
    for i in range(0, len(prompts), batch_size):
        inputs = tokenizer(prompts[i:i + batch_size], padding=True, truncation=True, max_length=2048,
                           return_tensors="pt", add_special_tokens=False).to(model.device)
        with torch.no_grad():
            last_logits = model(**inputs).logits[:, -1]
            scores.extend(torch.softmax(last_logits[:, [no_id, yes_id]], dim=1)[:, 1].cpu().tolist())
    for c, s in zip(candidates, scores):
        c["_rerank_score"] = s
    return sorted(candidates, key=lambda x: x["_rerank_score"], reverse=True)[:top_n]

# ---------------------------------------------------------------------------
# LLM (Qwen3.6-35B-A3B Q6_K, isolated child subprocess, single MIG slice)
# ---------------------------------------------------------------------------

_LLM_REPO = "unsloth/Qwen3.6-35B-A3B-GGUF"
_LLM_FILE = "Qwen3.6-35B-A3B-UD-Q6_K.gguf"
_LLM_CTX = 8192
_LLM_MAX_NEW_TOKENS = 1024
_LLM_SLICE_INDEX = 2
_SYSTEM_PROMPT = (
    "You are a highly precise technical assistant.\n\n"
    "Rules:\n"
    "1. Use ONLY information explicitly stated in the provided context. Do not draw on outside knowledge.\n"
    "2. Report exact values, labels, tag numbers, and steps exactly as they appear.\n"
    "3. Never infer, extrapolate, or extend beyond what is written.\n"
    "4. If the context is insufficient to answer fully, state what is and is not available.\n"
    "5. Organize your final response in a clean, highly readable manner using ONLY plain text formatting (newlines and indentation). ABSOLUTELY DO NOT use Markdown formatting such as **, *, or #."
)
# Trailing <think>\n\n</think>\n\n disables Qwen3 thinking mode (same effect as enable_thinking=False)
_PROMPT_TEMPLATE = (
    "<|im_start|>system\n{system}<|im_end|>\n"
    "<|im_start|>user\n{user}<|im_end|>\n"
    "<|im_start|>assistant\n<think>\n\n</think>\n\n"
)

def _llm_mig_uuid() -> str:
    if uuid := os.environ.get("LLM_MIG_UUID"):
        return uuid
    out = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, check=True).stdout
    uuids = re.findall(r"UUID: (MIG-[a-f0-9-]+)", out)
    if len(uuids) <= _LLM_SLICE_INDEX:
        raise RuntimeError(f"Need at least {_LLM_SLICE_INDEX + 1} MIG slices, found {len(uuids)}")
    return uuids[_LLM_SLICE_INDEX]

def _llm_worker(conn):
    from llama_cpp import Llama
    llm = Llama.from_pretrained(
        repo_id=_LLM_REPO, filename=_LLM_FILE,
        n_gpu_layers=-1, n_ctx=_LLM_CTX, verbose=False,
    )
    while True:
        try:
            prompt = conn.recv()
        except EOFError:
            break
        if prompt is None:
            break
        for chunk in llm(
            prompt,
            max_tokens=_LLM_MAX_NEW_TOKENS,
            temperature=0.7, top_p=0.8, top_k=20, presence_penalty=1.5,
            stop=["<|im_end|>"],
            stream=True,
        ):
            conn.send(chunk["choices"][0]["text"])
        conn.send(None)  # end-of-stream sentinel

def _build_prompt(query: str, chunks: list) -> str:
    parts = []
    for i, c in enumerate(chunks, 1):
        header = f"[{i}] Section: {c['section']}"
        if c["chunk_type"] == "image":
            header += f"\n[Figure: {c['image_src']}] Description:"
        parts.append(f"{header}\n{c['text']}")
    context = "\n\n---\n\n".join(parts)
    user_content = (
        "Use the following passages from the technical document or report to answer the question.\n\n"
        f"{context}\n\nQuestion: {query}"
    )
    return _PROMPT_TEMPLATE.format(system=_SYSTEM_PROMPT, user=user_content)

# ---------------------------------------------------------------------------
# SafetyAgent: lifecycle wrapper around the warm models + table handle
# ---------------------------------------------------------------------------

@dataclass
class SafetyAgent:
    embedder: object
    reranker: tuple
    table: object
    llm_proc: mp.Process
    llm_conn: object

    @classmethod
    def open(cls, table_path: Path) -> "SafetyAgent":
        embedder = load_embed_model()
        reranker = _load_reranker()
        table = open_table(table_path)
        proc, conn = cls._spawn_llm()
        return cls(embedder=embedder, reranker=reranker, table=table, llm_proc=proc, llm_conn=conn)

    @staticmethod
    def _spawn_llm() -> tuple:
        parent, child = mp.Pipe()
        saved = os.environ.get("CUDA_VISIBLE_DEVICES", "")
        os.environ["CUDA_VISIBLE_DEVICES"] = _llm_mig_uuid()
        try:
            p = mp.get_context("spawn").Process(target=_llm_worker, args=(child,))
            p.start()
        finally:
            os.environ["CUDA_VISIBLE_DEVICES"] = saved
        return p, parent

    def retrieve(self, query: str, k: int = 100, top_n: int = 15) -> list:
        vec = embed_query(self.embedder, query)
        candidates = hybrid_search(self.table, vec, query, k)
        return _rerank(self.reranker, query, candidates, top_n)

    def generate_stream(self, query: str, chunks: list):
        """Yield token chunks from the LLM as they're produced."""
        self.llm_conn.send(_build_prompt(query, chunks))
        while True:
            try:
                chunk = self.llm_conn.recv()
            except EOFError:
                raise RuntimeError(f"LLM subprocess crashed (exit code {self.llm_proc.exitcode})")
            if chunk is None:
                return
            yield chunk

    def generate(self, query: str, chunks: list) -> str:
        text = "".join(self.generate_stream(query, chunks)).strip()
        if "<think>" in text:
            end = text.find("</think>")
            if end != -1:
                text = text[end + len("</think>"):].strip()
        return text

    def query(self, question: str, k: int = 100, top_n: int = 15) -> str:
        chunks = self.retrieve(question, k=k, top_n=top_n)
        return self.generate(question, chunks)

    def switch_table(self, table_path: Path):
        self.table = open_table(table_path)

    def close(self):
        try:
            self.llm_conn.send(None)
        except (BrokenPipeError, OSError):
            pass
        self.llm_proc.join(timeout=5)
        if self.llm_proc.is_alive():
            self.llm_proc.terminate()


def _print_chunks(results: list):
    for i, r in enumerate(results, 1):
        rrf = r.get("_relevance_score") or 0.0
        print(f"\n#{i} Rerank:{r.get('_rerank_score', 0):.3f} | RRF:{rrf:.3f}\n"
              f"Type: {r.get('chunk_type', '')} | Section: {r.get('section', '')}\n"
              f"Text: {r['text'][:400].replace(chr(10), ' ')}...")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Layer 1 SafetyAgent against a LanceDB table.")
    parser.add_argument("table_path", type=Path, help="e.g. data/lancedb/my_table.lance")
    parser.add_argument("query", nargs="+", help="Query string")
    parser.add_argument("--k", type=int, default=100, help="Hybrid-search candidate pool size")
    parser.add_argument("--top-n", type=int, default=15, help="Rerank cutoff (chunks fed to LLM)")
    parser.add_argument("--retrieve-only", action="store_true", help="Skip LLM, print reranked chunks only")
    args = parser.parse_args()

    question = " ".join(args.query)

    if args.retrieve_only:
        embedder = load_embed_model()
        reranker = _load_reranker()
        table = open_table(args.table_path)
        vec = embed_query(embedder, question)
        candidates = hybrid_search(table, vec, question, args.k)
        _print_chunks(_rerank(reranker, question, candidates, args.top_n))
    else:
        agent = SafetyAgent.open(args.table_path)
        try:
            response = agent.query(question, k=args.k, top_n=args.top_n)
        finally:
            agent.close()
        print(f"\nQuestion: {question}\n")
        print("=" * 60)
        print(response)
        print("=" * 60)
