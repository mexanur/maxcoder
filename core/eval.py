"""
MaxCoder Eval Engine.
Scores model responses across 5 dimensions:
  1. Correctness   — does the code run without errors?
  2. Completeness  — are all required parts present?
  3. Code Quality  — style, type hints, error handling
  4. Speed         — tokens per second
  5. Instruction   — did it follow the UNDERSTAND/PLAN/CODE/VERIFY/DELIVER format?

Usage:
  python eval/run_eval.py                  # run full suite
  python eval/run_eval.py --suite coding   # specific suite
"""
from __future__ import annotations
import re, time, subprocess, tempfile, pathlib, json
from dataclasses import dataclass, field, asdict
from typing import Callable


# ── Result dataclass ──────────────────────────────────────────────────────────
@dataclass
class EvalResult:
    prompt_id:       str
    prompt:          str
    response:        str
    model:           str
    # Scores (0.0 – 1.0)
    correctness:     float = 0.0   # code runs without error
    completeness:    float = 0.0   # all required elements present
    code_quality:    float = 0.0   # style checks
    instruction_follow: float = 0.0  # CoT structure present
    latency_s:       float = 0.0   # wall-clock seconds
    tokens_per_sec:  float = 0.0
    overall:         float = 0.0
    notes:           list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ── Scoring helpers ───────────────────────────────────────────────────────────
def _extract_code_blocks(text: str) -> list[tuple[str, str]]:
    """Return list of (lang, code) from fenced blocks."""
    return re.findall(r"```(\w*)[^\n]*\n(.*?)```", text, re.DOTALL)


def score_correctness(response: str, lang: str = "python") -> tuple[float, str]:
    """Try to execute extracted code. Returns (score, note)."""
    blocks = _extract_code_blocks(response)
    if not blocks:
        return 0.0, "no code block found"

    # Find first block matching lang
    code = next(
        (c for l, c in blocks if l.lower() in (lang, "")),
        blocks[0][1]
    )

    ext_map = {"python": "py", "javascript": "js", "bash": "sh"}
    ext     = ext_map.get(lang, "py")
    cmd_map = {"python": ["python"], "javascript": ["node"], "bash": ["bash"]}
    cmd     = cmd_map.get(lang, ["python"])

    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / f"snippet.{ext}"
        p.write_text(code, encoding="utf-8")
        try:
            r = subprocess.run(cmd + [str(p)],
                               capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                return 1.0, "ran successfully"
            # Partial credit for syntax-only errors vs runtime errors
            if "SyntaxError" in r.stderr or "SyntaxError" in r.stdout:
                return 0.1, f"syntax error: {r.stderr[:120]}"
            return 0.4, f"runtime error: {r.stderr[:120]}"
        except subprocess.TimeoutExpired:
            return 0.3, "timeout (15s) — may be waiting for input"
        except FileNotFoundError:
            return 0.5, f"runtime not installed for {lang}"


def score_completeness(response: str, required_keywords: list[str]) -> tuple[float, str]:
    """Check that all required keywords/phrases appear in response."""
    if not required_keywords:
        return 1.0, "no requirements specified"
    found  = [k for k in required_keywords if k.lower() in response.lower()]
    missed = [k for k in required_keywords if k.lower() not in response.lower()]
    score  = len(found) / len(required_keywords)
    note   = f"found {len(found)}/{len(required_keywords)}"
    if missed:
        note += f" | missing: {missed}"
    return round(score, 2), note


def score_code_quality(response: str) -> tuple[float, str]:
    """Heuristic quality checks on code blocks."""
    blocks = _extract_code_blocks(response)
    if not blocks:
        return 0.0, "no code blocks"

    code = "\n".join(c for _, c in blocks)
    score = 1.0
    notes = []

    checks = [
        (r"import \*",                    -0.15, "wildcard import"),
        (r"except:\s*pass",               -0.15, "bare except:pass"),
        (r"print\(.*password",            -0.20, "possible secret in print"),
        (r"TODO|FIXME|HACK",               -0.10, "unresolved TODO/FIXME"),
        (r"def \w+\([^)]*\)(?!\s*->)", -0.05, "missing return type hint (Python)"),
        (r"\beval\(",                    -0.20, "dangerous eval()"),
        (r"shell=True",                    -0.10, "shell=True in subprocess"),
    ]
    for pattern, penalty, label in checks:
        if re.search(pattern, code):
            score = max(0.0, score + penalty)
            notes.append(label)

    # Bonus checks
    if re.search(r"->\s*\w+", code):
        notes.append("+type hints")
    if re.search(r"try:|except \w+", code):
        notes.append("+error handling")
    if re.search(r"pytest|unittest|assert ", code):
        notes.append("+tests present")

    return round(score, 2), ", ".join(notes) if notes else "clean"


def score_instruction_follow(response: str) -> tuple[float, str]:
    """Check for CoT structure: UNDERSTAND PLAN CODE VERIFY DELIVER."""
    sections = ["UNDERSTAND", "PLAN", "CODE", "VERIFY", "DELIVER"]
    found    = [s for s in sections if s in response.upper()]
    score    = len(found) / len(sections)
    note     = f"{len(found)}/{len(sections)} sections: {found}"
    return round(score, 2), note


def compute_overall(r: EvalResult) -> float:
    """Weighted average of all scores."""
    weights = {
        "correctness":        0.35,
        "completeness":       0.25,
        "code_quality":       0.20,
        "instruction_follow": 0.20,
    }
    return round(
        sum(getattr(r, k) * w for k, w in weights.items()), 3
    )


# ── Main scorer ───────────────────────────────────────────────────────────────
async def score_response(
    prompt_id: str,
    prompt: str,
    response: str,
    model: str,
    lang: str = "python",
    required_keywords: list[str] | None = None,
    latency_s: float = 0.0,
    token_count: int = 0,
) -> EvalResult:
    result = EvalResult(
        prompt_id=prompt_id,
        prompt=prompt,
        response=response,
        model=model,
        latency_s=round(latency_s, 2),
        tokens_per_sec=round(token_count / latency_s, 1) if latency_s > 0 else 0,
    )

    result.correctness,        c_note = score_correctness(response, lang)
    result.completeness,       p_note = score_completeness(response, required_keywords or [])
    result.code_quality,       q_note = score_code_quality(response)
    result.instruction_follow, i_note = score_instruction_follow(response)
    result.overall                    = compute_overall(result)
    result.notes = [c_note, p_note, q_note, i_note]

    return result
