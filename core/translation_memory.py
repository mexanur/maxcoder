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
    src_domain = _classify_domain(source)
    if not src_tokens:
        return examples[:k] if min_overlap == 0 else []

    scored = []
    for ex in examples:
        ex_tokens = _tokenize(ex.get("en", ""))
        if not ex_tokens:
            continue
        overlap = len(src_tokens & ex_tokens)
        # Domain match boost: examples from the same domain as the source get
        # a +5 score bump. Examples from a DIFFERENT domain (programming vs.
        # literature) get a -10 penalty — they're worse than no example at all.
        ex_domain = ex.get("domain", "general")
        if ex_domain == src_domain and src_domain != "general":
            overlap += 5
        elif ex_domain != "general" and src_domain != "general" and ex_domain != src_domain:
            overlap -= 10
        scored.append((overlap, ex))
    scored.sort(key=lambda t: -t[0])

    # Only return examples with at least min_overlap matching tokens AND a
    # non-negative score (so cross-domain examples are dropped entirely).
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


# ── Domain-specific post-NLLB rewrites ─────────────────────────────────────
# NLLB is frozen — we can't change its output directly. But for tier-3
# languages, NLLB sometimes uses the general-register synonym instead of the
# academic/literary one ("san'at asari" instead of "badiiy asar"). These
# rewrite files let us deterministically map NLLB's vocabulary to the
# preferred domain term WITHOUT involving an LLM (no hallucination risk).
#
# File format: data/translations/glossaries/<lang>_<domain>.json
#   {
#     "rewrites": { "nllb_phrase": "preferred_phrase", ... },
#     "_meta": { ... }
#   }
_rewrites_cache: dict[str, tuple[float, dict]] = {}


def load_domain_rewrites(target: str, domain: str) -> dict[str, str]:
    """Load post-NLLB rewrite rules for {target_lang}_{domain}. Returns {} if none."""
    key = f"{_lang_key(target)}_{domain.lower()}"
    if not key.strip("_"):
        return {}
    cached = _rewrites_cache.get(key)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]

    path = GLOSS_DIR / f"{key}.json"
    rewrites: dict[str, str] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8")) or {}
            r = data.get("rewrites", {})
            if isinstance(r, dict):
                rewrites = {str(k): str(v) for k, v in r.items() if k and v}
        except Exception:
            rewrites = {}
    _rewrites_cache[key] = (time.time(), rewrites)
    return rewrites


def apply_domain_rewrites(text: str, target: str, domain: str) -> str:
    """Apply domain-specific term rewrites to translated text.

    Rules are applied in INSERTION ORDER (longest/most-specific first if the
    JSON file is authored that way), with word-boundary matching to avoid
    partial replacements inside other words.

    Returns the rewritten text. If no rewrites are defined, returns text unchanged.
    """
    rewrites = load_domain_rewrites(target, domain)
    if not rewrites or not text:
        return text
    out = text
    for old, new in rewrites.items():
        # Case-insensitive whole-phrase replacement. We don't use \b alone
        # because Uzbek apostrophes (o', g') aren't word characters in regex,
        # so \b would split words wrongly. Instead require the match not be
        # preceded/followed by an alpha character.
        pattern = re.compile(
            r"(?<![A-Za-zÀ-ɏ])" + re.escape(old) + r"(?![A-Za-zÀ-ɏ])",
            re.IGNORECASE,
        )

        def _repl(m: "re.Match[str]") -> str:
            # Preserve capitalization: if the matched original was Capitalized
            # (sentence-start) or ALL CAPS, mirror that on the replacement.
            matched = m.group(0)
            if matched.isupper() and len(matched) > 1:
                return new.upper()
            if matched[:1].isupper():
                return new[:1].upper() + new[1:]
            return new

        out = pattern.sub(_repl, out)
    return out


# ── Corpus growth: append new (source, translation) pairs ─────────────────
def _classify_domain(text: str) -> str:
    """Cheap domain heuristic for tagging saved corpus entries.

    Returns one of: programming | literature | general.
    Used so the few-shot retriever can prefer same-domain examples (a literary
    Russian text should NOT be augmented with programming examples).
    """
    if not text:
        return "general"
    low = text.lower()
    prog_markers = ("python", "java", "javascript", "function", "variable",
                    "compile", "runtime", "library", "framework", "api",
                    "programming language", "source code", "garbage collection",
                    "bug", "debug", "stack trace", "off-by-one", "exception",
                    "syntax error", "regex", "algorithm", "datatype",
                    "программирован", "библиотек", "компил", "код ", "функци")
    lit_markers  = ("художеств", "поэзи", "роман", "новелл", "литератур",
                    "сюжет", "персонаж", "стих", "автор", "герой ",
                    "literary", "novel", "poem", "fiction", "narrative",
                    "character speech", "metaphor", "prose")
    if any(m in low for m in prog_markers):
        return "programming"
    if any(m in low for m in lit_markers):
        return "literature"
    return "general"


def append_example(source_text: str, translation: str, target: str,
                    source_lang: str = "en",
                    domain: str | None = None,
                    confidence: float = 1.0) -> bool:
    """Append a new parallel example to data/translations/examples/<lang>.jsonl.

    Used by the translation skill to grow the corpus automatically: every time
    NLLB produces a high-quality translation, we save the pair so future
    requests benefit from richer few-shot context.

    Args:
      domain:     overrides auto-classification ("programming"/"literature"/"general")
      confidence: 0.0–1.0; pairs below 0.7 are rejected to prevent auto-training
                  on garbage outputs.

    Returns True if the example was written, False if rejected (too short,
    duplicate, low-confidence, etc.).
    """
    if confidence < 0.7:
        return False  # don't auto-train on low-confidence translations
    key = _lang_key(target)
    if not key:
        return False
    src = (source_text or "").strip()
    tgt = (translation or "").strip()
    if len(src) < 20 or len(tgt) < 10:
        return False  # too short to be useful as few-shot

    path = EX_DIR / f"{key}.jsonl"

    # Cheap dedup: skip if this exact source already appears in the file.
    if path.exists():
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get(source_lang, "").strip() == src:
                        return False  # already have this pair
                except Exception:
                    continue
        except Exception:
            pass

    record = {
        source_lang: src,
        key: tgt,
        "domain": domain or _classify_domain(src),
    }
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        # Invalidate the cache so the new example is visible immediately
        _examples_cache.pop(key, None)
        return True
    except Exception:
        return False


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
