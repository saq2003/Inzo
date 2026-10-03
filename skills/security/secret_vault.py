"""Secret vault skill (fully local; HONEST obfuscation, not encryption).

SECURITY NOTE — read this before trusting the vault:
  * Secrets at rest are OBFUSCATED with a PBKDF2-HMAC-SHA256-derived key
    (200,000 iterations, 16-byte ``secrets`` salt) XORed as a keystream.
  * This is NOT authenticated encryption and NOT a substitute for a real
    cipher. It defeats casual disk inspection only.
  * Production MUST plug the ``cryptography`` package's Fernet through
    the ``VaultCipher`` Protocol defined below (``set_cipher``), which
    turns store/retrieve into real AEAD without changing any other code.
  * An HMAC-SHA256 tag (keyed with the same derived key) detects wrong
    passwords; ``retrieve`` raises ``VaultError`` instead of returning
    garbage. Plaintext is never stored and secrets are never echoed.

Entries live in ``data_dir/"vault.db"`` (salt + tag + obfuscated bytes).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from itertools import cycle
from typing import Protocol

from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteDocumentStore

KDF_ITERATIONS = 200_000
SALT_BYTES = 16
KEY_BYTES = 32


class VaultError(Exception):
    """Raised on wrong password, unknown entry, or integrity failure."""


class VaultCipher(Protocol):
    """Plug-in point: real authenticated cipher (e.g. Fernet).

    The default implementation below is XOR keystream obfuscation.
    Production must replace it via ``Vault.set_cipher`` with an AEAD
    cipher from the ``cryptography`` package.
    """

    def encrypt(self, plaintext: bytes, key: bytes) -> bytes:
        """Protect plaintext with the derived key."""
        ...

    def decrypt(self, ciphertext: bytes, key: bytes) -> bytes:
        """Reverse ``encrypt``; raise ``VaultError`` if it fails."""
        ...


class XorKeystreamCipher:
    """Default obfuscation cipher — NOT encryption (see module docstring)."""

    def encrypt(self, plaintext: bytes, key: bytes) -> bytes:
        return bytes(p ^ k for p, k in zip(plaintext, cycle(key)))

    def decrypt(self, ciphertext: bytes, key: bytes) -> bytes:
        return bytes(c ^ k for c, k in zip(ciphertext, cycle(key)))


def _derive_key(password: str, salt: bytes) -> bytes:
    """PBKDF2-HMAC-SHA256(password, salt, 200_000) → 32-byte key."""
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, KDF_ITERATIONS)


def _auth_tag(key: bytes, name: str) -> str:
    """Keyed integrity tag; detects a wrong password before decrypting."""
    return hmac.new(key, b"inzo-vault:" + name.encode("utf-8"), hashlib.sha256).hexdigest()


class Vault:
    """Password-protected secret store backed by ``vault.db``."""

    def __init__(self, data_dir_path: str = "") -> None:
        self._db_path = data_dir_path
        self._cipher: VaultCipher = XorKeystreamCipher()

    @classmethod
    def for_context(cls, context: SkillContext) -> Vault:
        """Build a Vault bound to the skill's data directory."""
        return cls(str(require_data_dir(context) / "vault.db"))

    def set_cipher(self, cipher: VaultCipher) -> None:
        """Plug a production cipher (e.g. ``cryptography`` Fernet)."""
        self._cipher = cipher

    def _store(self) -> SQLiteDocumentStore:
        return SQLiteDocumentStore(self._db_path)

    def _find(self, name: str) -> dict[str, object] | None:
        """Return the newest entry for ``name`` (store is created-DESC)."""
        for doc in self._store().search("", limit=10000):
            if doc.get("kind") == "vault_entry" and doc.get("name") == name:
                return dict(doc)
        return None

    def store(self, name: str, secret: str, password: str) -> None:
        """Obfuscate and persist a secret under ``name`` (never plaintext).

        Re-storing a name supersedes older entries; ``retrieve`` always
        reads the newest one.
        """
        if not name:
            raise VaultError("entry name must not be empty")
        if not password:
            raise VaultError("password must not be empty")
        salt = secrets.token_bytes(SALT_BYTES)
        key = _derive_key(password, salt)
        ciphertext = self._cipher.encrypt(secret.encode("utf-8"), key)
        self._store().add(
            {
                "kind": "vault_entry",
                "name": name,
                "salt_hex": salt.hex(),
                "tag_hex": _auth_tag(key, name),
                "ct_hex": ciphertext.hex(),
            }
        )

    def retrieve(self, name: str, password: str) -> str:
        """Return the secret for ``name``; raise VaultError on bad password."""
        doc = self._find(name)
        if doc is None:
            raise VaultError(f"unknown entry: {name!r}")
        salt = bytes.fromhex(str(doc["salt_hex"]))
        key = _derive_key(password, salt)
        if not hmac.compare_digest(_auth_tag(key, name), str(doc["tag_hex"])):
            raise VaultError("wrong password")
        plaintext = self._cipher.decrypt(bytes.fromhex(str(doc["ct_hex"])), key)
        return plaintext.decode("utf-8")

    def list_names(self) -> list[str]:
        """Return stored entry names (never secrets)."""
        names = [
            str(doc["name"])
            for doc in self._store().search("", limit=10000)
            if doc.get("kind") == "vault_entry"
        ]
        return sorted(set(names))


class SecretVaultSkill(Skill):
    """Password-protected vault for secrets (XOR obfuscation by default)."""

    name = "secret_vault"
    description = (
        "Stores secrets obfuscated at rest with a PBKDF2-derived key "
        "(NOT authenticated encryption — plug cryptography Fernet via the "
        "VaultCipher Protocol for production). Plaintext is never stored."
    )
    intents = ("vault.store", "vault.get", "vault.list")
    required_capabilities = ("skills.execute", "memory.write", "memory.read")
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        lower = text.lower()
        vault = Vault.for_context(context)

        if lower == "list":
            names = vault.list_names()
            return "vault entries: " + (", ".join(names) if names else "(empty)")

        if lower.startswith("store "):
            # "store <name> <secret> <password>"
            parts = text.split(maxsplit=3)
            if len(parts) != 4:
                return "usage: store <name> <secret> <password>"
            _, name, secret, password = parts
            try:
                vault.store(name, secret, password)
            except VaultError as exc:
                return f"store failed: {exc}"
            return f"stored secret for {name!r} (obfuscated at rest)"

        if lower.startswith("get "):
            # "get <name> <password>"
            parts = text.split(maxsplit=2)
            if len(parts) != 3:
                return "usage: get <name> <password>"
            _, name, password = parts
            try:
                return f"{name!r}: {vault.retrieve(name, password)}"
            except VaultError as exc:
                return f"retrieve failed: {exc}"

        return "vault: 'store <name> <secret> <password>', 'get <name> <password>', 'list'"


SKILLS: list[Skill] = [SecretVaultSkill()]
