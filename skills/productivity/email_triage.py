"""Email triage with a rule engine; the provider is a pluggable adapter."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Protocol, cast

from intelligence.finance.portfolio import NotConfiguredError
from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteKVStore

_STORE = "email_rules.db"
_INDEX_KEY = "rules:index"
_RULE_RE = re.compile(r"^rule\s+add\s+(sender|subject)\s+(.+?)\s*->\s*(.+)$", re.IGNORECASE)


@dataclass(frozen=True)
class Email:
    """A minimal email message."""

    sender: str
    subject: str
    body: str = ""
    date: str = ""


@dataclass(frozen=True)
class EmailRule:
    """A triage rule: substring match on sender/subject maps to a label."""

    id: str
    kind: str  # "sender" | "subject"
    pattern: str
    label: str


class EmailProvider(Protocol):
    """Plug-in point for fetching email (implemented by the user)."""

    def fetch_messages(self, limit: int = 20) -> list[Email]:
        """Return the most recent messages, newest first."""
        ...


class StubEmailProvider(EmailProvider):
    """Not-configured email provider.

    Plug-in: implement :class:`EmailProvider` and assign it to the skill's
    ``email_provider`` attribute, e.g.::

        skill.email_provider = MyImapProvider()

    A real implementation should use stdlib ``urllib`` (or the provider's
    HTTPS API) with a timeout and at most 3 retries, and must not hard-code
    any provider, credentials, or keys. Until one is plugged in, every call
    raises :class:`NotConfiguredError`.
    """

    def fetch_messages(self, limit: int = 20) -> list[Email]:
        raise NotConfiguredError(
            "no email provider configured: assign an EmailProvider implementation "
            "to this skill's email_provider attribute (see StubEmailProvider docstring)"
        )


def classify(email: Email, rules: list[EmailRule]) -> list[str]:
    """Apply rules to one email; returns labels in rule order, deduplicated."""
    labels: list[str] = []
    for rule in rules:
        haystack = email.sender if rule.kind == "sender" else email.subject
        if rule.pattern.lower() in haystack.lower() and rule.label not in labels:
            labels.append(rule.label)
    return labels


def _load_rules(context: SkillContext) -> list[EmailRule]:
    kv = SQLiteKVStore(require_data_dir(context) / _STORE)
    raw_index = kv.get(_INDEX_KEY)
    ids: list[str] = cast(list[str], json.loads(raw_index)) if raw_index else []
    rules: list[EmailRule] = []
    for rule_id in ids:
        raw = kv.get(f"rule:{rule_id}")
        if raw is None:
            continue
        data = cast(dict[str, str], json.loads(raw))
        rules.append(
            EmailRule(
                id=rule_id,
                kind=str(data.get("kind", "subject")),
                pattern=str(data.get("pattern", "")),
                label=str(data.get("label", "")),
            )
        )
    return rules


class EmailTriageSkill(Skill):
    """Rule-based email triage over a pluggable provider."""

    name = "email_triage"
    description = (
        "Email triage: 'rule add sender|subject <pattern> -> <label>' stores a "
        "classification rule, 'rule list' shows rules, 'triage [limit]' fetches "
        "messages through the configured EmailProvider adapter and labels them."
    )
    intents = ("email.triage", "email.rule_add")
    required_capabilities = ("skills.execute", "memory.write", "memory.read", "network.fetch")
    background = True
    local_only = False
    adapter_note = (
        "Messages come from an EmailProvider adapter. The default "
        "StubEmailProvider raises NotConfiguredError — plug a real provider in "
        "by setting skill.email_provider to your implementation (stdlib urllib, "
        "timeout, at most 3 retries, no hard-coded provider or credentials). "
        "Rules and classification are fully local."
    )
    email_provider: EmailProvider = StubEmailProvider()

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        lowered = text.lower()
        if lowered.startswith("rule add"):
            return self._rule_add(context, text)
        if lowered.startswith("rule"):
            return self._rule_list(context)
        if lowered.startswith("triage"):
            return self._triage(context, text[6:].strip())
        return (
            "email_triage: 'rule add sender|subject <pattern> -> <label>' | "
            "'rule list' | 'triage [limit]'"
        )

    def _rule_add(self, context: SkillContext, text: str) -> str:
        match = _RULE_RE.match(text)
        if not match:
            return "rule usage: 'rule add sender|subject <pattern> -> <label>'"
        kind, pattern, label = match.group(1).lower(), match.group(2).strip(), match.group(3).strip()
        if not pattern or not label:
            return "rule failed: pattern and label must be non-empty"
        rule_id = uuid.uuid4().hex[:8]
        kv = SQLiteKVStore(require_data_dir(context) / _STORE)
        kv.put(
            f"rule:{rule_id}",
            json.dumps({"kind": kind, "pattern": pattern, "label": label}),
        )
        raw_index = kv.get(_INDEX_KEY)
        ids: list[str] = cast(list[str], json.loads(raw_index)) if raw_index else []
        kv.put(_INDEX_KEY, json.dumps([*ids, rule_id]))
        return f"rule added: {kind} contains '{pattern}' -> '{label}'"

    def _rule_list(self, context: SkillContext) -> str:
        rules = _load_rules(context)
        if not rules:
            return "no triage rules — use 'rule add sender|subject <pattern> -> <label>'"
        lines = ["triage rules:"]
        lines.extend(
            f"  {r.id}: {r.kind} contains '{r.pattern}' -> '{r.label}'" for r in rules
        )
        return "\n".join(lines)

    def _triage(self, context: SkillContext, arg: str) -> str:
        try:
            limit = int(arg) if arg else 20
        except ValueError as exc:
            return f"triage failed: limit must be an integer ({exc})"
        if limit < 1:
            return "triage failed: limit must be >= 1"
        try:
            messages = self.email_provider.fetch_messages(limit=limit)
        except NotConfiguredError:
            return (
                "email provider not configured — rules are stored but messages "
                "cannot be fetched. Plug an EmailProvider adapter into this "
                "skill's email_provider attribute (see the adapter_note)."
            )
        rules = _load_rules(context)
        if not messages:
            return "inbox empty"
        lines = [f"triaged {len(messages)} message(s) with {len(rules)} rule(s):"]
        for email in messages:
            labels = classify(email, rules)
            tag = ", ".join(labels) if labels else "unlabeled"
            lines.append(f"  [{tag}] {email.sender} — {email.subject}")
        return "\n".join(lines)


SKILLS: list[Skill] = [EmailTriageSkill()]
