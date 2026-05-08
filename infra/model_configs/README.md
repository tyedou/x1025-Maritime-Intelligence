# Model Configs

Drop per-model YAML / JSON configs here:

- `nv-embed-v2.yaml` — NV-Embed-v2 (Layer 1 retrieval embedder)
- `qwen3-reranker.yaml` — Qwen/Qwen3-Reranker-0.6B
- `qwen3.6-35b-a3b.yaml` — Qwen3.6-35B-A3B Q6_K (Layer 1 generator, llama.cpp)
- `internvl2.5-38b-awq.yaml` — InternVL2.5-38B-AWQ (vision captioner)

TODO: extract the model IDs / paths / GPU placement constants currently hard-coded
in `backend/storage/lancedb_client.py`, `agents/safety_agent.py`, and
`backend/ingestion/vision_captioner.py` into per-model configs once the layout
stabilizes.
