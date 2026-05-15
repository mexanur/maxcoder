"""
Uncertainty Handler — detect and surface when the model isn't sure.

Two complementary signals:
  1. Verbalized confidence — we explicitly ask the model to rate its answer
     (HIGH / MEDIUM / LOW) and explain why.
  2. Hedge-word detection — even if the model doesn't verbalize, we scan for
     uncertainty signals ("probably", "I think", "might be", ...).

The combined signal drives:
  - UI badges (⚠️ Low Confidence)
  - "Verify with web" button surfacing
  - Optional auto-escalation (e.g. re-ask with web search forced on)
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional

from core.generator import generate


# ── Hedge-word detection ────────────────────────────────────────────────────
# Phrases that indicate the model isn't certain. Weighted so strong hedges
# count more than mild ones.
_HEDGE_PATTERNS: list[tuple[re.Pattern, int]] = [
    # Strong uncertainty (weight 3)
    (re.compile(r"\bi['’]?m\s+not\s+(sure|certain|positive)\b", re.I), 3),
    (re.compile(r"\bi\s+don['’]?t\s+know\b", re.I),                    3),
    (re.compile(r"\bcannot\s+confirm\b", re.I),                        3),
    (re.compile(r"\bwithout\s+more\s+(info|information|context)\b", re.I), 3),
    (re.compile(r"\bmay\s+not\s+exist\b", re.I),                       3),
    (re.compile(r"\bhallucinat", re.I),                                3),
    # Medium hedges (weight 2)
    (re.compile(r"\bi\s+(think|believe|suspect|guess)\b", re.I),       2),
    (re.compile(r"\bas\s+far\s+as\s+i\s+know\b", re.I),                2),
    (re.compile(r"\bbased\s+on\s+my\s+(knowledge|training)\b", re.I),  2),
    (re.compile(r"\bprobably|presumably\b", re.I),                     2),
    (re.compile(r"\bnot\s+entirely\s+sure\b", re.I),                   2),
    # Weak hedges (weight 1) — single occurrence ok, multiple is a signal
    (re.compile(r"\bmight\s+(be|need|have|cause)\b", re.I),            1),
    (re.compile(r"\bcould\s+(be|need|have|cause)\b", re.I),            1),
    (re.compile(r"\btypically|usually|often|generally\b", re.I),       1),
    (re.compile(r"\blikely\b", re.I),                                  1),
    (re.compile(r"\bperhaps|possibly\b", re.I),                        1),
]

# Phrases that explicitly suggest checking external sources
_VERIFY_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(check|verify|consult)\s+(the\s+)?(docs?|documentation|website|source)\b", re.I),
    re.compile(r"\brefer\s+to\s+(the\s+)?(docs?|documentation)\b", re.I),
    re.compile(r"\blook\s+up\b", re.I),
    re.compile(r"\bsee\s+(the\s+)?(official\s+)?(docs?|documentation)\b", re.I),
]


def detect_hedges(text: str) -> dict:
    """Score uncertainty signals in a piece of text.

    Returns:
      {
        "score":   int — total weighted hedges
        "matches": list of {phrase, weight}
        "verify_suggested": bool — model already said "check the docs"
      }
    """
    matches: list[dict] = []
    total = 0
    for pat, weight in _HEDGE_PATTERNS:
        for m in pat.finditer(text):
            matches.append({"phrase": m.group(0), "weight": weight})
            total += weight

    verify_suggested = any(p.search(text) for p in _VERIFY_PATTERNS)
    return {
        "score":            total,
        "matches":          matches[:8],   # cap for display
        "verify_suggested": verify_suggested,
    }


# ── Verbalized confidence ───────────────────────────────────────────────────
_VERBALIZE_PROMPT = """Below is an answer that was just produced. You are auditing it for hallucinations.

---
{answer}
---

Step 1: List every external library, package, framework, function, method, or
API name mentioned in the answer (NOT standard language built-ins like `print`,
`for`, `len`). Just the names, comma-separated. If none, write "none".

Step 2: For each name in your list, mentally ask "Have I seen this in real
training data, or did I just invent it because the user mentioned it?" Names
that exactly match a user-given term are SUSPICIOUS — they're often hallucinated
because the model felt obligated to use them.

Step 3: Rate overall factual confidence. Reply in EXACTLY this format:

Names: <comma-separated list or "none">
Confidence: HIGH | MEDIUM | LOW
Reason: <one sentence — be honest, especially about names that may not exist>

