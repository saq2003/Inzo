# INZO API reference

Base URL: `http://127.0.0.1:8000`. Interactive docs at `/docs`.

## Health & status

- `GET /health` → `{"status": "ok", "app": "INZO", "version": "0.1.0"}`
- `GET /api/status` → uptime, env, LLM provider, tool/skill/memory/task counts

## Chat

`POST /api/chat` — body: `{"message": str, "actor": "user", "session_id": null}`

Runs the full agent turn (intent → plan → tool execution → verification)
and returns `reply`, `intent`, `plan_steps`, `tool_calls`, `verified`,
`issues`.

## Voice

`POST /api/voice/process` — body: `{"audio_base64": str|null,
"transcript": str|null, "confidence": float|null, "actor": "user"}`

- `audio_base64`: 16-bit PCM mono frames → full pipeline (VAD → STT → agent → TTS).
- `transcript`: pre-transcribed text (client STT / tests); still gated by
  `INZO_STT_CONFIDENCE_THRESHOLD`. Below threshold (or empty) →
  `needs_repetition: true`; INZO asks the speaker to repeat.

## Memory

- `POST /api/memory/store` — `{"text", "kind": "fact"|"note"|"conversation", "tags": []}` → `{"id", "kind"}`
- `POST /api/memory/recall` — `{"query", "limit": 5}` → ranked `hits` (vector + keyword)
- `GET /api/memory/stats` — short/long/vector counts

## Background tasks

- `POST /api/tasks` — `{"name", "kind": "index_documents"|"consolidate_memory"|"research", "payload": {...}}`
- `GET /api/tasks` — list; `GET /api/tasks/{id}` — inspect (`pending|running|done|failed`)

## Skills

- `GET /api/skills` — catalog with enabled state
- `POST /api/skills/{name}/enable` · `POST /api/skills/{name}/disable`

## Tools

- `GET /api/tools` — catalog with parameters and required capabilities
- `POST /api/tools/{name}/execute` — `{"args": {...}, "actor": "user"}`
  - `404` unknown tool · `403` missing capability · `422` bad args/timeout

## Settings

- `GET /api/settings` — non-secret settings view
- `PUT /api/settings` — whitelisted updates only (`log_level`,
  `stt_confidence_threshold`). Secrets are never readable or settable here.
