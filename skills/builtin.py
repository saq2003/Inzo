"""Built-in skills: small, local, permission-aware behaviors."""

from __future__ import annotations

from datetime import datetime

from intelligence.finance.calculations import compound_growth, format_money, loan_emi
from intelligence.nlp.pipeline import extract_expression, extract_numbers, safe_eval
from skills.base import Skill, SkillContext


class CalculatorSkill(Skill):
    name = "calculator"
    description = "Evaluates arithmetic expressions deterministically."
    intents = ("calculate",)

    async def handle(self, context: SkillContext) -> str:
        expression = extract_expression(context.message) or context.message.strip()
        try:
            value = safe_eval(expression)
        except ValueError as exc:
            return f"could not evaluate: {exc}"
        return f"{expression.strip()} = {value}"


class TimeSkill(Skill):
    name = "time"
    description = "Reports the current local time."
    intents = ("get_time",)

    async def handle(self, context: SkillContext) -> str:
        now = datetime.now().astimezone()
        return f"current time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}"


class NoteSkill(Skill):
    name = "notes"
    description = "Saves and recalls user notes via long-term memory."
    intents = ("save_note", "recall_memory")
    required_capabilities = ("skills.execute", "memory.write")

    async def handle(self, context: SkillContext) -> str:
        if "recall" in context.message.lower() or "remember" in context.message.lower():
            hits = await context.memory.recall(context.message, limit=3)
            if not hits:
                return "no matching notes found"
            return "notes: " + " | ".join(h.text[:120] for h in hits)
        note_id = await context.memory.remember(
            "user", context.message, durable=True, kind="note"
        )
        return f"note saved (id={note_id})"


class FinanceSkill(Skill):
    name = "finance"
    description = "Runs deterministic finance calculations (Python computes)."
    intents = ("finance",)

    async def handle(self, context: SkillContext) -> str:
        text = context.message.lower()
        numbers = extract_numbers(text)
        try:
            if "compound" in text and len(numbers) >= 3:
                result = compound_growth(numbers[0], numbers[1], numbers[2])
                return f"future value = {format_money(result)}"
            if "emi" in text and len(numbers) >= 3:
                result = loan_emi(numbers[0], numbers[1], int(numbers[2]))
                return f"monthly EMI = {format_money(result)}"
        except ValueError as exc:
            return f"finance error: {exc}"
        return (
            "finance skill: try 'compound principal=10000 rate=8 years=5' "
            "or 'emi principal=500000 rate=9 months=60'"
        )


def builtin_skills() -> list[Skill]:
    """Default local skill set."""
    return [CalculatorSkill(), TimeSkill(), NoteSkill(), FinanceSkill()]
