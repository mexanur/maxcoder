"""
Prompt Builder — assembles the final message list sent to the LLM.
Injects: system prompt, long-term memories, RAG context, CoT instructions.
"""
from __future__ import annotations

COT_SYSTEM = """You are MaxCoder, an expert software engineer who produces production-grade
code in ANY programming language.

For EVERY coding request, follow this EXACT structure:

## UNDERSTAND
Restate the request in 2 sentences. List assumptions made.

## PLAN
Numbered implementation plan (max 7 steps).
Identify and call out the trickiest part.

## CODE
Complete, runnable code. Use file paths as code-block headers:
e.g. ```python title=src/main.py

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


def build(
    user_query: str,
    history: list[dict],
    memory_context: str = "",
    rag_context: str = "",
) -> list[dict]:
    """
    Assemble the full messages list for the LLM.

    Args:
        user_query   : the (possibly rewritten) user request
        history      : prior [{"role":..,"content":..}] turns
        memory_context: string from memory.retrieve()
        rag_context  : string from rag_retriever.retrieve()

    Returns:
        list of message dicts ready for Ollama /api/chat
    """
    messages: list[dict] = [{"role": "system", "content": COT_SYSTEM}]

    # Inject memory
    if memory_context:
        messages.append({
            "role": "system",
            "content": memory_context,
        })

    # Inject RAG
    if rag_context:
        messages.append({
            "role": "system",
            "content": rag_context,
        })

    # Prior conversation history (skip the system turns already injected)
    for turn in history:
        if turn.get("role") in ("user", "assistant"):
            messages.append(turn)

    # Current user message
    messages.append({"role": "user", "content": user_query})

    return messages
