"""Security skills: network-guard mode, voice/PIN lock, password audit, vault.

``local_only_mode`` flips the shared ``netguard.json`` mode that the
``NetworkGuard`` helper (``netguard.py``) reads before any network call.
``voice_lock`` is hardware-gated with a real local PIN fallback;
``password_audit`` and ``secret_vault`` are pure-local (``local_only=True``)
with no network, no storage of plaintext, and no logged passwords.
"""
