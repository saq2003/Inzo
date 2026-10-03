"""Loan planning: amortization schedules with total interest."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from intelligence.finance.calculations import format_money, loan_emi
from intelligence.finance.loans import amortization_schedule
from skills.base import Skill, SkillContext


def _to_decimal(raw: str) -> Decimal:
    try:
        return Decimal(raw.replace(",", "").strip())
    except InvalidOperation as exc:
        raise ValueError(f"invalid number: {raw!r}") from exc


class LoanPlannerSkill(Skill):
    """Builds loan amortization schedules (pure local math)."""

    name = "loan_planner"
    description = (
        "Loan planner: 'schedule <principal> <annual_rate_pct> <months>' shows "
        "the EMI, total interest, total payable, and the first/last schedule rows."
    )
    intents = ("loan.schedule",)
    required_capabilities = ("skills.execute",)
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        if text.lower().startswith("schedule "):
            text = text[9:]
        parts = text.split()
        if len(parts) != 3:
            return "loan usage: 'schedule <principal> <annual_rate_pct> <months>'"
        try:
            principal = _to_decimal(parts[0])
            rate = _to_decimal(parts[1])
            months = int(parts[2])
        except ValueError as exc:
            return f"loan failed: {exc}"
        try:
            emi = loan_emi(principal, rate, months)
            rows = amortization_schedule(principal, rate, months)
        except ValueError as exc:
            return f"loan failed: {exc}"
        total_interest = sum((r["interest"] for r in rows), Decimal("0"))
        total_payment = sum((r["payment"] for r in rows), Decimal("0"))
        first, last = rows[0], rows[-1]
        return (
            f"loan schedule: {format_money(principal)} @ {rate}% for {months} months\n"
            f"  EMI: {format_money(emi)}\n"
            f"  total interest: {format_money(total_interest)}\n"
            f"  total payable: {format_money(total_payment)}\n"
            f"  month 1: pay {format_money(first['payment'])} "
            f"(principal {format_money(first['principal'])}, "
            f"interest {format_money(first['interest'])}) "
            f"balance {format_money(first['balance'])}\n"
            f"  month {months}: pay {format_money(last['payment'])} "
            f"(principal {format_money(last['principal'])}, "
            f"interest {format_money(last['interest'])}) "
            f"balance {format_money(last['balance'])}"
        )


SKILLS: list[Skill] = [LoanPlannerSkill()]
