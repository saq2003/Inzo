"""Parameterized SQL SELECT builder (fully local, stdlib only).

Builds ``SELECT`` statements with ``?`` placeholders plus a params list —
values are never interpolated into the SQL text. Every identifier (table,
column, dotted reference) is validated against
``^[A-Za-z_][A-Za-z0-9_]*$`` per dot-separated part, and operators/joins
come from strict allowlists, so injection attempts raise ``ValueError``
instead of producing SQL.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

from skills.base import Skill, SkillContext

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ALLOWED_OPS = {"=", "!=", "<>", "<", "<=", ">", ">=", "LIKE", "IN", "NOT IN", "IS", "IS NOT"}
_ALLOWED_JOINS = {"INNER", "LEFT", "RIGHT", "FULL"}
_ALLOWED_ORDER = {"ASC", "DESC"}


def validate_identifier(name: str) -> str:
    """Validate a (possibly dotted) SQL identifier; raise ValueError if bad."""
    parts = name.split(".")
    if not name or any(not _IDENT_RE.fullmatch(part) for part in parts):
        raise ValueError(f"invalid SQL identifier (possible injection): {name!r}")
    return name


@dataclass(frozen=True)
class WhereClause:
    """One WHERE triplet: column, operator, value."""

    column: str
    op: str
    value: object


@dataclass(frozen=True)
class JoinClause:
    """One JOIN: type, table, left ON operand, right ON operand."""

    join_type: str
    table: str
    left: str
    right: str


def build_select(
    table: str,
    columns: list[str] | None = None,
    joins: list[JoinClause] | None = None,
    where: list[WhereClause] | None = None,
    order_by: list[tuple[str, str]] | None = None,
    limit: int | None = None,
) -> tuple[str, list[object]]:
    """Build ``(sql, params)`` for a parameterized SELECT statement."""
    validate_identifier(table)
    selected = columns or ["*"]
    cols = ["*" if col == "*" else validate_identifier(col) for col in selected]
    # noqa S608: every interpolated fragment is a validated identifier or "*".
    sql = f"SELECT {', '.join(cols)} FROM {table}"  # noqa: S608
    params: list[object] = []
    for join in joins or []:
        join_type = join.join_type.upper()
        if join_type not in _ALLOWED_JOINS:
            raise ValueError(f"invalid join type: {join.join_type!r}")
        validate_identifier(join.table)
        validate_identifier(join.left)
        validate_identifier(join.right)
        sql += f" {join_type} JOIN {join.table} ON {join.left} = {join.right}"
    conditions: list[str] = []
    for clause in where or []:
        validate_identifier(clause.column)
        op = clause.op.upper()
        if op not in _ALLOWED_OPS:
            raise ValueError(f"invalid operator: {clause.op!r}")
        if op in ("IS", "IS NOT"):
            if not isinstance(clause.value, str) or clause.value.upper() != "NULL":
                raise ValueError("IS / IS NOT only support NULL")
            conditions.append(f"{clause.column} {op} NULL")
        elif op in ("IN", "NOT IN"):
            if not isinstance(clause.value, (list, tuple)) or not clause.value:
                raise ValueError("IN / NOT IN need a non-empty list of values")
            placeholders = ", ".join("?" for _ in clause.value)
            conditions.append(f"{clause.column} {op} ({placeholders})")
            params.extend(clause.value)
        else:
            conditions.append(f"{clause.column} {op} ?")
            params.append(clause.value)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    if order_by:
        ordering: list[str] = []
        for column, direction in order_by:
            validate_identifier(column)
            direction_up = direction.upper()
            if direction_up not in _ALLOWED_ORDER:
                raise ValueError(f"invalid order direction: {direction!r}")
            ordering.append(f"{column} {direction_up}")
        sql += " ORDER BY " + ", ".join(ordering)
    if limit is not None:
        if limit < 0:
            raise ValueError("limit cannot be negative")
        sql += " LIMIT ?"
        params.append(limit)
    return sql, params


def _coerce_scalar(text: str) -> object:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def parse_spec(text: str) -> tuple[str, list[object]]:
    """Parse a ``key=value`` spec into ``(sql, params)``.

    Keys: ``table=``, ``columns=a,b``, ``join=LEFT:t2:t1.id=t2.tid``
    (repeatable), ``where=col,op,val`` (``;``-separated, ``IN`` values use
    ``|``), ``order=col[:DESC]``, ``limit=n``.
    """
    raw: dict[str, list[str]] = {}
    for token in shlex.split(text):
        if "=" not in token:
            continue
        key, _, value = token.partition("=")
        raw.setdefault(key.strip().lower(), []).append(value.strip())
    table_vals = raw.get("table", [""])[0]
    if not table_vals:
        raise ValueError("spec needs table=<name>")
    columns = [c.strip() for c in raw.get("columns", ["*"])[0].split(",") if c.strip()]
    joins: list[JoinClause] = []
    for spec in raw.get("join", []):
        parts = spec.split(":", 2)
        if len(parts) != 3 or "=" not in parts[2]:
            raise ValueError(f"bad join spec: {spec!r} (want TYPE:table:left=right)")
        left, _, right = parts[2].partition("=")
        joins.append(JoinClause(parts[0], parts[1], left.strip(), right.strip()))
    where: list[WhereClause] = []
    for spec in raw.get("where", []):
        for triplet in spec.split(";"):
            bits = [b.strip() for b in triplet.split(",", 2)]
            if len(bits) != 3:
                raise ValueError(f"bad where triplet: {triplet!r} (want col,op,value)")
            column, op, value = bits
            if op.upper() in ("IN", "NOT IN"):
                where.append(
                    WhereClause(column, op, [_coerce_scalar(v) for v in value.split("|")])
                )
            else:
                where.append(WhereClause(column, op, _coerce_scalar(value)))
    order_by: list[tuple[str, str]] = []
    for spec in raw.get("order", []):
        for item in spec.split(","):
            col, _, direction = item.partition(":")
            order_by.append((col.strip(), (direction.strip() or "ASC")))
    limit: int | None = None
    if "limit" in raw:
        try:
            limit = int(raw["limit"][0])
        except ValueError as exc:
            raise ValueError(f"invalid limit: {raw['limit'][0]!r}") from exc
    return build_select(table_vals, columns, joins, where, order_by, limit)


class SqlBuilderSkill(Skill):
    """Builds parameterized SELECT statements with injection guards."""

    name = "sql_builder"
    description = (
        "Builds parameterized SQL SELECT statements (? placeholders + params "
        "list) with strict identifier validation; rejects injection attempts."
    )
    intents = ("sql.build",)
    required_capabilities = ("skills.execute",)
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        try:
            sql, params = parse_spec(context.message)
        except ValueError as exc:
            return f"sql build error: {exc}"
        rendered = ", ".join(repr(p) for p in params) if params else "(none)"
        return (
            "parameterized query built:\n"
            f"SQL: {sql}\n"
            f"params: [{rendered}]\n"
            "usage: pass params separately to your DB driver (never interpolate)."
        )


SKILLS: list[Skill] = [SqlBuilderSkill()]
