"""Net worth: track assets and liabilities, show the balance sheet."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import cast

from intelligence.finance.calculations import format_money
from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteKVStore

_STORE = "networth.db"
_ASSETS_INDEX = "assets:index"
_LIABILITIES_INDEX = "liabilities:index"


def _to_decimal(raw: str) -> Decimal:
    try:
        return Decimal(raw.replace(",", "").strip())
    except InvalidOperation as exc:
        raise ValueError(f"invalid amount: {raw!r}") from exc


def _load_names(kv: SQLiteKVStore, key: str) -> list[str]:
    raw = kv.get(key)
    if raw is None:
        return []
    data = cast(list[str], json.loads(raw))
    return sorted(str(name) for name in data)


def _save_names(kv: SQLiteKVStore, key: str, names: list[str]) -> None:
    kv.put(key, json.dumps(sorted(names)))


class NetworthSkill(Skill):
    """Tracks assets and liabilities and reports net worth."""

    name = "networth"
    description = (
        "Net-worth ledger: 'add <account> <amount>' records an asset, "
        "'liability <name> <amount>' records a liability, 'show' reports "
        "assets, liabilities, and net worth."
    )
    intents = ("networth.add", "networth.show")
    required_capabilities = ("skills.execute", "memory.write", "memory.read")
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        lowered = text.lower()
        if lowered.startswith("add "):
            return self._add(context, text[4:], kind="asset")
        if lowered.startswith("liability "):
            return self._add(context, text[10:], kind="liability")
        if lowered == "show":
            return self._show(context)
        return (
            "networth: 'add <account> <amount>' | 'liability <name> <amount>' | 'show'"
        )

    def _add(self, context: SkillContext, arg: str, kind: str) -> str:
        parts = arg.rsplit(None, 1)
        if len(parts) != 2:
            word = "add" if kind == "asset" else "liability"
            return f"{word} usage: '{word} <name> <amount>'"
        name = parts[0].strip()
        try:
            amount = _to_decimal(parts[1])
        except ValueError as exc:
            return f"add failed: {exc}"
        if not name or amount < 0:
            return "add failed: need a name and a non-negative amount"
        kv = SQLiteKVStore(require_data_dir(context) / _STORE)
        prefix, index_key = (
            ("asset", _ASSETS_INDEX) if kind == "asset" else ("liability", _LIABILITIES_INDEX)
        )
        kv.put(f"{prefix}:{name.lower()}", json.dumps({"name": name, "amount": str(amount)}))
        names = _load_names(kv, index_key)
        if name.lower() not in names:
            _save_names(kv, index_key, [*names, name.lower()])
        return f"recorded {kind}: {name} = {format_money(amount)}"

    def _show(self, context: SkillContext) -> str:
        kv = SQLiteKVStore(require_data_dir(context) / _STORE)

        def _entries(prefix: str, index_key: str) -> list[tuple[str, Decimal]]:
            entries: list[tuple[str, Decimal]] = []
            for key in _load_names(kv, index_key):
                raw = kv.get(f"{prefix}:{key}")
                if raw is None:
                    continue
                data = cast(dict[str, str], json.loads(raw))
                entries.append((str(data.get("name", key)), _to_decimal(str(data.get("amount", "0")))))
            return entries

        assets = _entries("asset", _ASSETS_INDEX)
        liabilities = _entries("liability", _LIABILITIES_INDEX)
        total_assets = sum((a for _, a in assets), Decimal("0"))
        total_liabilities = sum((a for _, a in liabilities), Decimal("0"))
        net = total_assets - total_liabilities
        lines = ["net worth:"]
        lines.append("  assets:")
        lines.extend(f"    {name}: {format_money(amount)}" for name, amount in assets)
        lines.append(f"    total: {format_money(total_assets)}")
        lines.append("  liabilities:")
        lines.extend(f"    {name}: {format_money(amount)}" for name, amount in liabilities)
        lines.append(f"    total: {format_money(total_liabilities)}")
        lines.append(f"  net worth: {format_money(net)}")
        return "\n".join(lines)


SKILLS: list[Skill] = [NetworthSkill()]
