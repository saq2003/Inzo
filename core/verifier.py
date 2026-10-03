"""Output verifier: checks agent replies against a safety policy (Rule 11).

The verifier is deterministic and local. It never calls a model.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class VerificationPolicy:
    """Tunable verification rules."""

    max_output_chars: int = 4000
    blocked_substrings: tuple[str, ...] = (
        "__import__",
        "os.system",
        "subprocess.",
        "eval(",
    )


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    issues: tuple[str, ...] = field(default_factory=tuple)


class Verifier:
    """Checks candidate replies before they reach the user."""

    def __init__(self, policy: VerificationPolicy | None = None) -> None:
        self.policy = policy or VerificationPolicy()

    def verify(self, text: str) -> VerificationResult:
        """Verify ``text``; return ok=False with issues on any violation."""
        issues: list[str] = []
        if not text.strip():
            issues.append("empty response")
        if len(text) > self.policy.max_output_chars:
            issues.append(
                f"response too long ({len(text)} > {self.policy.max_output_chars})"
            )
        lowered = text.lower()
        for blocked in self.policy.blocked_substrings:
            if blocked in lowered:
                issues.append(f"blocked pattern present: {blocked!r}")
        return VerificationResult(ok=not issues, issues=tuple(issues))
