# INZO

**INZO** is a Python-first, modular, local-capable, model-agnostic personal AI
assistant. Python 3.12+ is the primary language for everything: AI
orchestration, LLM integration, NLP, reasoning, planning, memory, RAG,
embeddings, vector search, speech-to-text, audio preprocessing,
text-to-speech, voice activity detection, finance math, web research,
automation, file/document processing, tool execution, the plugin/skill
system, scheduling, background workers, security, logging, testing, and the
API backend.

Design goals:

- **Local-first** — runs fully offline with zero paid services. The default
  model adapter (`local-echo`), STT/TTS, embeddings, vector store, and
  database are all deterministic local implementations.
- **Model-agnostic** — providers are never hard-coded. Every engine (LLM,
  STT, TTS, VAD, embeddings, vector DB, fetcher, vision) sits behind a
  `Protocol`/abstract interface and is registered by name.
- **Safe by construction** — deny-by-default permissions, capability checks
  before every tool call, timeouts on external calls, and *no shell tool*:
  arbitrary shell commands can never be executed from natural-language input.
- **Deterministic where it matters** — finance math runs in Python with
  `Decimal`; the model interprets and explains, Python computes.

## Architecture

```
Python
├── FastAPI / API Layer          app/            chat, voice, memory, tasks,
│                                                skills, tools, settings, health, status
├── Pydantic / Schemas           app/schemas.py
├── AsyncIO / Async execution    workers/        InProcessQueue, Scheduler
├── AI Model Router              core/router.py  named adapters, no hard-coded providers
├── Agent Orchestrator           core/agent.py   intent → plan → execute → verify
├── Memory Manager               memory/         short-term, long-term, vector retrieval
├── RAG Engine                   memory/retrieval.py + workers/tasks.index_documents
├── Skill Registry               skills/         intent-matched plugin behaviors
├── Tool Registry                tools/          permission-checked, timeout-bound tools
├── Permission Manager           security/       deny-by-default capabilities
├── Voice Pipeline               voice/          VAD → denoise → STT → agent → TTS
├── Finance Engine               intelligence/finance/  Decimal math (EMI, XIRR, budgets…)
├── Research Engine              intelligence/research/ pluggable fetcher + summarizer
├── Automation Engine            workers/        background + scheduled jobs
└── Storage Layer                storage/        protocols + SQLite local default
```

## Quickstart

```bash
# 1. Clone / enter the project
cd INZO

# 2. Developer startup: creates .venv, installs, runs the server
bash scripts/dev.sh
# → http://127.0.0.1:8000  (docs at /docs)

# Or manually:
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env   # optional
.venv/bin/python -m inzo        # same as: .venv/bin/python -m app.main
```

Try it:

```bash
curl -X POST localhost:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "calculate (2+3)*4"}'

curl -X POST localhost:8000/api/tools/finance_calc/execute \
  -H 'Content-Type: application/json' \
  -d '{"args": {"request": "emi principal=500000 rate=9 months=60"}}'
```

## Testing, lint, typecheck

```bash
.venv/bin/pytest                 # full suite (offline, no services)
.venv/bin/ruff check .            # lint
.venv/bin/mypy app core memory voice intelligence skills tools security storage workers inzo config
.venv/bin/python scripts/smoke.py # offline smoke test
```

## Swapping model engines / adapters

Nothing about a vendor is hard-coded. To plug in a real backend:

1. **LLM** — implement `core.protocols.LLMAdapter`
   (`async def generate(...) -> LLMResponse`), then
   `router.register(MyAdapter())` and `router.route_kind("chat", "my-model")`.
   Set `INZO_LLM_PROVIDER=my-model`. Keep API keys in the environment
   (`security.secrets.get_secret`), never in code.
2. **STT / TTS / VAD** — implement `voice.protocols.STTEngine`,
   `TTSEngine`, or `VADProtocol` and pass the engine to `VoicePipeline(...)`
   in `app/dependencies.py`.
3. **Embeddings / vector DB** — implement
   `storage.protocols.VectorStore` (and a real embedder replacing
   `memory.vector_store.HashEmbedding`).
4. **Storage** — implement `storage.protocols.KeyValueStore` /
   `DocumentStore` to replace the SQLite default.
5. **Web research** — implement `intelligence.research.engine.Fetcher`.

See `docs/adapters.md` for worked examples.

## Configuration

Environment variables (see `.env.example`); secrets stay out of Git:

| Variable | Default | Purpose |
|---|---|---|
| `INZO_ENV` | `development` | environment name |
| `INZO_LOG_LEVEL` | `INFO` | structured JSON log level |
| `INZO_DATA_DIR` | `./data` | SQLite + file storage root |
| `INZO_HOST` / `INZO_PORT` | `127.0.0.1` / `8000` | server bind |
| `INZO_LLM_PROVIDER` | `local-echo` | model adapter name |
| `INZO_STT_CONFIDENCE_THRESHOLD` | `0.6` | below → ask to repeat, never fabricate |

## API overview

| Method & path | Purpose |
|---|---|
| `GET /health` | liveness |
| `GET /api/status` | uptime, provider, subsystem counts |
| `POST /api/chat` | agent turn: intent → plan → tools → verify |
| `POST /api/voice/process` | voice pipeline (audio or pre-transcribed) |
| `POST /api/memory/store` / `POST /api/memory/recall` / `GET /api/memory/stats` | memory |
| `POST /api/tasks`, `GET /api/tasks`, `GET /api/tasks/{id}` | background jobs |
| `GET /api/skills`, `POST /api/skills/{name}/enable\|disable` | skills |
| `GET /api/tools`, `POST /api/tools/{name}/execute` | tools |
| `GET /api/settings`, `PUT /api/settings` | non-secret runtime settings |

Full reference: `docs/api.md`.

## Project layout

```
INZO/
├── app/            FastAPI app, config, DI wiring, schemas, routers
├── core/           agent orchestrator, planner, reasoning, verifier, model router
├── memory/         manager, short-term, long-term, vector store, retrieval
├── voice/          pipeline, VAD, denoise, STT, TTS, wake-word (protocols + local stubs)
├── intelligence/   nlp/, finance/, research/, vision/, coding/
├── skills/         plugin system + built-in skills
├── tools/          tool registry + deterministic built-in tools (no shell tool)
├── security/       permission manager, secrets, validation
├── storage/        protocols + SQLite local stores
├── workers/        async task queue, scheduler, background task functions
├── tests/          pytest suite (unit, integration, safety, e2e)
├── scripts/        dev.sh (startup), smoke.py
├── config/         static defaults
├── docs/           architecture, adapters, api, security
└── .github/        CI: pytest + ruff + mypy
```

## The 15 design rules (enforced)

1. Stdlib first (`sqlite3`, `asyncio`, `ast`, `audioop`, `decimal`…).
2. Third-party deps only where meaningful (FastAPI/Pydantic/uvicorn for the API).
3. Dependencies replaceable via protocols.
4. No hard-coded model providers. 5. No hard-coded API keys.
6. Interfaces/protocols/ABCs for swappable parts.
7. Async for I/O. 8. CPU-heavy work off the event loop.
9. Timeouts on external calls. 10. Retry policies with limits (voice STT retry).
11. Tests for every critical component. 12. Never execute shell from NL input.
13. Permission checks before tool execution. 14. Secrets outside Git.
15. Runnable locally without paid services.

## License

MIT — see `LICENSE`.
