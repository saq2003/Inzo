"""Chat draft templates: fill a tone template for a topic.

Tones: formal, friendly, hinglish, apology, followup. Pure string
templating on the stdlib — no model needed.
"""

from __future__ import annotations

from skills.base import Skill, SkillContext

_TONES: dict[str, str] = {
    "formal": (
        "Hello, I hope you are doing well. I am writing regarding {about}. "
        "Please let me know a convenient time to discuss this further. Thank you."
    ),
    "friendly": (
        "Hey! Hope you're doing great. Wanted to chat about {about} — "
        "let me know when you're free!"
    ),
    "hinglish": (
        "Arre suno! {about} ke baare mein baat karni thi. "
        "Jab free ho to bata dena!"
    ),
    "apology": (
        "I am really sorry about {about}. That was my mistake, and I will "
        "make sure it does not happen again. I hope you can forgive me."
    ),
    "followup": (
        "Hi, just following up on {about}. Please let me know if there is "
        "any update. Thanks!"
    ),
}


def list_tones() -> list[str]:
    """Available draft tones."""
    return sorted(_TONES)


def render_draft(tone: str, about: str) -> str:
    """Fill the ``tone`` template for ``about``; raises KeyError on bad tone."""
    return _TONES[tone].format(about=about.strip())


class ChatDraftsSkill(Skill):
    """Renders tone-based chat/message drafts from templates."""

    name = "chat_drafts"
    description = (
        "Drafts short chat messages from tone templates (formal, friendly, "
        "hinglish, apology, followup): 'draft <tone> <what it is about>'."
    )
    intents = ("draft.make",)
    required_capabilities = ("skills.execute",)
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        rest = text[len("draft") :].strip() if text.lower().startswith("draft") else text.strip()
        if not rest or rest.lower() in ("tones", "list", "help"):
            return (
                "tones: " + ", ".join(list_tones()) + " — usage: draft <tone> <what it is about>"
            )
        parts = rest.split(None, 1)
        tone = parts[0].lower()
        if tone not in _TONES:
            return f"unknown tone {tone!r}; tones: " + ", ".join(list_tones())
        if len(parts) < 2 or not parts[1].strip():
            return f"usage: draft {tone} <what it is about>"
        return render_draft(tone, parts[1])


SKILLS: list[Skill] = [ChatDraftsSkill()]
