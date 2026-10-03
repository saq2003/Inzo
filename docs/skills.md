# INZO Skill Catalog

INZO ships with **84 skills** (80 plugin skills + 4 builtin), all of them
**background-first**: every skill declares `background = True`, so the
headless daemon (`python -m inzo.daemon`) can run any of them without a
terminal, display, or user present.

## Local vs adapter skills

- **62 fully-local skills** run on the standard library only. They read/write
  SQLite stores under the data dir and never touch the network.
- **22 adapter skills** need hardware, a model, or a network service plugged
  in through a `Protocol` interface. Without a configured adapter they
  **never fake results** — they report honestly, e.g.
  `"wakeword: microphone capture not configured: plug in a MicrophoneProtocol adapter"`.

See `docs/adapters.md` for how to plug real adapters in, and
`docs/daemon.md` for how the daemon schedules and ticks these skills.

## Full catalog

| Skill | Group | Background | Local/Adapter | Description |
|---|---|---|---|---|
| `anomaly_detect` | advanced | yes | local | Detects anomalies (z-score) in spending totals, sleep durations, and habit check-in gaps; 'check' runs a scan, hourly tick notifies. |
| `autonomous_goals` | advanced | yes | local | Background goal pursuit: 'add <goal>' decomposes a goal into steps, the hourly tick advances steps, 'status' reports progress. |
| `conv_summarizer` | advanced | yes | local | Extractive summarizer: 'summarize <text>' returns the key sentences as bullets and stores the summary. |
| `lan_sync` | advanced | yes | local | Offline LAN sync protocol: 'advertise' builds this node's advertisement envelope; 'push <kind> <json>' builds a push envelope. |
| `plugin_hotreload` | advanced | yes | local | Hot-reloads skill plugins: 'reload skills.<module>' refreshes the module in sys.modules; 'list' shows skills.* modules and SKILLS counts. |
| `predictive_reminders` | advanced | yes | local | Learns when recurring events usually happen (hour histograms) and fires a pre-reminder 30 min before; 'status' shows patterns. |
| `privacy_firewall` | advanced | yes | local | Privacy firewall: 'allow <skill> <host>' / 'block <skill> <host>' manage the per-skill network allowlist; 'status' shows the policy. |
| `self_learn` | advanced | yes | local | Learns agent behavior rules from corrections: 'correct: <wrong> -> <right>', 'never do X', 'always do Y'; 'rules' lists what was learned. |
| `skill_marketplace` | advanced | yes | local | Local skill marketplace: 'index <dir>' builds a sha256 index, 'verify <index.json> [srcdir]' re-hashes, 'install <index.json> <srcdir>' installs into skills/_thirdparty/. |
| `workflow_macros` | advanced | yes | local | Workflow macros: 'define <name>' + YAML/JSON steps, 'run <name>' executes each step's skill in order, 'list' shows macros. |
| `calculator` | builtin | yes | local | Evaluates arithmetic expressions deterministically. |
| `finance` | builtin | yes | local | Runs deterministic finance calculations (Python computes). |
| `notes` | builtin | yes | local | Saves and recalls user notes via long-term memory. |
| `time` | builtin | yes | local | Reports the current local time. |
| `api_tester` | coding | yes | local | Tests HTTP API endpoints from a JSON list of checks (method, url, expected status, JSON path); reports status/latency/pass-fail. |
| `codegen_debug` | coding | yes | local | Generates Python function/class/CLI templates with syntax checking, and maps pasted tracebacks to heuristic fix suggestions. |
| `excel_regex` | coding | yes | local | Builds regex patterns from descriptions, tests patterns against text, and generates Excel formulas (VLOOKUP/XLOOKUP/SUMIFS/INDEX-MATCH/IFERROR). |
| `mql5_builder` | coding | yes | local | Generates a complete, valid MQL5 Expert Advisor (EMA fast/slow crossover with RSI filter, CTrade entries, SL/TP in points) from parameters. |
| `pr_reviewer` | coding | yes | adapter | Reviews unified diffs with local heuristics (missing docstrings, debug leftovers, TODOs, oversized diffs); can fetch PR diffs from GitHub when a token-backed adapter is wired. |
| `repo_docs` | coding | yes | local | Walks a repo directory, extracts module/class/function docstrings with ast, and emits a Markdown doc (file tree + API summary). |
| `sql_builder` | coding | yes | local | Builds parameterized SQL SELECT statements (? placeholders + params list) with strict identifier validation; rejects injection attempts. |
| `chat_drafts` | comms | yes | local | Drafts short chat messages from tone templates (formal, friendly, hinglish, apology, followup): 'draft <tone> <what it is about>'. |
| `followup_tracker` | comms | yes | local | Tracks 'follow up with <who> about <what> in <N> days' (also Hinglish) and notifies when reminders come due on the hourly tick. |
| `morning_briefing` | comms | yes | local | Builds a morning briefing from today's calendar events, cached news headlines, and weather (via adapter); notifies once delivered. |
| `send_message` | comms | yes | adapter | Queues outbound messages durably ('send <to> <text>'), lists the outbox, and flushes it through a plugged sender. Delivery is only ever claimed when the provider confirms it. |
| `translator` | comms | yes | local | Translates English<->Hindi word-by-word from a built-in dictionary (unknown words pass through); direction auto-detected from script. |
| `whatsapp_bot` | comms | yes | adapter | Normalizes WhatsApp inbound webhooks (Twilio-style or generic) with message-id dedupe. Outbound delivery needs a WhatsAppProvider and is never faked. |
| `app_launcher` | desktop | yes | adapter | Keeps a name->app-id alias registry and launches apps only through a pluggable AppLauncher adapter; never uses subprocess (Rule 12). |
| `clipboard_history` | desktop | yes | local | Keeps a local in-memory ring buffer (max 100) of clipboard entries with put/history/search/clear; OS clipboard access goes through a pluggable ClipboardBackend. |
| `file_organizer` | desktop | yes | local | Organizes a directory's files into organized/<ext>/<YYYY-MM>/ buckets; dry-run by default, 'confirm' executes, 'undo' restores; never deletes; refuses system paths. |
| `gui_automation` | desktop | yes | adapter | Validates GUI actions (allowlisted kinds, coordinate bounds, key allowlist), logs them append-only to gui_actions.db, and executes via a pluggable GuiDriver. |
| `hotkey` | desktop | yes | adapter | Registers global hotkeys with normalization and conflict detection (persisted); OS-level listening needs a plugged-in GlobalHotkey adapter. |
| `screen_qa` | desktop | yes | adapter | Answers questions about the current screen: routes the question, caches answers, and uses pluggable ScreenCapture/VisionModel adapters (honest 'not configured' path when missing). |
| `tray_app` | desktop | yes | adapter | Shows desktop notifications and manages tray state through a pluggable TrayHost adapter; falls back to NotificationCenter or plain text when headless. |
| `backtester` | finance | yes | local | Backtests a strategy: 'run <csvpath> [fast] [slow]' reads a date,open,high,low,close csv, builds SMA-crossover signals, and reports total return %, max drawdown %, win rate, and trade count on Rs 100000. |
| `budget_alerts` | finance | yes | local | Budget guardrails: 'set <category> <amount>' stores a monthly budget; the hourly tick compares it against this month's expenses and notifies when a category hits 80% (warning) or 100% (exceeded). |
| `expense_tracker` | finance | yes | local | Tracks expenses: 'add <amount> <description>' stores a categorized expense, 'import <csvpath>' loads a date,description,amount CSV, 'report [YYYY-MM]' shows totals by category. |
| `loan_planner` | finance | yes | local | Loan planner: 'schedule <principal> <annual_rate_pct> <months>' shows the EMI, total interest, total payable, and the first/last schedule rows. |
| `networth` | finance | yes | local | Net-worth ledger: 'add <account> <amount>' records an asset, 'liability <name> <amount>' records a liability, 'show' reports assets, liabilities, and net worth. |
| `portfolio_tracker` | finance | yes | adapter | Portfolio ledger: 'add <ticker> <qty> <avg_cost>' records a holding (repeat adds average down/up), 'value' prices every holding with the configured PriceFeedProtocol adapter and shows value plus P&L. |
| `price_alerts` | finance | yes | adapter | Price watches: 'watch <ticker> above\|below <price>' stores an alert, 'list' shows active watches; the 5-minute tick fetches prices through the configured PriceFeedProtocol adapter and notifies on a crossing. |
| `tax_india` | finance | yes | local | Income-tax estimator: 'compute <income>' shows the new-regime breakdown for FY 2025-26 (slabs, Rs 75000 standard deduction, 87A rebate); add 'nonsalaried' to skip the standard deduction. |
| `diet_log` | health | yes | local | Logs meals (name, kcal, optional protein) and reports today's totals against a configurable daily calorie target. |
| `med_reminders` | health | yes | local | Keeps a list of medications with daily dose times and notifies when a dose is due (15-minute window, one reminder per day per dose). |
| `mood_tracker` | health | yes | local | Logs mood (1-5) with an optional note and computes weekly trends: average, minimum, and the streak of days at mood 4 or better. |
| `sleep_analysis` | health | yes | local | Parses a sleep CSV export (start_iso,end_iso[,quality]) and reports average duration, bedtime variance, and a 0-100 consistency score. |
| `workout_planner` | health | yes | local | Builds a structured weekly workout plan from a built-in exercise database by goal (strength\|cardio\|general), level, and days/week. |
| `appliance_schedule` | home | yes | adapter | Schedules appliances with on/off times, dispatches plug state changes on a 60-second tick, and estimates daily energy use in kWh. |
| `camera_qa` | home | yes | adapter | Ask questions about what the home camera sees and log motion events. Needs a CameraFeed + VisionModel adapter; without them it reports not-configured and only records the query. |
| `lights_control` | home | yes | adapter | Controls smart lights via scenes and validated commands. Needs a LightHub adapter; without one it reports not-configured. |
| `temp_monitor` | home | yes | adapter | Samples a temperature sensor on a 10-minute tick, logs readings, and notifies when temperature crosses configurable high/low limits. |
| `auto_journal` | memory | yes | local | Builds a daily journal digest from events and habit check-ins. |
| `episodic_memory` | memory | yes | local | Append-only episodic event log with keyword and time recall. |
| `goals_habits` | memory | yes | local | Weekly goals with check-ins and streak computation. |
| `memory_nl_search` | memory | yes | local | NL memory search with time-expression parsing across sources. |
| `people_graph` | memory | yes | local | Stores people, their relations, and per-person preferences. |
| `pref_learn` | memory | yes | local | Learns preferences from corrections like 'no, I meant X'. |
| `calendar_local` | productivity | yes | local | Local calendar: 'add <title> \| <start_iso> \| <end_iso>' stores an event (warns on overlap), 'list [YYYY-MM-DD]' shows events, 'delete <id>' removes one. |
| `daily_planner` | productivity | yes | local | Morning briefing: 'today' builds the plan from today's calendar events, the top 3 tasks by priority score, and habits when present. The daily tick sends it as a notification. |
| `email_triage` | productivity | yes | adapter | Email triage: 'rule add sender\|subject <pattern> -> <label>' stores a classification rule, 'rule list' shows rules, 'triage [limit]' fetches messages through the configured EmailProvider adapter and labels them. |
| `focus_pomodoro` | productivity | yes | local | Focus timer: 'start' begins a 25-minute focus block, 'status' shows the current phase and remaining time, 'stop' resets. The 60-second tick advances phases and notifies on transitions. |
| `meeting_finder` | productivity | yes | local | Free-slot finder: 'find <minutes> [YYYY-MM-DD]' scans 09:00-18:00 on the given day (default today), skips events from the local calendar, and returns the first free slots long enough for the meeting. |
| `reminders` | productivity | yes | local | Local reminders: 'add in <N> minutes <text>', 'add at HH:MM <text>', or Hinglish '<N> minute me yaad dilao <text>'; 'list' shows pending. The 60-second tick fires due reminders and marks them done. |
| `smart_notes` | productivity | yes | local | Smart notes: 'save <text>' stores a note with auto-generated keyword tags (top 5 by frequency, stopwords removed), 'search <query>' finds matching notes. |
| `task_prioritizer` | productivity | yes | local | Task manager: 'add <title> [importance 1-5] [due <iso>] [effort <min>]' stores a task, 'prioritize' ranks open tasks by score (importance*2 + due urgency - effort/60), 'done <id>' completes one. |
| `deep_research` | research | yes | local | Researches a topic across up to 5 fetched pages (URLs from the message or Wikipedia search), ranks by keyword overlap, and returns a brief with numbered citations. |
| `doc_qa` | research | yes | local | Indexes .txt/.md files ('index <dir>') into paragraph chunks and answers questions ('ask <question>') with file:chunk citations. |
| `factcheck` | research | yes | local | Extracts checkable claims (numbers, quotes, superlatives) from text and compares each against fetched sources with honest confidence wording. |
| `market_research` | research | yes | local | Builds a market brief (Overview/Audience/Competitors/Pricing/Channels/Risks) from up to 4 fetched pages, with citations. |
| `news_digest` | research | yes | local | Maintains an RSS/Atom cache ('digest' refreshes and shows top 8 headlines; 'feeds' lists sources; 'feed add <url>' adds one). |
| `study_notes` | research | yes | local | Converts text into study notes: detected headings, key points, a glossary of 'X is Y' definitions, and fill-in-the-blank quiz questions. |
| `video_summary` | research | yes | adapter | Fetches a video transcript through a plugged TranscriptProvider and returns an extractive summary (frequency-scored sentences). |
| `local_only_mode` | security | yes | local | Controls the network guard: 'on' blocks ALL network access for ALL skills (local_only mode); 'off' restores normal mode; 'status' reports the current mode. |
| `password_audit` | security | yes | local | Audits a password (after the 'audit ' prefix) against common passwords and scores it 0-100 by length, character classes, and entropy. The password is never stored, logged, or echoed. |
| `secret_vault` | security | yes | local | Stores secrets obfuscated at rest with a PBKDF2-derived key (NOT authenticated encryption — plug cryptography Fernet via the VaultCipher Protocol for production). Plaintext is never stored. |
| `voice_lock` | security | yes | adapter | Locks sensitive actions behind voice biometrics with a real local PIN fallback: PBKDF2-hashed PIN, constant-time verification, and a 10-minute lockout after 5 failed attempts. |
| `farfield_listen` | voice | yes | adapter | Far-field capture with SNR-based microphone selection. |
| `meeting_recorder` | voice | yes | local | Records meeting transcripts and produces extractive summaries. |
| `speaker_id` | voice | yes | adapter | Enrolls voiceprints and identifies speakers by cosine similarity. |
| `voice_clone` | voice | yes | adapter | Consent-gated voice cloning with a pluggable synthesis engine. |
| `voice_emotion` | voice | yes | local | Lexicon-based emotion scoring (joy, sadness, anger, fear, surprise). |
| `voice_multilingual` | voice | yes | local | Transliterates Devanagari and normalizes Hinglish voice text. |
| `voice_realtime` | voice | yes | adapter | Realtime voice turn manager with barge-in interruption handling. |
| `wakeword` | voice | yes | adapter | Energy-gated wake-word listening with a pluggable keyword spotter. |
