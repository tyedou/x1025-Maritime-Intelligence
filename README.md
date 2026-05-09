# x1025-Maritime-Intelligence

**Autonomous Maritime Intelligence — multi-layer agent system over self-hosted models.**

This repository is the production home for the x1025 maritime AI stack. It builds on the Layer 1 RAG prototype (originally `x1025-maritime-rag`) and extends it with: a router/specialist agent system, a dynamic-data pipeline, IoT integration, and a SaaS frontend.

The Layer 1 RAG pipeline is **production-grade**: it ingests, searches, and reasons over highly technical maritime engineering manuals (e.g. the *N.S. SAVANNAH Safety Analysis Report*) and returns 100% grounded answers without hallucinating — a critical requirement under the ISM Code.

## Repository layout

Only files that currently exist in the repo are listed below. Empty directories (kept via `.gitkeep`) are placeholders for upcoming work.

```
x1025-Maritime-Intelligence/
├── agents/
│   └── safety_agent.py           # Layer 1 — Procedural/ISM specialist (RAG)
│
├── backend/
│   ├── ingestion/
│   │   ├── docling_parser.py     # PDF → Markdown via Docling
│   │   └── vision_captioner.py   # InternVL2.5-38B-AWQ image-to-text
│   ├── storage/
│   │   └── lancedb_client.py     # NV-Embed-v2 + macro-chunker + LanceDB hybrid search
│   └── stream/                   # (empty — dynamic-data ingestion to come)
│
├── frontend/
│   ├── chat_interface/
│   │   └── cli.py                # Interim Python REPL — warm-loads SafetyAgent, supports `switch`
│   ├── dashboard/                # (empty — TS/React fleet-overview UI to come)
│   └── agent_monitor/            # (empty — agent-thinking visualizer to come)
│
├── hardware/
│   └── raspberry_pi/             # (empty — Pi sensor + telemetry scripts to come)
│
├── infra/
│   └── model_configs/
│       └── README.md             # Notes for upcoming per-model YAML configs
│
├── tests/                        # (empty — pytest scaffolding to come)
├── data/                         # Raw PDFs + ingestion outputs (gitignored)
├── assets/                       # (empty — README screenshots to come)
│
├── .env.example                  # HF_HOME / HF_TOKEN / OPENAI_* template
├── .gitignore
├── LICENSE
├── README.md
├── requirements.txt              # Top-level deps (use environment.yml for exact lock)
└── environment.yml               # Conda lockfile (canonical)
```

### What's implemented today (Layer 1)

The four files marked ✅ above form a complete, runnable RAG pipeline:

* **`backend/ingestion/docling_parser.py`** — converts a PDF to `manual.md` + `images/` + `image_manifest.json`. Uses Docling with native-text extraction (no OCR), table-structure parsing, and a heavy navigation/header-noise scrubber for marine-manual artifacts (e.g. `PREVIOUS PAGE`, page numbers, revision stamps). Replaces inline image refs with `<!-- IMAGE_PLACEHOLDER -->` blocks for the captioner to fill.
* **`backend/ingestion/vision_captioner.py`** — walks the manifest, runs **InternVL2.5-38B-AWQ** (via `lmdeploy` Turbomind, tp=1, 8K context) over each non-trivial image with a marine-engineering-specific prompt, detects refusal/empty outputs, sanitizes embedded HTML-comment markers, and writes descriptions back into both the manifest and the markdown placeholders. Skips images <5 KB as decorative.
* **`backend/storage/lancedb_client.py`** — owns the shared **NV-Embed-v2** embedder, the macro-chunker (1000-word cap, 5-line overlap, header-aware sectioning, image-chunk type), the `_SCHEMA` (text + 4096-d vector + section + chunk_type + image fields), the FTS index, and `hybrid_search()` (cosine + BM25 fused via `RRFReranker`). Patches the upstream `modeling_nvembed.py` on first load to fix two transformers incompatibilities (rotary embeddings not threaded through gradient checkpointing; KV-cache tensor handling). Used by both the ingestion write path and the agent read path.
* **`agents/safety_agent.py`** — the `SafetyAgent` lifecycle wrapper. Loads the embedder + **Qwen3-Reranker-0.6B** in the parent process, spawns the **Qwen3.6-35B-A3B Q6_K** (`llama.cpp`) generator in a `multiprocessing.spawn` child pinned to one MIG slice via `CUDA_VISIBLE_DEVICES`, exposes `retrieve()` / `generate()` / `query()` / `switch_table()` / `close()`. Also provides a `--retrieve-only` CLI for inspecting reranked chunks without spinning up the LLM.
* **`frontend/chat_interface/cli.py`** — interim REPL. Lists `data/lancedb/*.lance`, prompts the user to pick one, warm-loads `SafetyAgent` once, and supports a `switch` command that swaps the table without reloading any model.

