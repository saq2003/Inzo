# INZO security model

## Capabilities (deny-by-default)

`security/permissions.py::PermissionManager` grants named capabilities to
actors. `check()` returns `False` unless explicitly granted; `require()`
raises `PermissionDenied` otherwise. Every tool execution calls `require()`
for each of the tool's `required_capabilities` **before** running (Rule 13).

Default grants (see `app/dependencies.py`) cover the local builtin tools
for `user` and `inzo-agent`. Unknown actors (e.g. `intruder`) hold nothing.

## Rule 12: no shell from natural language

There is **no shell/command/subprocess tool** in the registry, by design.
`tests/test_tool_safety.py` pins this behaviorally:

- no registered tool name contains `shell|exec|command|subprocess|bash|terminal`
- `calculator` uses AST-whitelisted arithmetic (`safe_eval`) — code like
  `__import__('os')` is rejected, not executed
- `read_file` is sandboxed to the data dir (symlink-aware) and refuses
  path escapes
- unknown tools raise `UnknownToolError`; bad args raise `ValueError`

## Secrets

`security/secrets.py` reads only from the environment (`get_secret`), with
`mask_secret()` for safe logging. `.env` is git-ignored (Rule 14); the API
settings endpoints expose no secrets.

## Output verification

`core/verifier.py` checks every agent reply against `VerificationPolicy`
(length cap, blocked substrings) before delivery. The voice pipeline adds a
confidence gate so unclear audio triggers a repetition request, never a
fabricated transcript.

## Timeouts & retries

External calls carry timeouts (Rule 9): tool execution (`10s` default),
model generation (`30s`), fetch (`20s`). The voice STT stage retries once
with re-preprocessing on low confidence (Rule 10), then asks for repetition.
