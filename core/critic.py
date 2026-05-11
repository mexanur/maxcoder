"""
Self-Critique loop — the model reviews its own output and fixes issues.
Runs up to max_rounds of (critique → fix) cycles.
"""
from __future__ import annotations
from core.generator import generate

CRITIC_SYSTEM = """You are a senior code reviewer. Analyze the code below for:
1. Logic bugs and off-by-one errors
2. Security vulnerabilities (injection, hardcoded secrets, etc.)
3. Missing error handling and edge cases
4. Missing imports or undefined variables
5. Style / performance issues

If you find issues, list them as:
ISSUES:
- <issue 1>
- <issue 2>

If the code is correct and complete, respond with exactly: LGTM
Do NOT rewrite the code. Only list issues or say LGTM.
"""

FIX_SYSTEM = """You are MaxCoder. Fix ONLY the listed issues in the code below.
Output the COMPLETE corrected code with the same file structure.
Do not change anything that wasn't listed as an issue.
"""


async def critique_and_fix(
    draft: str,
    model: str | None = None,
    max_rounds: int = 2,
) -> tuple[str, list[str]]:
    """
    Run self-critique loop on a draft response.

    Returns:
        (final_text, list_of_critique_logs)
    """
    logs: list[str] = []

    for round_num in range(max_rounds):
        critique_msgs = [
            {"role": "system", "content": CRITIC_SYSTEM},
            {"role": "user", "content": draft},
        ]
        review = await generate(critique_msgs, model=model)
        logs.append(f"Round {round_num + 1} critique:\n{review}")

        if "LGTM" in review.upper():
            break

        fix_msgs = [
            {"role": "system", "content": FIX_SYSTEM},
            {"role": "user",
             "content": f"ISSUES:\n{review}\n\nORIGINAL CODE:\n{draft}"},
        ]
        draft = await generate(fix_msgs, model=model)
        logs.append(f"Round {round_num + 1} fix applied.")

    return draft, logs