## Layer 1 — Key architectural innovations (RAG pipeline)

* **Macro-Chunking:** Instead of naive line-splitting, we group text under shared Markdown headers up to a strict 1000-word limit, with a 5-line overlap on splits. This keeps large tables ingested as single, cohesive units, preventing fragmentation of rows from their column headers.
* **Vision-Language Processing:** We bypass faulty OCR and extract pristine native text via Docling. For diagrams, **InternVL2.5-38B-AWQ** translates imagery into highly accurate text descriptions, which are then embedded directly back into the Markdown source.
* **Three-Stage Hybrid Retrieval & Generation:**
  * **Stage 1 (Recall)** — `LanceDB` hybrid search combining `NV-Embed-v2` cosine similarity with BM25, fused via Reciprocal Rank Fusion, fetches up to 100 candidates.
  * **Stage 2 (Precision)** — `Qwen3-Reranker-0.6B` cross-encoder scores each candidate via yes/no logits and extracts the top-N.
  * **Stage 3 (Synthesis)** — locally-hosted `Qwen3.6-35B-A3B` (Q6_K GGUF, ~29 GB) generates a strictly grounded answer over the reranked context, with thinking mode disabled for deterministic output.
* **Multi-Slice GPU Orchestration:** Embedder, reranker, and generator are pinned to separate MIG slices. The LLM runs in an isolated child subprocess because `llama.cpp` dedupes devices by PCI BDF — all MIG slices share one BDF, so single-slice pinning only works when the slice is the only one visible to the process.
* **100% Self-Hosted Security:** Designed specifically to run on local **NVIDIA H200 MIG slices**. No sensitive fleet data or proprietary company manuals are ever sent to third-party APIs.

## Hardware requirements

* **Minimum:** 3× NVIDIA H200 MIG slices (each ~`1g.35gb`, ~34.9 GB VRAM), or equivalent GPUs with combined ~105 GB of VRAM.
* **Slice layout at runtime:**
  * `cuda:0` — NV-Embed-v2 (~15.7 GB) — parent process
  * `cuda:1` — Qwen3-Reranker (~16.4 GB) — parent process
  * slice 2 — Qwen3.6-35B-A3B Q6_K (~28–30 GB) — child subprocess, single-slice pinned
* **Why three slices?** llama.cpp's BDF deduplication forces the LLM into a process where only one MIG slice is visible. Override the slice index with `LLM_MIG_UUID` if needed.
* **Slurm:** request `--gres=gpu:3` minimum.

## Installation & setup

```bash
# Clone the repository
git clone https://github.com/tyedou/x1025-Maritime-Intelligence.git
cd x1025-Maritime-Intelligence

# Create the Conda environment from the exported file
conda env create -f environment.yml

# Activate the environment
conda activate x1025
```

`llama-cpp-python` must be built with CUDA support for the generation stage:

