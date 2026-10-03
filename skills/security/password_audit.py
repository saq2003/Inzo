"""Password audit skill (fully local, deterministic).

Audits a password against a built-in list of ~60 common passwords and
computes a 0–100 score from length, character classes, and estimated
entropy. PRIVACY: the password is taken only from the message text after
the ``audit `` prefix, is never written to disk, never added to memory,
and never appears in the skill's output.
"""

from __future__ import annotations

import math
from typing import Any

from skills.base import Skill, SkillContext

# ~60 well-known weak passwords; keep the list static so the audit is
# deterministic and works fully offline.
COMMON_PASSWORDS: tuple[str, ...] = (
    "password",
    "123456",
    "123456789",
    "qwerty",
    "abc123",
    "password1",
    "12345678",
    "111111",
    "123123",
    "admin",
    "letmein",
    "welcome",
    "monkey",
    "dragon",
    "1234567",
    "princess",
    "football",
    "qwerty123",
    "michael",
    "sunshine",
    "shadow",
    "master",
    "jesus",
    "superman",
    "maggie",
    "hunter",
    "trustno1",
    "baseball",
    "starwars",
    "whatever",
    "charlie",
    "aa123456",
    "donald",
    "jordan",
    "harley",
    "ranger",
    "thomas",
    "robert",
    "jennifer",
    "joshua",
    "matthew",
    "andrew",
    "daniel",
    "anthony",
    "william",
    "george",
    "nicole",
    "chloe",
    "michelle",
    "samantha",
    "qwertyuiop",
    "123321",
    "654321",
    "666666",
    "987654321",
    "qazwsx",
    "1q2w3e4r",
    "1qaz2wsx",
    "password123",
    "iloveyou",
    "freedom",
    "hello123",
    "solo",
    "passw0rd",
)


def audit(password: str) -> dict[str, Any]:
    """Score a password 0–100 with length, classes, entropy, common check.

    Entropy estimate: len × log2(character-pool size). Score = length
    (up to 40) + classes (10 each, up to 40) + entropy (up to 20).
    Common passwords are capped at 5/100. The input is never logged.
    """
    length = len(password)
    classes = sum(
        [
            any(c.islower() for c in password),
            any(c.isupper() for c in password),
            any(c.isdigit() for c in password),
            any(not c.isalnum() for c in password),
        ]
    )
    pool = 0
    if any(c.islower() for c in password):
        pool += 26
    if any(c.isupper() for c in password):
        pool += 26
    if any(c.isdigit() for c in password):
        pool += 10
    if any(not c.isalnum() for c in password):
        pool += 33
    entropy_bits = length * math.log2(pool) if pool > 0 else 0.0

    length_score = min(40.0, length * 2.5)
    class_score = min(40.0, classes * 10.0)
    entropy_score = min(20.0, entropy_bits / 6.0)
    score = length_score + class_score + entropy_score
    common = password.lower() in COMMON_PASSWORDS
    if common:
        score = min(score, 5.0)
    return {
        "score": round(min(100.0, score), 1),
        "length": length,
        "classes": classes,
        "entropy_bits": round(entropy_bits, 1),
        "common_password": common,
    }


class PasswordAuditSkill(Skill):
    """Audits password strength locally; never stores or logs the password."""

    name = "password_audit"
    description = (
        "Audits a password (after the 'audit ' prefix) against common "
        "passwords and scores it 0-100 by length, character classes, and "
        "entropy. The password is never stored, logged, or echoed."
    )
    intents = ("password.audit",)
    required_capabilities = ("skills.execute",)
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        password = ""
        if text.lower().startswith("audit "):
            password = text[len("audit ") :]
        if not password:
            return "usage: audit <password> (the password is checked locally only)"
        result = audit(password)
        verdict = (
            "weak" if result["score"] < 40 else "moderate" if result["score"] < 70 else "strong"
        )
        flag = " — COMMON PASSWORD, change it immediately" if result["common_password"] else ""
        return (
            f"password audit: score {result['score']}/100 ({verdict}){flag}\n"
            f"length: {result['length']}, classes: {result['classes']}/4, "
            f"entropy: {result['entropy_bits']} bits"
        )


SKILLS: list[Skill] = [PasswordAuditSkill()]
