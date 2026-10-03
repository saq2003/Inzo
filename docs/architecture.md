# INZO architecture

## Request flow (chat)

```
POST /api/chat
  → app/api/chat.py            validate + sanitize
  → core/agent.py::handle      orchestrate
      → intelligence/nlp       detect_intent (local, rule-based)
      → core/planner.py        Plan: ordered tool steps + required capabilities
      → core/router.py         ModelRouter.route("chat") → LLMAdapter
      → tools/registry.py      execute(): permission check → validate → run (timeout)
      → skills/registry.py     match(intent) → enabled skill context
      → core/verifier.py       policy check on the reply
      → memory/manager.py      remember turn (short-term; durable on demand)
  → ChatResponse               reply + intent + plan + tool calls + verified
```

## Voice flow

```
POST /api/voice/process
  → voice/pipeline.py
      VAD (EnergyVAD) → preprocess (denoise/aec/enhance stages)
      → STT → confidence gate (retry once → else NeedsRepetitionError)
      → core/agent.py::handle → TTS
```

The pipeline **never fabricates**: below-threshold confidence raises
`NeedsRepetitionError`, and the API asks the speaker to repeat.

## Memory flow

```
remember() → ShortTermMemory (bounded deque)
           → [durable] LongTermMemory → SQLiteDocumentStore
           → [durable] Retriever.index → HashEmbedding → LocalVectorStore
recall()   → vector search + keyword search, merged and ranked
```

Swap `HashEmbedding` for a real embedding model and `LocalVectorStore`
for a vector DB by implementing `storage.protocols.VectorStore`.

## Background work

`workers/queue.py::InProcessQueue` runs coroutine factories on the event
loop; `workers/scheduler.py::Scheduler` runs recurring jobs. Task kinds:
`index_documents`, `consolidate_memory`, `research`. Heavy bodies use
`loop.run_in_executor` (Rule 8).

## Wiring

`app/dependencies.py` constructs every singleton with explicit
dependencies (settings → permissions → memory → tools → skills → router →
agent → voice → queue → scheduler). `reset_wiring()` gives tests isolation.
