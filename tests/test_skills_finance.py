"""Finance skill tests (offline, deterministic; Decimal math)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from skills.base import Skill, SkillContext
from skills.discovery import build_skill_registry


def _ctx(tmp_path: Path, message: str) -> SkillContext:
    """Bare skill context over an isolated data dir."""
    return SkillContext(
        actor="test", message=message, memory=None, tools=None, data_dir=tmp_path
    )


def _skill(name: str) -> Skill:
    """Fetch a skill from a fresh registry."""
    return build_skill_registry().get(name)


def test_tax_india_compute_1500000(tmp_path: Path) -> None:
    """New-regime tax on 15,00,000 income is 93,750."""
    result = asyncio.run(_skill("tax_india").handle(_ctx(tmp_path, "compute 1500000")))
    assert "93750" in result.replace(",", "")  # skill formats money with commas


def test_loan_planner_schedule(tmp_path: Path) -> None:
    """Amortization schedule ends at zero balance with a total-interest line."""
    result = asyncio.run(
        _skill("loan_planner").handle(_ctx(tmp_path, "schedule 100000 12 12"))
    )
    assert "balance ₹0.00" in result
    assert "total interest" in result


def test_expense_add_then_report(tmp_path: Path) -> None:
    """An added expense appears in the category report."""
    skill = _skill("expense_tracker")
    added = asyncio.run(skill.handle(_ctx(tmp_path, "add 250 chai snacks")))
    assert "added" in added

    report = asyncio.run(skill.handle(_ctx(tmp_path, "report")))
    assert "food" in report
    assert "250.00" in report


def test_networth_add_liability_show_math(tmp_path: Path) -> None:
    """Assets minus liabilities net out correctly in 'show'."""
    skill = _skill("networth")
    asyncio.run(skill.handle(_ctx(tmp_path, "add savings 500000")))
    asyncio.run(skill.handle(_ctx(tmp_path, "liability car_loan 200000")))

    shown = asyncio.run(skill.handle(_ctx(tmp_path, "show")))
    assert "savings" in shown
    assert "car_loan" in shown
    assert "300,000.00" in shown  # 500000 - 200000


def test_budget_alerts_set_and_check(tmp_path: Path) -> None:
    """A set budget is reported back by the status check."""
    skill = _skill("budget_alerts")
    result = asyncio.run(skill.handle(_ctx(tmp_path, "set food 10000")))
    assert "food" in result

    status = asyncio.run(skill.handle(_ctx(tmp_path, "")))
    assert "budgets" in status
