"""Unit tests: NLP helpers, planner, reasoning trace, verifier."""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.planner import Planner
from core.reasoning import ReasoningTrace
from core.verifier import VerificationPolicy, Verifier
from intelligence.nlp.pipeline import (
    detect_intent,
    extract_expression,
    extract_numbers,
    safe_eval,
    tokenize,
)


def test_tokenize():
    assert tokenize("Hello, World! 123") == ["hello", "world", "123"]


def test_detect_intent_cases():
    assert detect_intent("calculate (2+3)*4") == "calculate"
    assert detect_intent("what time is it?") == "get_time"
    assert detect_intent("remember that I like tea") == "save_note"
    assert detect_intent("do you remember my notes?") == "recall_memory"
    assert detect_intent("compound principal=1000 rate=5 years=2") == "finance"
    assert detect_intent("tell me a story") == "chat"


def test_extract_expression():
    assert extract_expression("calculate (2+3)*4 please") == "(2+3)*4"
    assert extract_expression("no numbers here") is None


def test_extract_numbers():
    assert extract_numbers("emi principal=500000 rate=9 months=60") == [
        Decimal("500000"),
        Decimal("9"),
        Decimal("60"),
    ]


def test_safe_eval_values():
    assert safe_eval("2+3*4") == Decimal("14")
    assert safe_eval("(2+3)*4") == Decimal("20")
    assert safe_eval("2^3") == Decimal("8")


def test_safe_eval_rejects_non_arithmetic():
    for bad in ("__import__('os')", "open('x')", "1 + (lambda: 2)()", "a + 1"):
        with pytest.raises(ValueError):
            safe_eval(bad)


def test_planner_calculate_plan():
    planner = Planner()
    plan = planner.plan("calculate", "calculate 2+2")
    assert plan.intent == "calculate"
    assert len(plan.steps) == 1
    assert plan.steps[0].tool_name == "calculator"
    assert plan.steps[0].requires_capability == "tool.calculator"


def test_planner_chat_plan_has_no_tools():
    planner = Planner()
    plan = planner.plan("chat", "hello there")
    assert plan.steps == ()


def test_reasoning_trace():
    trace = ReasoningTrace()
    trace.add("intent", "calculate")
    trace.add("plan", "one step")
    assert len(trace) == 2
    assert "intent" in trace.summarize()


def test_verifier_accepts_clean_text():
    assert Verifier().verify("hello, this is fine").ok is True


def test_verifier_rejects_empty_and_blocked():
    assert Verifier().verify("   ").ok is False
    result = Verifier().verify("run os.system('rm -rf /') now")
    assert result.ok is False
    assert result.issues


def test_verifier_length_policy():
    policy = VerificationPolicy(max_output_chars=10)
    assert Verifier(policy).verify("this is way too long").ok is False
