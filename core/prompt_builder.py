"""
Prompt Builder — assembles the final message list sent to the LLM.
Injects: system prompt, long-term memories, RAG context, CoT instructions.

Two modes:
  build()        — standard chat mode (existing behaviour, unchanged)
  agent_build()  — agentic mode: injects project files + file-op instructions
"""
from __future__ import annotations

# ── Standard chat system prompt (unchanged) ───────────────────────────────────
COT_SYSTEM = """You are MaxCoder, an expert software engineer who produces production-grade code in ANY programming language.

For EVERY coding request, follow this EXACT structure:

## UNDERSTAND
Restate the request in 2 sentences. List assumptions made.

## PLAN
Numbered implementation plan (max 7 steps).
Identify and call out the trickiest part.

## CODE
Complete, runnable code.
Use file paths as code-block headers: e.g. ```python title=src/main.py

## VERIFY
Self-review your code for:
- Logic bugs / off-by-one errors
- Security vulnerabilities
- Missing error handling & edge cases
- Missing imports or dependencies
Fix anything found, inline.

## DELIVER
- Install command(s)
- Run command(s)
- One minimal test / usage example

HARD RULES:
- Never invent APIs or library methods. If unsure, say so.
- Always pin dependency versions in requirements/package files.
- Prefer modern idioms (Python 3.12+, ES2022+, Rust 2021 edition, etc.)
- Type-annotate Python functions.
- Keep prose short. Code speaks louder.
"""

# ── Agent system prompt ───────────────────────────────────────────────────────
AGENT_SYSTEM = """You are MaxCoder Agent, an expert software engineer that directly reads and writes project files — exactly like Cursor or Claude Code.

## HOW YOU WORK
You are given the CURRENT STATE of all project files before every message.
You read them, understand the full context, then make PRECISE edits.

## OUTPUT FORMAT — MANDATORY
For every file you create or change, output a block like this:

@@CREATE path/to/newfile.ext
```lang
<full file content>
```

@@EDIT path/to/existing.ext
```lang
<full updated file content — always output the COMPLETE file, not just changed lines>
```

@@DELETE path/to/file.ext

To run code after writing it:
@@RUN python
```python
<code>
```

## RULES
1. ALWAYS output the COMPLETE file content for CREATE and EDIT — never partial snippets.
2. Use EDIT (not CREATE) when the file already exists in the project snapshot.
3. Only touch files relevant to the request — do NOT rewrite unrelated files.
4. File paths must be relative (e.g. src/main.py, not /workspace/src/main.py).
5. After all @@-blocks, write a SHORT human summary of what you changed and why.
6. If the project is empty, design a clean folder structure before creating files.
7. Never invent library APIs. If you are unsure of a method signature, say so.
8. Always include install + run instructions in your summary.
"""


def build(
    user_query:     str,
    history:        list[dict],
    memory_context: str = "",
    rag_context:    str = "",
) -> list[dict]:
    """
    Standard chat mode — unchanged from v2.
    """
    messages: list[dict] = [{"role": "system", "content": COT_SYSTEM}]

    if memory_context:
        messages.append({"role": "system", "content": memory_context})

    if rag_context:
        messages.append({"role": "system", "content": rag_context})

    for turn in history:
        if turn.get("role") in ("user", "assistant"):
            messages.append(turn)

    messages.append({"role": "user", "content": user_query})
    return messages


def agent_build(
    user_query:      str,
    history:         list[dict],
    project_snapshot: str = "",
    memory_context:  str  = "",
) -> list[dict]:
    """
    Agentic mode — injects project file snapshot + structured output instructions.
    Used by the /agent/chat endpoint.
    """
    messages: list[dict] = [{"role": "system", "content": AGENT_SYSTEM}]

    if memory_context:
        messages.append({"role": "system", "content": memory_context})

    if project_snapshot:
        messages.append({
            "role":    "system",
            "content": project_snapshot,
        })
    else:
        messages.append({
            "role":    "system",
            "content": "CURRENT PROJECT FILES:\n\n(empty project — no files yet)",
        })

    for turn in history:
        if turn.get("role") in ("user", "assistant"):
            messages.append(turn)

    messages.append({"role": "user", "content": user_query})
    return messages
