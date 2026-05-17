"""
Translation Memory — parallel corpus + glossary management for the translation skill.

Storage layout (data/translations/):
  glossaries/<lang>.json       — { english_term: native_term, ... }
  examples/<lang>.jsonl        — { "en": "...", "<lang>": "..." } per line

Loading is lazy + cached so we don't read files on every translation call.

How it's used by TranslationSkill:
  - At call time, load_glossary(target) returns the term map for the prompt
  - find_relevant_examples(source, target, k=5) returns the k example pairs
    whose English side overlaps most with the user's source text
  - format_examples_for_prompt(examples, target) returns a ready-to-inject block

Anyone can drop new JSON/JSONL files into data/translations/ to expand coverage —
they're picked up on the next request (with a 60-second TTL cache).
"""
from __future__ import annotations
import json, pathlib, re, time
from typing import Optional

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "translations"
GLOSS_DIR = DATA_DIR / "glossaries"
EX_DIR    = DATA_DIR / "examples"
GLOSS_DIR.mkdir(parents=True, exist_ok=True)
EX_DIR.mkdir(parents=True, exist_ok=True)

_CACHE_TTL = 60   # seconds
_glossary_cache: dict[str, tuple[float, dict]] = {}
_examples_cache: dict[str, tuple[float, list[dict]]] = {}


def _lang_key(target: str) -> str:
    """Normalize a target language name to a stable lowercase key."""
    return re.sub(r"[^a-z]", "", target.lower())


# ── Glossary loading ────────────────────────────────────────────────────────
def load_glossary(target: str) -> dict:
    """Load { english_term: native_term, ... } for the given target language.

    Returns empty dict if no file exists for that language.
    """
    key = _lang_key(target)
    if not key:
        return {}
    cached = _glossary_cache.get(key)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]

    path = GLOSS_DIR / f"{key}.json"
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8")) or {}
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
    _glossary_cache[key] = (time.time(), data)
    return data


def format_glossary_for_prompt(glossary: dict, max_terms: int = 30) -> str:
    """Format a glossary as bullet lines for injection into the system prompt."""
    if not glossary:
        return ""
    items = list(glossary.items())[:max_terms]
    width = max((len(k) for k, _ in items), default=20)
    lines = [f"   {k.ljust(width)} → {v}" for k, v in items]
    return "\n".join(lines)


# ── Parallel examples (translation memory) ─────────────────────────────────
def load_examples(target: str) -> list[dict]:
    """Load all parallel examples for the target language.

    Returns: [ { "en": "English text", "<lang>": "Native text", ... }, ... ]
    """
    key = _lang_key(target)
    if not key:
        return []
    cached = _examples_cache.get(key)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]

    path = EX_DIR / f"{key}.jsonl"
    out: list[dict] = []
    if path.exists():
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if "en" in rec and key in {_lang_key(k) for k in rec.keys() if k != "en"}:
                        out.append(rec)
                except Exception:
                    continue
        except Exception:
            pass
    _examples_cache[key] = (time.time(), out)
    return out


def _tokenize(text: str) -> set[str]:
    """Crude word tokenizer for similarity scoring."""
    return set(re.findall(r"[a-z0-9]{3,}", text.lower()))


def find_relevant_examples(source: str, target: str, k: int = 5,
                            min_overlap: int = 1) -> list[dict]:
    """Pick the k examples whose English side overlaps most with the source.

    IMPORTANT: returns EMPTY list if no example has token overlap with the
    source. Padding with irrelevant examples confuses small models — better
    to give no few-shot than misleading few-shot.

    To force inclusion of generic examples regardless of overlap, set min_overlap=0.
    """
    examples = load_examples(target)
    if not examples:
        return []
    src_tokens = _tokenize(source)
    if not src_tokens:
        return examples[:k] if min_overlap == 0 else []

    scored = []
    for ex in examples:
        ex_tokens = _tokenize(ex.get("en", ""))
        if not ex_tokens:
            continue
        overlap = len(src_tokens & ex_tokens)
        scored.append((overlap, ex))
    scored.sort(key=lambda t: -t[0])

    # Only return examples with at least min_overlap matching tokens.
    # If nothing meets the bar, return EMPTY — the system prompt's rules
    # are enough on their own; bad examples are worse than no examples.
    top = [ex for sc, ex in scored if sc >= min_overlap][:k]
    return top


def format_examples_for_prompt(examples: list[dict], target: str) -> str:
    """Render parallel examples as a few-shot block for the system prompt."""
    if not examples:
        return ""
    key = _lang_key(target)
    lines = ["EXAMPLES of high-quality English → " + target + " translation:"]
    for i, ex in enumerate(examples, 1):
        en = ex.get("en", "").strip()
        # Look up the native side under any of: lower-case key, original target name
        native = ex.get(key) or ex.get(target.lower()) or ex.get(target) or ""
        if not en or not native:
            continue
        lines.append(f"\nExample {i}:")
        lines.append(f"  English: {en}")
        lines.append(f"  {target}: {native.strip()}")
    return "\n".join(lines)


# ── Stats helpers ──────────────────────────────────────────────────────────
def available_languages() -> dict:
    """Return summary of what languages have data: { lang: {gloss: N, examples: M} }."""
    out: dict[str, dict] = {}
    for p in GLOSS_DIR.glob("*.json"):
        key = p.stem
        try:
            n = len(json.loads(p.read_text(encoding="utf-8")) or {})
        except Exception:
            n = 0
        out.setdefault(key, {})["gloss"] = n
    for p in EX_DIR.glob("*.jsonl"):
        key = p.stem
        try:
            m = sum(1 for line in p.read_text(encoding="utf-8").splitlines() if line.strip())
        except Exception:
            m = 0
        out.setdefault(key, {})["examples"] = m
    return out