```bash
CMAKE_ARGS="-DGGML_CUDA=on" pip install llama-cpp-python --no-cache-dir \
    --force-reinstall --no-binary=llama-cpp-python
```

Copy `.env.example` to `.env` and configure `HF_HOME` and `HF_TOKEN` so HuggingFace models download to your designated persistent cache (~45 GB for the SafetyAgent retrieval+generation path; ~80 GB total if you also run ingestion, since InternVL2.5-38B-AWQ adds ~35 GB more).

## Quickstart — Layer 1 RAG

All commands run from the repository root.

### Phase 1: Data ingestion & indexing

Place your raw PDF in `data/`, then run the three ingestion stages in order:

1. **PDF → Markdown** — Docling extracts native text and saves diagrams as PNGs.
   ```bash
   python -m backend.ingestion.docling_parser data/<file-name>.pdf --output-dir data/<output-dir>
   ```
2. **Vision extraction** — InternVL2.5-38B-AWQ describes each image and writes back into `manual.md`.
   ```bash
   python -m backend.ingestion.vision_captioner data/<output-dir>
   ```
3. **Embedding & indexing** — Macro-chunks the markdown, embeds with `NV-Embed-v2`, writes to `data/lancedb/<folder>_lancedb.lance` with FTS index for hybrid search.
   ```bash
   python -m backend.storage.lancedb_client data/<output-dir>
   ```

### Phase 2: Querying & generation

**Interactive chat (recommended)** — loads all three models once and keeps them warm. Switch manuals without reloading.
```bash
python -m frontend.chat_interface.cli
```
Inside the chat: type a question, `switch` to pick a different manual, or `quit`/Ctrl+D to exit.

**Web chat (ChatGPT-style UI)** — Next.js + Tailwind frontend that
streams answers from a FastAPI bridge wrapping the same `SafetyAgent`. Two
shells:

```bash
# shell 1 — backend (real GPU mode)
uvicorn backend.chat_api.main:app --reload --port 8001

# shell 1 — backend (mock mode for UI dev, no GPU)
CHAT_API_MOCK=1 uvicorn backend.chat_api.main:app --reload --port 8001

# shell 2 — frontend
cd frontend/chat_interface/web
npm install   # first time only
npm run dev
```

Open `http://localhost:3000`. If `localhost:3000` doesn't reach your browser
(some networks intercept SSH port forwarding), use `scripts/demo.sh` instead —
it exposes the backend over a public cloudflared tunnel and serves a minimal
same-origin chat at `/chat` for debugging. When the Next.js frontend lives
behind a different origin than the backend, set `NEXT_PUBLIC_CHAT_API_URL`
before `npm run dev` so the browser fetches and the WebSocket target the
right host. See `backend/chat_api/README.md` and
`frontend/chat_interface/web/README.md` for the wire protocol and component
layout.

**One-shot CLI** — useful for scripted evaluation or single questions.
```bash
python -m agents.safety_agent data/lancedb/<folder>_lancedb.lance "your question here"
```

**Retrieval only (no generation)** — inspect reranked chunks without spinning up the LLM.
```bash
python -m agents.safety_agent --retrieve-only data/lancedb/<folder>_lancedb.lance "your query"
```

### Quick demo (one command)

For a reproducible demo on chimera, `scripts/demo.sh` boots uvicorn, waits for
the SafetyAgent to load, starts a public cloudflared tunnel, and prints the
`/chat` URL. Ctrl+C in the shell shuts down both processes cleanly.

```bash
# from a chimera login shell — open an interactive GPU allocation
salloc -c2 -A impact -q aicore --gres=gpu:4 --mem=32G \
       -w chimera24 -p AICORE_H200 -t 720

# inside the allocation
cd ~/x1025_fi/x1025-Maritime-Intelligence
./scripts/demo.sh
```

The script prints a `https://*.trycloudflare.com/chat` URL — open it in any
browser. Trycloudflare URLs are random and ephemeral; for a stable URL,
configure a named cloudflared tunnel under your own Cloudflare account.

