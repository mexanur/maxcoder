"""
Skill registry — declarative list of skills checked in priority order.
"""
from __future__ import annotations
from typing import AsyncIterator, Optional

from core.skills.base            import Skill, SkillContext, SkillEvent
from core.skills.translation     import TranslationSkill
from core.skills.file_generation import FileGenerationSkill
from core.skills.repo_explorer   import RepoExplorerSkill
from core.skills.web_fetch       import WebFetchSkill
from core.skills.web_compare     import WebCompareSkill
from core.skills.docs_navigation import DocsNavigationSkill
from core.skills.web_search      import WebSearchSkill

# All registered skills. Lower priority = checked first.
# Skills run before any LLM call — first matching skill wins.
SKILLS: list[Skill] = [
    TranslationSkill(),      # priority 9   — "translate X to Y" / "in Spanish"
    FileGenerationSkill(),   # priority 10  — file gen + multi-file
    RepoExplorerSkill(),     # priority 11  — github.com URLs go here
    WebFetchSkill(),         # priority 12  — explicit URLs (incl. PDFs)
    WebCompareSkill(),       # priority 13  — "X vs Y" comparison
    DocsNavigationSkill(),   # priority 14  — "how to X with Y framework" docs deep dive
    WebSearchSkill(),        # priority 15  — generic search intent
    # Future skills:
    #   CodeExecutionSkill(),
    #   ImageGenerationSkill(),
]
# Sort by priority so the router checks the most specific first
SKILLS.sort(key=lambda s: s.priority)


def find_matching_skill(ctx: SkillContext) -> Optional[Skill]:
    """Return the first registered skill that matches the context, or None."""
    for s in SKILLS:
        try:
            if s.matches(ctx):
                return s
        except Exception:
            continue
    return None


async def run_skill(skill: Skill, ctx: SkillContext) -> AsyncIterator[SkillEvent]:
    """Convenience wrapper — run a skill and stream its events."""
    async for ev in skill.execute(ctx):
        yield ev


def list_skills() -> list[dict]:
    """Return a description of every registered skill (for /skills endpoint)."""
    return [
        {
            "name":        s.name,
            "label":       s.label,
            "description": s.description,
            "priority":    s.priority,
        }
        for s in SKILLS
    ]


__all__ = [
    "Skill", "SkillContext", "SkillEvent",
    "SKILLS", "find_matching_skill", "run_skill", "list_skills",
]
