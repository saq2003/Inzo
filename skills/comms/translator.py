"""English <-> Hindi dictionary translator (stdlib, fully local).

Word-by-word translation using a built-in EN<->HI dictionary (~85
entries, including common phrases). Unknown words pass through
untouched. Direction is auto-detected: any Devanagari in the input
means HI->EN, otherwise EN->HI. For full neural-machine-translation
coverage, plug a ``TranslatorEngine`` implementation.
"""

from __future__ import annotations

from typing import Protocol

from skills.base import Skill, SkillContext

_EN_HI: dict[str, str] = {
    "hello": "नमस्ते",
    "hi": "नमस्ते",
    "good morning": "सुप्रभात",
    "good night": "शुभ रात्रि",
    "good evening": "शुभ संध्या",
    "welcome": "स्वागत है",
    "goodbye": "अलविदा",
    "bye": "अलविदा",
    "see you": "फिर मिलेंगे",
    "thank you": "धन्यवाद",
    "thanks": "धन्यवाद",
    "please": "कृपया",
    "sorry": "माफ़ कीजिए",
    "excuse me": "माफ़ कीजिए",
    "yes": "हाँ",
    "no": "नहीं",
    "ok": "ठीक है",
    "okay": "ठीक है",
    "good": "अच्छा",
    "bad": "बुरा",
    "very": "बहुत",
    "today": "आज",
    "tomorrow": "कल",
    "yesterday": "बीता कल",
    "day": "दिन",
    "night": "रात",
    "morning": "सुबह",
    "evening": "शाम",
    "week": "सप्ताह",
    "month": "महीना",
    "year": "साल",
    "time": "समय",
    "now": "अब",
    "later": "बाद में",
    "here": "यहाँ",
    "there": "वहाँ",
    "where": "कहाँ",
    "what": "क्या",
    "when": "कब",
    "why": "क्यों",
    "how": "कैसे",
    "who": "कौन",
    "i": "मैं",
    "you": "तुम",
    "we": "हम",
    "they": "वे",
    "he": "वह",
    "she": "वह",
    "my": "मेरा",
    "your": "तुम्हारा",
    "our": "हमारा",
    "name": "नाम",
    "what is your name": "आपका नाम क्या है",
    "my name is": "मेरा नाम है",
    "how are you": "आप कैसे हैं",
    "i am fine": "मैं ठीक हूँ",
    "nice to meet you": "आपसे मिलकर खुशी हुई",
    "love": "प्यार",
    "friend": "दोस्त",
    "family": "परिवार",
    "home": "घर",
    "house": "मकान",
    "water": "पानी",
    "food": "खाना",
    "eat": "खाना",
    "drink": "पीना",
    "money": "पैसा",
    "work": "काम",
    "school": "स्कूल",
    "book": "किताब",
    "read": "पढ़ना",
    "write": "लिखना",
    "come": "आना",
    "go": "जाना",
    "see": "देखना",
    "know": "जानना",
    "think": "सोचना",
    "want": "चाहना",
    "need": "ज़रूरत",
    "help": "मदद",
    "all the best": "शुभकामनाएँ",
    "take care": "अपना ख्याल रखना",
    "congratulations": "बधाई हो",
    "happy birthday": "जन्मदिन की शुभकामनाएँ",
    "happy": "खुश",
    "sad": "उदास",
    "big": "बड़ा",
    "small": "छोटा",
    "new": "नया",
    "old": "पुराना",
}

_HI_EN: dict[str, str] = {}
for _en, _hi in _EN_HI.items():
    _HI_EN.setdefault(_hi, _en)

_TRAILING_PUNCT = ".,!?;:'\")"


def _core(token: str) -> str:
    """Lowercased token without surrounding punctuation (for lookup)."""
    return token.strip(_TRAILING_PUNCT).lower()


def _trail(token: str) -> str:
    """Trailing punctuation of a token, to reattach after translation."""
    end = len(token)
    while end > 0 and token[end - 1] in _TRAILING_PUNCT:
        end -= 1
    return token[end:]


def _translate_words(text: str, mapping: dict[str, str]) -> str:
    """Translate longest phrases first, then single words; passthrough unknown."""
    tokens = text.split()
    out: list[str] = []
    i = 0
    while i < len(tokens):
        core = _core(tokens[i])
        if not core:
            out.append(tokens[i])
            i += 1
            continue
        hit: str | None = None
        hit_len = 0
        for size in (4, 3, 2, 1):
            if i + size > len(tokens):
                continue
            phrase = " ".join(_core(t) for t in tokens[i : i + size])
            if phrase in mapping:
                hit = mapping[phrase]
                hit_len = size
                break
        if hit is None:
            out.append(tokens[i])
            i += 1
        else:
            out.append(hit + _trail(tokens[i + hit_len - 1]))
            i += hit_len
    return " ".join(out)


def _is_hindi(text: str) -> bool:
    """True when the text contains Devanagari characters."""
    return any("\u0900" <= ch <= "\u097f" for ch in text)


class TranslatorEngine(Protocol):
    """Plug-in point for a full neural machine translation engine.

    Attach with ``TranslatorSkill.set_engine`` for coverage beyond the
    built-in dictionary (grammar, rare words, other language pairs).
    """

    def translate(self, text: str, src: str, dest: str) -> str:
        """Translate ``text`` from ``src`` to ``dest`` (ISO-639-1 codes)."""
        ...


class DictionaryEngine:
    """Bundled stdlib engine: dictionary lookup with passthrough."""

    def translate(self, text: str, src: str, dest: str) -> str:
        mapping = _HI_EN if src == "hi" else _EN_HI
        return _translate_words(text, mapping)


class TranslatorSkill(Skill):
    """Dictionary-based EN<->HI translator with auto direction detection."""

    name = "translator"
    description = (
        "Translates English<->Hindi word-by-word from a built-in dictionary "
        "(unknown words pass through); direction auto-detected from script."
    )
    intents = ("translate",)
    required_capabilities = ("skills.execute",)
    background = True
    local_only = True

    def __init__(self, engine: TranslatorEngine | None = None) -> None:
        self._engine: TranslatorEngine = engine or DictionaryEngine()

    def set_engine(self, engine: TranslatorEngine) -> None:
        """Attach a full NMT engine for coverage beyond the dictionary."""
        self._engine = engine

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        rest = text[len("translate") :].strip() if text.lower().startswith("translate") else text
        if not rest:
            return "usage: translate <text> (direction auto-detected: Devanagari -> EN, else -> HI)"
        src, dest = ("hi", "en") if _is_hindi(rest) else ("en", "hi")
        return self._engine.translate(rest, src, dest)


SKILLS: list[Skill] = [TranslatorSkill()]
