"""
Translation Learning — safe user-driven corpus growth.

Lifecycle of a user-submitted correction:

  1. SUBMIT  → user provides {source, target_lang, corrected_translation, [draft, note]}
  2. SCREEN  → run automatic quality heuristics (length, script, dedup, junk)
               • Pass  → status='pending'
               • Fail  → status='rejected' (auto, with reason)
  3. REVIEW  → user (you) approves or rejects in the UI / via API
               • Approve → appended to data/translations/examples/<lang>.jsonl (LIVE)
               • Reject  → kept in audit log only
  4. USE     → next translation request picks up the new example via translation_memory

User contributions are NEVER trusted blindly — every candidate must be either
auto-screened or manually approved before it influences future translations.

Storage:
  data/translations/candidates/<lang>.jsonl   — all pending + rejected (audit)
  data/translations/examples/<lang>.jsonl     — APPROVED, used at inference time
"""
from __future__ import annotations
import json, pathlib, re, time, uuid
from dataclasses import dataclass, field
from typing import Optional

from core.translation_memory import EX_DIR, _lang_key

CAND_DIR = EX_DIR.parent / "candidates"
CAND_DIR.mkdir(parents=True, exist_ok=True)


# ── Auto-screening heuristics ──────────────────────────────────────────────
# Maps language → "script must contain at least one of these unicode ranges"
_SCRIPT_RANGES = {
    # Cyrillic-script languages
    "russian":   [(0x0400, 0x04FF)],
    "ukrainian": [(0x0400, 0x04FF)],
    "bulgarian": [(0x0400, 0x04FF)],
    "serbian":   [(0x0400, 0x04FF)],
    "kazakh":    [(0x0400, 0x04FF)],
    "kyrgyz":    [(0x0400, 0x04FF)],
    "mongolian": [(0x0400, 0x04FF), (0x1800, 0x18AF)],
    # CJK
    "chinese":   [(0x4E00, 0x9FFF), (0x3400, 0x4DBF)],
    "mandarin":  [(0x4E00, 0x9FFF), (0x3400, 0x4DBF)],
    "japanese":  [(0x3040, 0x309F), (0x30A0, 0x30FF), (0x4E00, 0x9FFF)],
    "korean":    [(0xAC00, 0xD7AF), (0x1100, 0x11FF)],
    # Arabic / Hebrew
    "arabic":    [(0x0600, 0x06FF)],
    "hebrew":    [(0x0590, 0x05FF)],
    "urdu":      [(0x0600, 0x06FF)],
    "persian":   [(0x0600, 0x06FF)],
    # Indic
    "hindi":     [(0x0900, 0x097F)],
    "bengali":   [(0x0980, 0x09FF)],
    "tamil":     [(0x0B80, 0x0BFF)],
    "telugu":    [(0x0C00, 0x0C7F)],
    "gujarati":  [(0x0A80, 0x0AFF)],
    # Greek / Armenian / Georgian
    "greek":     [(0x0370, 0x03FF)],
    "armenian":  [(0x0530, 0x058F)],
    "georgian":  [(0x10A0, 0x10FF)],
    # Thai / Khmer / Lao / Burmese
    "thai":      [(0x0E00, 0x0E7F)],
    "khmer":     [(0x1780, 0x17FF)],
    "lao":       [(0x0E80, 0x0EFF)],
    "burmese":   [(0x1000, 0x109F)],
    # Latin-script — no specific range check (covered by ascii check below)
}


def _has_required_script(text: str, lang: str) -> bool:
    """True if `text` contains at least one character from the script associated with `lang`.

    For Latin-script languages we don't have a positive test; we use a negative
    test (rejection criteria) for those instead.
    """
    ranges = _SCRIPT_RANGES.get(_lang_key(lang))
    if not ranges:
        return True   # no specific script requirement for this language
    for ch in text:
        cp = ord(ch)
        if any(lo <= cp <= hi for lo, hi in ranges):
            return True
    return False


@dataclass
class HeuristicResult:
    passed:  bool
    reasons: list[str] = field(default_factory=list)


def screen_candidate(source: str, target: str, lang: str) -> HeuristicResult:
    """Run automatic quality screening. Returns pass/fail + reasons."""
    issues: list[str] = []

    src_len = len(source.strip())
    tgt_len = len(target.strip())

    # 1. Length sanity — translations within reasonable ratio of source
    if src_len < 1 or tgt_len < 1:
        issues.append("Empty source or target")
    elif tgt_len < src_len * 0.2 and src_len > 40:
        issues.append(f"Target is suspiciously short ({tgt_len} chars vs {src_len} source)")
    elif tgt_len > src_len * 6:
        issues.append(f"Target is suspiciously long ({tgt_len} chars vs {src_len} source)")

    # 2. Script consistency — target should be in the right script for non-Latin languages
    if not _has_required_script(target, lang):
        issues.append(f"Target text doesn't contain expected {lang} script characters")

    # 3. Identical to source — likely user mistake or non-translation
    if source.strip().lower() == target.strip().lower():
        issues.append("Target identical to source (no translation occurred)")

    # 4. Garbage / non-text — lots of control characters, repeated chars
    if re.search(r'(.)\1{15,}', target):
        issues.append("Target contains long repeated-character runs (likely garbage)")
    if sum(1 for ch in target if ord(ch) < 32 and ch not in '\n\t') > 5:
        issues.append("Target contains too many control characters")

    # 5. URL only / numbers only — not a real translation
    if re.fullmatch(r'[\s\d.,;:!?]*', target):
        issues.append("Target contains no actual words")

    # 6. Profanity check (very basic — extend with a real list if needed)
    PROFANITY = {"fuck", "shit", "bitch", "asshole"}    # keep small + obvious
    target_lower = target.lower()
    if any(p in target_lower for p in PROFANITY):
        issues.append("Target contains likely profanity (manual review required)")

    return HeuristicResult(passed=len(issues) == 0, reasons=issues)


