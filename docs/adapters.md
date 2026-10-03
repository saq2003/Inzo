# Swapping adapters (model-agnostic by design)

INZO never hard-codes a provider (Rule 4). Every engine is a `Protocol`;
register yours by name and point config at it.

## LLM adapter

```python
from core.protocols import LLMAdapter, LLMResponse

class MyLocalModel:
    name = "my-local-model"

    async def generate(self, prompt, *, system=None, max_tokens=512, timeout_s=30.0):
        import asyncio
        # call ollama / llama.cpp / transformers here (async, with timeout)
        text = await asyncio.wait_for(call_my_model(prompt), timeout_s)
        return LLMResponse(text=text, model=self.name)
```

Wire it in `app/dependencies.py`:

```python
router.register(MyLocalModel())
router.route_kind("chat", "my-local-model")
```

or set `INZO_LLM_PROVIDER=my-local-model` after registering. Keys come
from the environment via `security.secrets.get_secret("MY_KEY")` — never
hard-code them (Rule 5).

## Speech engines

```python
from voice.protocols import STTEngine, Transcription

class WhisperSTT:
    name = "whisper-local"
    async def transcribe(self, frames):
        ...  # never fabricate: return low confidence when unclear
        return Transcription(text=text, confidence=conf)
```

Pass to `VoicePipeline(stt=WhisperSTT(), tts=..., vad=...)` in wiring.

## Embeddings / vector store

Implement `storage.protocols.VectorStore` (`upsert`, `query`, `count`)
and inject it into `memory.retrieval.Retriever`. Replace
`memory.vector_store.HashEmbedding` with a real embedding model exposing
`.embed(text) -> list[float]`.

## Storage backend

Implement `storage.protocols.DocumentStore` / `KeyValueStore` and swap the
`SQLiteDocumentStore` construction in `app/dependencies.py`.

## Web research

Implement `intelligence.research.engine.Fetcher`
(`async def fetch(url, *, timeout_s) -> str`) and pass it to
`ResearchEngine(fetcher=...)`. Until then `NullFetcher` fails loudly
offline instead of pretending.
