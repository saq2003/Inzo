"""Indian new-regime income tax estimates (FY 2025-26)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from intelligence.finance.calculations import format_money
from intelligence.finance.tax_india import compute_tax
from skills.base import Skill, SkillContext


class TaxIndiaSkill(Skill):
    """Estimates Indian income tax under the new regime (FY 2025-26 slabs)."""

    name = "tax_india"
    description = (
        "Income-tax estimator: 'compute <income>' shows the new-regime "
        "breakdown for FY 2025-26 (slabs, Rs 75000 standard deduction, 87A "
        "rebate); add 'nonsalaried' to skip the standard deduction."
    )
    intents = ("tax.compute",)
    required_capabilities = ("skills.execute",)
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        if text.lower().startswith("compute "):
            text = text[8:]
        parts = text.split()
        if not parts:
            return "tax usage: 'compute <income> [nonsalaried]'"
        try:
            income = Decimal(parts[0].replace(",", "").strip())
        except InvalidOperation as exc:
            raise ValueError(f"invalid income: {parts[0]!r}") from exc
        if income < 0:
            return "tax failed: income must be >= 0"
        salaried = "nonsalaried" not in {p.lower() for p in parts[1:]}
        try:
            result = compute_tax(income, salaried=salaried)
        except ValueError as exc:
            return f"tax failed: {exc}"
        return (
            f"new-regime tax FY2025-26 ({'salaried' if salaried else 'non-salaried'}):\n"
            f"  gross income: {format_money(result['gross_income'])}\n"
            f"  standard deduction: {format_money(result['standard_deduction'])}\n"
            f"  taxable income: {format_money(result['taxable_income'])}\n"
            f"  slab tax: {format_money(result['slab_tax'])}\n"
            f"  rebate 87A: {format_money(result['rebate_87a'])}\n"
            f"  total tax: {format_money(result['total_tax'])} "
            f"({result['effective_rate_pct']}% effective)"
        )


SKILLS: list[Skill] = [TaxIndiaSkill()]
