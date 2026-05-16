"""
Base Skill interface — declarative skills routed before the LLM pipeline.

Each skill detects whether a query matches its triggers, then executes
deterministic logic (often invoking the LLM internally) and returns a
SkillResult the chat endpoint can stream back.

Skills are checked in priority order. The first one that returns
handled=True wins.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass
class SkillContext:
    """Everything a skill might need from the request."""
    query:         str           # user message (post-reference-resolution)
    history:       list[dict]    # prior messages
    model:         str           # selected model
    web_ctx:       str = ""      # web search context if any
    rag_ctx:       str = ""      # RAG retrieval if any
    memory_ctx:    str = ""      # long-term memory if any
    files:         list[dict] = field(default_factory=list)  # attached files
    chat_memory:   object = None # ChatMemory snapshot — see core/chat_memory.py
    use_reasoning: bool = False  # if True, skill should use thoughtful synthesis


@dataclass
class SkillEvent:
    """One streamed event from a skill — UI renders these incrementally."""
    kind:    str               # e.g. "text", "artifact", "tool", "status"
    content: dict | str        # payload for the UI


class Skill(ABC):
    """Inherit this and register with the skill router."""
    name:        str = "base"        # internal id
    label:       str = "Base"        # user-visible name
    description: str = ""            # short description
    priority:    int = 100           # lower = checked earlier

    @abstractmethod
    def matches(self, ctx: SkillContext) -> bool:
        """Return True if this skill should handle the query."""
        ...

    @abstractmethod
    async def execute(self, ctx: SkillContext) -> AsyncIterator[SkillEvent]:
        """Stream events back to the UI. MUST be an async generator."""
        yield  # type: ignore
