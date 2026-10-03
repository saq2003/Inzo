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

## Background daemon

INZO ships a headless background daemon — no GUI, no web server, no prompts.
It runs skill ticks (e.g. `reminders` every 60 s), natural-language schedules
from `schedules.json`, and the notification center:

```bash
python3 -m inzo.daemon --data-dir ~/.local/share/inzo
```

- **Flags:** `--data-dir` (state root), `--pid-file` (default
  `<data-dir>/inzo-daemon.pid`; refuses a second live daemon), `--webhook-url`
  (optional fan-out target).
- **Schedules:** entries in `<data-dir>/schedules.json` like
  `{"name": "morning brief", "schedule": "har subah 8 baje",
  "skill": "morning_briefing"}` are parsed by `core.nl_cron` (English +
  Hinglish: `"every 5 minutes"`, `"roz shaam 7 baje"`,
  `"every weekday at 9pm"`) and dispatched every 60 seconds. Bad entries are
  skipped, never fatal.
- **Signals:** `SIGTERM`/`SIGINT` stop jobs, drain the queue, release the PID
  file, and exit.
- **Notifications:** always persisted to a SQLite inbox
  (`GET /notifications/inbox`); optional `desktop` (plyer) and `webhook`
  fan-out channels are best-effort. Channel failures are logged, never raised.
- **Status:** `GET /daemon/status` (skill counts, scheduler jobs, queue depth),
  `POST /skills/run` (run any skill on demand).

See `docs/daemon.md` (systemd user-service example included) and
`docs/skills.md` (full catalog).

## Skill catalog

All **84 skills** (80 plugin + 4 builtin) are **background-first** — every one
declares `background = True`, so the daemon can run any of them headlessly.
62 run fully locally on the stdlib; 22 need a hardware/model/network adapter
plugged through a `Protocol` and **report honestly** when it is missing
(e.g. `"wakeword: microphone capture not configured: plug in a
MicrophoneProtocol adapter"`). This table is generated from
`skills.discovery.build_skill_registry()`, never hand-typed.