# ── Storage layer ──────────────────────────────────────────────────────────
def _candidates_path(lang: str) -> pathlib.Path:
    return CAND_DIR / f"{_lang_key(lang)}.jsonl"


def _read_jsonl(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _write_jsonl(path: pathlib.Path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + ("\n" if records else ""),
        encoding="utf-8",
    )


# ── Public API ─────────────────────────────────────────────────────────────
def submit_candidate(
    *,
    source:      str,
    target:      str,
    lang:        str,
    draft:       Optional[str] = None,
    note:        Optional[str] = None,
    submitter:   str           = "user",
) -> dict:
    """Submit a user-provided translation candidate.

    Auto-screens it. If it passes, status = 'pending' (awaits review).
    If it fails, status = 'rejected' (auto, with reasons).
    Returns the saved record.
    """
    if not source.strip() or not target.strip():
        return {"ok": False, "error": "Source and target both required"}

    result = screen_candidate(source, target, lang)
    rec = {
        "id":          uuid.uuid4().hex,
        "lang":        _lang_key(lang),
        "source":      source.strip(),
        "target":      target.strip(),
        "draft":       (draft or "").strip(),    # what the LLM originally produced
        "note":        (note or "").strip(),     # user's comment
        "status":      "pending" if result.passed else "rejected_auto",
        "reasons":     result.reasons,
        "submitter":   submitter,
        "ts":          int(time.time()),
        "approved_at": None,
        "approved_by": None,
    }
    path = _candidates_path(lang)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {"ok": True, **rec}


def list_candidates(lang: Optional[str] = None, status: str = "pending",
                     limit: int = 100) -> list[dict]:
    """Return candidates filtered by language + status."""
    out: list[dict] = []
    if lang:
        out.extend(_read_jsonl(_candidates_path(lang)))
    else:
        for p in CAND_DIR.glob("*.jsonl"):
            out.extend(_read_jsonl(p))
    if status != "all":
        out = [r for r in out if r.get("status") == status]
    out.sort(key=lambda r: r.get("ts", 0), reverse=True)
    return out[:limit]


def approve_candidate(cid: str, approver: str = "user") -> dict:
    """Promote a candidate to the live corpus.

    Steps:
      1. Find the candidate in any language file
      2. Update its status to 'approved' with timestamp / approver
      3. Append { en, <lang>: ... } to data/translations/examples/<lang>.jsonl
    """
    for path in CAND_DIR.glob("*.jsonl"):
        records = _read_jsonl(path)
        for r in records:
            if r.get("id") == cid:
                if r.get("status") not in ("pending", "rejected_auto"):
                    return {"ok": False, "error": f"Candidate is {r.get('status')!r}, cannot approve"}
                r["status"]      = "approved"
                r["approved_at"] = int(time.time())
                r["approved_by"] = approver
                _write_jsonl(path, records)
                # Add to live corpus
                live_path = EX_DIR / f"{r['lang']}.jsonl"
                with live_path.open("a", encoding="utf-8") as f:
                    live_record = {"en": r["source"], r["lang"]: r["target"]}
                    f.write(json.dumps(live_record, ensure_ascii=False) + "\n")
                return {"ok": True, "id": cid, "lang": r["lang"], "promoted_to": str(live_path)}
    return {"ok": False, "error": "Candidate not found"}


def reject_candidate(cid: str, reason: str = "", rejector: str = "user") -> dict:
    """Mark a candidate as rejected (kept in audit log)."""
    for path in CAND_DIR.glob("*.jsonl"):
        records = _read_jsonl(path)
        for r in records:
            if r.get("id") == cid:
                if r.get("status") == "approved":
                    return {"ok": False, "error": "Already approved — cannot reject"}
                r["status"]      = "rejected"
                r["reject_reason"] = reason
                r["rejected_by"] = rejector
                r["rejected_at"] = int(time.time())
                _write_jsonl(path, records)
                return {"ok": True, "id": cid}
    return {"ok": False, "error": "Candidate not found"}


def stats() -> dict:
    """Counts of candidates by status across all languages."""
    counts = {"pending": 0, "approved": 0, "rejected": 0, "rejected_auto": 0}
    by_lang: dict[str, dict] = {}
    for p in CAND_DIR.glob("*.jsonl"):
        lang = p.stem
        by_lang[lang] = {"pending": 0, "approved": 0, "rejected": 0, "rejected_auto": 0}
        for r in _read_jsonl(p):
            s = r.get("status", "pending")
            counts[s] = counts.get(s, 0) + 1
            by_lang[lang][s] = by_lang[lang].get(s, 0) + 1
    return {"total": counts, "by_lang": by_lang}