Rules:
- HIGH only if every name listed is a real, widely-known library/API.
- MEDIUM if structure is right but some names may be fabricated.
- LOW if ANY name in the list might not actually exist (e.g. names mirroring
  the user's question rather than real APIs the model knows).
- Hallucinating > admitting LOW. Be willing to flag your own work."""


_CONF_RE = re.compile(
    r"confidence\s*:\s*(HIGH|MEDIUM|LOW)\s*\n+\s*reason\s*:\s*(.+)",
    re.I,
)
_NAMES_RE = re.compile(r"names?\s*:\s*(.+?)(?:\n|$)", re.I)


def parse_confidence(text: str) -> tuple[str, str, str]:
    """Extract (level, reason, names_list) from verbalized confidence reply."""
    m = _CONF_RE.search(text)
    n = _NAMES_RE.search(text)
    names = n.group(1).strip()[:300] if n else ""
    if not m:
        return "UNKNOWN", text.strip()[:200], names
    return m.group(1).upper(), m.group(2).strip().split("\n")[0][:300], names


async def verbalize_confidence(answer: str, model: str = "qwen2.5-coder:3b") -> dict:
    """Ask the model to audit its answer for hallucinated library/API names.
    Returns {"level", "reason", "names"}. Uses the fast base model (3B).
    """
    msgs = [
        {"role": "system", "content": "You are a hallucination auditor. Be ruthlessly honest about made-up names."},
        {"role": "user",   "content": _VERBALIZE_PROMPT.format(answer=answer)},
    ]
    try:
        raw = await generate(
            msgs, model=model,
            options={"num_predict": 200, "temperature": 0.1, "num_ctx": 4096},
        )
    except Exception as e:
        return {"level": "UNKNOWN", "reason": f"(could not verify: {e})", "names": ""}
    level, reason, names = parse_confidence(raw)
    return {"level": level, "reason": reason, "names": names}


# ── Combined assessment ─────────────────────────────────────────────────────
@dataclass
class UncertaintyResult:
    level:             str                # HIGH | MEDIUM | LOW | UNKNOWN
    verbalized_level:  str                # what the model itself reported
    verbalized_reason: str                # the explanation it gave
    audited_names:     str                # comma-separated names model audited
    hedge_score:       int                # numeric hedge intensity in the answer
    hedge_matches:     list[dict]         # specific phrases that triggered
    verify_suggested:  bool               # model already said "check docs"
    show_badge:        bool               # frontend should warn the user
    suggest_web:       bool               # frontend should offer "verify with web"

    def to_dict(self) -> dict:
        return {
            "level":             self.level,
            "verbalized_level":  self.verbalized_level,
            "verbalized_reason": self.verbalized_reason,
            "audited_names":     self.audited_names,
            "hedge_score":       self.hedge_score,
            "hedge_matches":     self.hedge_matches,
            "verify_suggested":  self.verify_suggested,
            "show_badge":        self.show_badge,
            "suggest_web":       self.suggest_web,
        }


# Hedge score thresholds — tuned empirically
HEDGE_LOW    = 0   # everything below this is HIGH
HEDGE_MEDIUM = 3   # 1-3 = MEDIUM
HEDGE_HIGH   = 6   # 4+ = LOW


async def assess(
    answer:          str,
    skip_verbalize:  bool = False,
    model:           str  = "qwen2.5-coder:3b",
) -> UncertaintyResult:
    """Full uncertainty assessment combining hedge detection + verbalization."""
    hedges = detect_hedges(answer)

    if skip_verbalize:
        verb = {"level": "UNKNOWN", "reason": "", "names": ""}
    else:
        verb = await verbalize_confidence(answer, model=model)

    # Combine signals — take the more pessimistic of the two
    score = hedges["score"]
    if score >= HEDGE_HIGH:
        hedge_level = "LOW"
    elif score >= HEDGE_MEDIUM:
        hedge_level = "MEDIUM"
    else:
        hedge_level = "HIGH"

    levels = ["HIGH", "MEDIUM", "LOW", "UNKNOWN"]
    # If either says LOW, we go LOW. If either says MEDIUM, MEDIUM. Etc.
    rank = {"LOW": 3, "MEDIUM": 2, "HIGH": 1, "UNKNOWN": 0}
    final = max([verb["level"], hedge_level], key=lambda x: rank.get(x, 0))

    return UncertaintyResult(
        level             = final,
        verbalized_level  = verb["level"],
        verbalized_reason = verb["reason"],
        audited_names     = verb.get("names", ""),
        hedge_score       = score,
        hedge_matches     = hedges["matches"],
        verify_suggested  = hedges["verify_suggested"],
        show_badge        = final in ("MEDIUM", "LOW"),
        # Offer "Verify with web" for both MEDIUM and LOW — anything below HIGH
        # benefits from external corroboration.
        suggest_web       = final in ("MEDIUM", "LOW") or hedges["verify_suggested"],
    )