`MOCK=1 ./scripts/demo.sh` skips the GPU pipeline and serves canned answers
(useful for verifying the wire without holding a SLURM allocation). Other
knobs: `PORT=…`, `CONDA_ENV=…`, `CLOUDFLARED=/path/to/binary`. Logs land in
`/tmp/x1025-demo/`.

Prerequisite (one-time, per host): a `cloudflared` binary somewhere on disk
(`wget` it from `github.com/cloudflare/cloudflared/releases/latest`) and an
ingested LanceDB table at `data/lancedb/*.lance` (Phase 1 above).

## Performance demonstration

The pipeline has been extensively tested against the *N.S. SAVANNAH Safety Analysis Report*. By combining Macro-Chunking with a cross-encoder reranker and a strictly-grounded generator, the system extracts and synthesizes correct answers from highly complex, tabular engineering data where standard RAG systems fail.

Screenshots from the prototype runs (`assets/performance_1.png`, `assets/performance_2.png`) will be re-added here once the prototype assets are migrated into this repo.

## Engineering "war stories"

Building this pipeline involved solving several real limitations of modern LLMs and toolchains:

* **Token truncation.** Embedding models silently amputated the bottom 200 tokens of 1500-word chunks. Fixed by reducing chunk thresholds to 1000 words.
* **NV-Embed-v2 patches.** The upstream `modeling_nvembed.py` had multiple incompatibilities with current `transformers` (rotary embeddings not threaded through gradient checkpointing, KV-cache tensor handling). `backend/storage/lancedb_client.py` patches the cached file in-place on first load — see `patch_nvembed()`.
* **MIG slice pinning for llama.cpp.** All MIG slices on an H200 share a single PCI BDF, which `llama.cpp` deduplicates. We isolate the LLM in a `multiprocessing.spawn` child with `CUDA_VISIBLE_DEVICES` pinned to a single slice UUID — the only reliable way to run llama.cpp on one MIG partition while the parent uses the others.
* **Ground-truth discrepancies.** When the LLM supposedly "failed" test queries, programmatic PDF-extraction scripts proved the LLM was actually 100% correct — the expected test answers were factually missing from the original source documents.

## Project status

| Layer | Component | Status |
|------|-----------|--------|
| 1 | `agents/safety_agent.py` (RAG) | ✅ Working (migrated from prototype) |
| 1 | `backend/ingestion/docling_parser.py` | ✅ Working |
| 1 | `backend/ingestion/vision_captioner.py` | ✅ Working |
| 1 | `backend/storage/lancedb_client.py` | ✅ Working |
| 1 | `frontend/chat_interface/cli.py` (interim Python REPL) | ✅ Working |
| 1 | `backend/chat_api/` (FastAPI WebSocket bridge to SafetyAgent) | ✅ Working |
| 1 | `frontend/chat_interface/web/` (Next.js + Tailwind + shadcn chat UI) | ✅ Working |
| 2 | `agents/analytics_agent.py`, `backend/stream/`, `backend/storage/timeseries_db.py` | ⏸ Not yet scaffolded |
| 3 | `agents/superintendent.py` | ⏸ Stretch goal |
| — | `agents/supervisor.py` | ⏸ Not yet scaffolded |
| — | `frontend/{dashboard,chat_interface (TS/React),agent_monitor}/` | 🚧 Empty — TS/React UI pending |
| — | `hardware/raspberry_pi/` | 🚧 Empty — Pi sensor scripts pending |
| — | `infra/model_configs/` | 🚧 Placeholder + README; configs to be extracted from hard-coded constants |
| — | `infra/docker-compose.yml` | ⏸ Optional, not yet authored |
| — | `tests/` | 🚧 Empty — pytest scaffolding pending |

---
*Developed for the IMPACT Program — UMass Boston Venture Development Center*