| Skill | Group | Local/Adapter | Description |
|---|---|---|---|
| `anomaly_detect` | advanced | local | Detects anomalies (z-score) in spending totals, sleep durations, and habit check-in gaps; 'check' runs a scan, hourly tick notifies. |
| `autonomous_goals` | advanced | local | Background goal pursuit: 'add <goal>' decomposes a goal into steps, the hourly tick advances steps, 'status' reports progress. |
| `conv_summarizer` | advanced | local | Extractive summarizer: 'summarize <text>' returns the key sentences as bullets and stores the summary. |
| `lan_sync` | advanced | local | Offline LAN sync protocol: 'advertise' builds this node's advertisement envelope; 'push <kind> <json>' builds a push envelope. |
| `plugin_hotreload` | advanced | local | Hot-reloads skill plugins: 'reload skills.<module>' refreshes the module in sys.modules; 'list' shows skills.* modules and SKILLS counts. |
| `predictive_reminders` | advanced | local | Learns when recurring events usually happen (hour histograms) and fires a pre-reminder 30 min before; 'status' shows patterns. |
| `privacy_firewall` | advanced | local | Privacy firewall: 'allow <skill> <host>' / 'block <skill> <host>' manage the per-skill network allowlist; 'status' shows the policy. |
| `self_learn` | advanced | local | Learns agent behavior rules from corrections: 'correct: <wrong> -> <right>', 'never do X', 'always do Y'; 'rules' lists what was learned. |
| `skill_marketplace` | advanced | local | Local skill marketplace: 'index <dir>' builds a sha256 index, 'verify <index.json> [srcdir]' re-hashes, 'install <index.json> <srcdir>' installs into skills/_thirdparty/. |
| `workflow_macros` | advanced | local | Workflow macros: 'define <name>' + YAML/JSON steps, 'run <name>' executes each step's skill in order, 'list' shows macros. |
| `calculator` | builtin | local | Evaluates arithmetic expressions deterministically. |
| `finance` | builtin | local | Runs deterministic finance calculations (Python computes). |
| `notes` | builtin | local | Saves and recalls user notes via long-term memory. |
| `time` | builtin | local | Reports the current local time. |
| `api_tester` | coding | local | Tests HTTP API endpoints from a JSON list of checks (method, url, expected status, JSON path); reports status/latency/pass-fail. |
| `codegen_debug` | coding | local | Generates Python function/class/CLI templates with syntax checking, and maps pasted tracebacks to heuristic fix suggestions. |
| `excel_regex` | coding | local | Builds regex patterns from descriptions, tests patterns against text, and generates Excel formulas (VLOOKUP/XLOOKUP/SUMIFS/INDEX-MATCH/IFERROR). |
| `mql5_builder` | coding | local | Generates a complete, valid MQL5 Expert Advisor (EMA fast/slow crossover with RSI filter, CTrade entries, SL/TP in points) from parameters. |
| `pr_reviewer` | coding | adapter | Reviews unified diffs with local heuristics (missing docstrings, debug leftovers, TODOs, oversized diffs); can fetch PR diffs from GitHub when a token-backed adapter is wired. |
| `repo_docs` | coding | local | Walks a repo directory, extracts module/class/function docstrings with ast, and emits a Markdown doc (file tree + API summary). |
| `sql_builder` | coding | local | Builds parameterized SQL SELECT statements (? placeholders + params list) with strict identifier validation; rejects injection attempts. |
| `chat_drafts` | comms | local | Drafts short chat messages from tone templates (formal, friendly, hinglish, apology, followup): 'draft <tone> <what it is about>'. |
| `followup_tracker` | comms | local | Tracks 'follow up with <who> about <what> in <N> days' (also Hinglish) and notifies when reminders come due on the hourly tick. |
| `morning_briefing` | comms | local | Builds a morning briefing from today's calendar events, cached news headlines, and weather (via adapter); notifies once delivered. |
| `send_message` | comms | adapter | Queues outbound messages durably ('send <to> <text>'), lists the outbox, and flushes it through a plugged sender. Delivery is only ever claimed when the provider confirms it. |
| `translator` | comms | local | Translates English<->Hindi word-by-word from a built-in dictionary (unknown words pass through); direction auto-detected from script. |
| `whatsapp_bot` | comms | adapter | Normalizes WhatsApp inbound webhooks (Twilio-style or generic) with message-id dedupe. Outbound delivery needs a WhatsAppProvider and is never faked. |
| `app_launcher` | desktop | adapter | Keeps a name->app-id alias registry and launches apps only through a pluggable AppLauncher adapter; never uses subprocess (Rule 12). |
| `clipboard_history` | desktop | local | Keeps a local in-memory ring buffer (max 100) of clipboard entries with put/history/search/clear; OS clipboard access goes through a pluggable ClipboardBackend. |
| `file_organizer` | desktop | local | Organizes a directory's files into organized/<ext>/<YYYY-MM>/ buckets; dry-run by default, 'confirm' executes, 'undo' restores; never deletes; refuses system paths. |
| `gui_automation` | desktop | adapter | Validates GUI actions (allowlisted kinds, coordinate bounds, key allowlist), logs them append-only to gui_actions.db, and executes via a pluggable GuiDriver. |
| `hotkey` | desktop | adapter | Registers global hotkeys with normalization and conflict detection (persisted); OS-level listening needs a plugged-in GlobalHotkey adapter. |
| `screen_qa` | desktop | adapter | Answers questions about the current screen: routes the question, caches answers, and uses pluggable ScreenCapture/VisionModel adapters (honest 'not configured' path when missing). |
| `tray_app` | desktop | adapter | Shows desktop notifications and manages tray state through a pluggable TrayHost adapter; falls back to NotificationCenter or plain text when headless. |
| `backtester` | finance | local | Backtests a strategy: 'run <csvpath> [fast] [slow]' reads a date,open,high,low,close csv, builds SMA-crossover signals, and reports total return %, max drawdown %, win rate, and trade count on Rs 100000. |
| `budget_alerts` | finance | local | Budget guardrails: 'set <category> <amount>' stores a monthly budget; the hourly tick compares it against this month's expenses and notifies when a category hits 80% (warning) or 100% (exceeded). |
| `expense_tracker` | finance | local | Tracks expenses: 'add <amount> <description>' stores a categorized expense, 'import <csvpath>' loads a date,description,amount CSV, 'report [YYYY-MM]' shows totals by category. |
| `loan_planner` | finance | local | Loan planner: 'schedule <principal> <annual_rate_pct> <months>' shows the EMI, total interest, total payable, and the first/last schedule rows. |
| `networth` | finance | local | Net-worth ledger: 'add <account> <amount>' records an asset, 'liability <name> <amount>' records a liability, 'show' reports assets, liabilities, and net worth. |
| `portfolio_tracker` | finance | adapter | Portfolio ledger: 'add <ticker> <qty> <avg_cost>' records a holding (repeat adds average down/up), 'value' prices every holding with the configured PriceFeedProtocol adapter and shows value plus P&L. |
| `price_alerts` | finance | adapter | Price watches: 'watch <ticker> above\|below <price>' stores an alert, 'list' shows active watches; the 5-minute tick fetches prices through the configured PriceFeedProtocol adapter and notifies on a crossing. |
| `tax_india` | finance | local | Income-tax estimator: 'compute <income>' shows the new-regime breakdown for FY 2025-26 (slabs, Rs 75000 standard deduction, 87A rebate); add 'nonsalaried' to skip the standard deduction. |
| `diet_log` | health | local | Logs meals (name, kcal, optional protein) and reports today's totals against a configurable daily calorie target. |
| `med_reminders` | health | local | Keeps a list of medications with daily dose times and notifies when a dose is due (15-minute window, one reminder per day per dose). |
| `mood_tracker` | health | local | Logs mood (1-5) with an optional note and computes weekly trends: average, minimum, and the streak of days at mood 4 or better. |
| `sleep_analysis` | health | local | Parses a sleep CSV export (start_iso,end_iso[,quality]) and reports average duration, bedtime variance, and a 0-100 consistency score. |
| `workout_planner` | health | local | Builds a structured weekly workout plan from a built-in exercise database by goal (strength\|cardio\|general), level, and days/week. |
| `appliance_schedule` | home | adapter | Schedules appliances with on/off times, dispatches plug state changes on a 60-second tick, and estimates daily energy use in kWh. |
| `camera_qa` | home | adapter | Ask questions about what the home camera sees and log motion events. Needs a CameraFeed + VisionModel adapter; without them it reports not-configured and only records the query. |
| `lights_control` | home | adapter | Controls smart lights via scenes and validated commands. Needs a LightHub adapter; without one it reports not-configured. |
| `temp_monitor` | home | adapter | Samples a temperature sensor on a 10-minute tick, logs readings, and notifies when temperature crosses configurable high/low limits. |
| `auto_journal` | memory | local | Builds a daily journal digest from events and habit check-ins. |
| `episodic_memory` | memory | local | Append-only episodic event log with keyword and time recall. |
| `goals_habits` | memory | local | Weekly goals with check-ins and streak computation. |
| `memory_nl_search` | memory | local | NL memory search with time-expression parsing across sources. |
| `people_graph` | memory | local | Stores people, their relations, and per-person preferences. |
| `pref_learn` | memory | local | Learns preferences from corrections like 'no, I meant X'. |
| `calendar_local` | productivity | local | Local calendar: 'add <title> \| <start_iso> \| <end_iso>' stores an event (warns on overlap), 'list [YYYY-MM-DD]' shows events, 'delete <id>' removes one. |
| `daily_planner` | productivity | local | Morning briefing: 'today' builds the plan from today's calendar events, the top 3 tasks by priority score, and habits when present. The daily tick sends it as a notification. |
| `email_triage` | productivity | adapter | Email triage: 'rule add sender\|subject <pattern> -> <label>' stores a classification rule, 'rule list' shows rules, 'triage [limit]' fetches messages through the configured EmailProvider adapter and labels them. |
| `focus_pomodoro` | productivity | local | Focus timer: 'start' begins a 25-minute focus block, 'status' shows the current phase and remaining time, 'stop' resets. The 60-second tick advances phases and notifies on transitions. |
| `meeting_finder` | productivity | local | Free-slot finder: 'find <minutes> [YYYY-MM-DD]' scans 09:00-18:00 on the given day (default today), skips events from the local calendar, and returns the first free slots long enough for the meeting. |
| `reminders` | productivity | local | Local reminders: 'add in <N> minutes <text>', 'add at HH:MM <text>', or Hinglish '<N> minute me yaad dilao <text>'; 'list' shows pending. The 60-second tick fires due reminders and marks them done. |
| `smart_notes` | productivity | local | Smart notes: 'save <text>' stores a note with auto-generated keyword tags (top 5 by frequency, stopwords removed), 'search <query>' finds matching notes. |
| `task_prioritizer` | productivity | local | Task manager: 'add <title> [importance 1-5] [due <iso>] [effort <min>]' stores a task, 'prioritize' ranks open tasks by score (importance*2 + due urgency - effort/60), 'done <id>' completes one. |
| `deep_research` | research | local | Researches a topic across up to 5 fetched pages (URLs from the message or Wikipedia search), ranks by keyword overlap, and returns a brief with numbered citations. |
| `doc_qa` | research | local | Indexes .txt/.md files ('index <dir>') into paragraph chunks and answers questions ('ask <question>') with file:chunk citations. |
| `factcheck` | research | local | Extracts checkable claims (numbers, quotes, superlatives) from text and compares each against fetched sources with honest confidence wording. |
| `market_research` | research | local | Builds a market brief (Overview/Audience/Competitors/Pricing/Channels/Risks) from up to 4 fetched pages, with citations. |
| `news_digest` | research | local | Maintains an RSS/Atom cache ('digest' refreshes and shows top 8 headlines; 'feeds' lists sources; 'feed add <url>' adds one). |
| `study_notes` | research | local | Converts text into study notes: detected headings, key points, a glossary of 'X is Y' definitions, and fill-in-the-blank quiz questions. |
| `video_summary` | research | adapter | Fetches a video transcript through a plugged TranscriptProvider and returns an extractive summary (frequency-scored sentences). |
| `local_only_mode` | security | local | Controls the network guard: 'on' blocks ALL network access for ALL skills (local_only mode); 'off' restores normal mode; 'status' reports the current mode. |
| `password_audit` | security | local | Audits a password (after the 'audit ' prefix) against common passwords and scores it 0-100 by length, character classes, and entropy. The password is never stored, logged, or echoed. |
| `secret_vault` | security | local | Stores secrets obfuscated at rest with a PBKDF2-derived key (NOT authenticated encryption — plug cryptography Fernet via the VaultCipher Protocol for production). Plaintext is never stored. |
| `voice_lock` | security | adapter | Locks sensitive actions behind voice biometrics with a real local PIN fallback: PBKDF2-hashed PIN, constant-time verification, and a 10-minute lockout after 5 failed attempts. |
| `farfield_listen` | voice | adapter | Far-field capture with SNR-based microphone selection. |
| `meeting_recorder` | voice | local | Records meeting transcripts and produces extractive summaries. |
| `speaker_id` | voice | adapter | Enrolls voiceprints and identifies speakers by cosine similarity. |
| `voice_clone` | voice | adapter | Consent-gated voice cloning with a pluggable synthesis engine. |
| `voice_emotion` | voice | local | Lexicon-based emotion scoring (joy, sadness, anger, fear, surprise). |
| `voice_multilingual` | voice | local | Transliterates Devanagari and normalizes Hinglish voice text. |
| `voice_realtime` | voice | adapter | Realtime voice turn manager with barge-in interruption handling. |
| `wakeword` | voice | adapter | Energy-gated wake-word listening with a pluggable keyword spotter. |

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
