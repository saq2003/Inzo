"""Multilingual voice-text normalization: Devanagari transliteration + cleanup.

Real (deterministic, stdlib): :func:`normalize_hinglish` transliterates
Devanagari script to Latin, converts Devanagari digits to ASCII, collapses
common Hinglish spelling variants (``nahi``/``nhi`` → ``nahin``), and
normalizes whitespace/punctuation. The transliteration is conservative and
documented — it is a phonetic mapping, not a full Indic NLP engine.
"""

from __future__ import annotations

import re
import unicodedata

from skills.base import Skill, SkillContext

# --- Devanagari transliteration tables -------------------------------------

#: Independent vowels: अ आ इ ई उ ऊ ऋ ए ऐ ओ औ
_VOWELS: dict[str, str] = {
    "अ": "a",
    "आ": "aa",
    "इ": "i",
    "ई": "ee",
    "उ": "u",
    "ऊ": "oo",
    "ऋ": "ri",
    "ए": "e",
    "ऐ": "ai",
    "ओ": "o",
    "औ": "au",
}

#: Dependent vowel signs (matras): ा ि ी ु ू ृ े ै ो ौ
_MATRAS: dict[str, str] = {
    "ा": "aa",
    "ि": "i",
    "ी": "ee",
    "ु": "u",
    "ू": "oo",
    "ृ": "ri",
    "े": "e",
    "ै": "ai",
    "ो": "o",
    "ौ": "au",
}

#: Consonants क..ज्ञ in traditional order (inherent 'a' included).
_CONSONANTS: dict[str, str] = {
    "क": "ka",
    "ख": "kha",
    "ग": "ga",
    "घ": "gha",
    "ङ": "nga",
    "च": "cha",
    "छ": "chha",
    "ज": "ja",
    "झ": "jha",
    "ञ": "nya",
    "ट": "ta",
    "ठ": "tha",
    "ड": "da",
    "ढ": "dha",
    "ण": "na",
    "त": "ta",
    "थ": "tha",
    "द": "da",
    "ध": "dha",
    "न": "na",
    "प": "pa",
    "फ": "pha",
    "ब": "ba",
    "भ": "bha",
    "म": "ma",
    "य": "ya",
    "र": "ra",
    "ल": "la",
    "व": "va",
    "श": "sha",
    "ष": "sha",
    "स": "sa",
    "ह": "ha",
    "क्ष": "ksha",
    "त्र": "tra",
    "ज्ञ": "gya",
}

#: Devanagari digits ०-९ → ASCII.
_DIGITS: dict[str, str] = {chr(0x0966 + i): str(i) for i in range(10)}

_VIRAMA = "्"  # halant: kills the inherent 'a' of the preceding consonant
_ANUSVARA = "ं"  # → 'n'
_VISARGA = "ः"  # → 'h'

#: Common Hinglish spelling variants collapsed to one canonical form.
_VARIANT_MAP: dict[str, str] = {
    "nahi": "nahin",
    "naheen": "nahin",
    "nhi": "nahin",
    "nhin": "nahin",
    "nahin": "nahin",
    "haan": "haan",
    "han": "haan",
    "acha": "achha",
    "accha": "achha",
    "achha": "achha",
    "kya": "kya",
    "kyon": "kyon",
    "kyun": "kyon",
    "mein": "mein",
    "main": "mein",
    "tum": "tum",
    "aap": "aap",
    "hai": "hai",
    "hain": "hain",
    "tha": "tha",
    "thi": "thi",
    "the": "the",
}

_WS_RUN = re.compile(r"\s+")
_PUNCT_RUN = re.compile(r"[^\w\s]", re.UNICODE)


def transliterate_devanagari(text: str) -> str:
    """Transliterate Devanagari characters in ``text`` to Latin (phonetic).

    Rules: independent vowels map directly; a consonant emits its inherent
    'a' unless followed by a matra (replaces the 'a') or a virama (drops the
    'a'). Anusvara → 'n', visarga → 'h'. Non-Devanagari characters pass
    through unchanged.
    """
    out: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in _VOWELS:
            out.append(_VOWELS[ch])
        elif ch in _CONSONANTS:
            base = _CONSONANTS[ch]
            nxt = text[i + 1] if i + 1 < len(text) else ""
            if nxt == _VIRAMA:
                out.append(base[:-1])  # drop inherent 'a'
                i += 1
            elif nxt in _MATRAS:
                out.append(base[:-1] + _MATRAS[nxt])  # matra replaces 'a'
                i += 1
            else:
                out.append(base)
        elif ch == _ANUSVARA:
            out.append("n")
        elif ch == _VISARGA:
            out.append("h")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def normalize_hinglish(text: str) -> str:
    """Normalize Hinglish/Devanagari voice text (deterministic).

    Steps: NFKC normalize → Devanagari→Latin transliteration → Devanagari
    digits→ASCII → lowercase → collapse common spelling variants →
    strip punctuation → collapse whitespace.
    """
    text = unicodedata.normalize("NFKC", text)
    text = transliterate_devanagari(text)
    text = "".join(_DIGITS.get(ch, ch) for ch in text)
    text = text.lower()
    words = [_VARIANT_MAP.get(word, word) for word in text.split()]
    text = " ".join(words)
    text = _PUNCT_RUN.sub(" ", text)
    return _WS_RUN.sub(" ", text).strip()


class MultilingualSkill(Skill):
    """Normalizes mixed Hindi/English voice transcripts."""

    name = "voice_multilingual"
    description = "Transliterates Devanagari and normalizes Hinglish voice text."
    intents = ("voice.normalize",)
    required_capabilities = ("skills.execute",)
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        """Normalize the message text and return the normalized form."""
        return normalize_hinglish(context.message)


SKILLS: list[Skill] = [MultilingualSkill()]
