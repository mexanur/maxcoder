"""
RepoExplorerSkill — Level 2 web capability.

Triggers when the user provides a GitHub URL or asks about a repo. Fetches the
README plus a few key source files via raw.githubusercontent (no API needed,
works behind firewalls that block api.github.com), then answers the user's
question using all of them as grounded context.

Examples:
  "explain how https://github.com/tiangolo/fastapi works"
  "what does this repo do: https://github.com/anthropics/claude-code"
  "summarize https://github.com/owner/repo"
"""
from __future__ import annotations
import re
from typing import AsyncIterator

from core.skills.base import Skill, SkillContext, SkillEvent
from core.generator    import stream as llm_stream
from core.web_navigator import parse_github_url, explore_github_repo
from core.skills._synthesize import synthesize


_REPO_SYSTEM = """You are a code-aware research assistant analyzing a GitHub repository.

You have access to:
  - The README (or equivalent project description)
  - Key source files (entry points, configs, manifest)

Your job:
1. Answer the user's specific question using ONLY the files provided.
2. If they asked "what is this" / "explain" / "summarize" → give:
   - One-sentence "what it does"
   - Tech stack (language, frameworks, key deps from package.json/Cargo.toml/etc.)
   - Architecture / main components (from source file structure)
   - Notable features or design decisions visible in the code
   - Caveat: "Files I read were limited to X — for deeper analysis ask about specific files"
3. Use code snippets from the provided files when illustrative (max 3 small snippets).
4. NEVER invent API methods, function names, or file contents not in the provided files.
5. Be concise. Code-heavy when needed, prose elsewhere."""

_REPO_USER = """User asked: {query}

Repository: {owner}/{repo} (branch: {branch})

Files I was able to read:
{files_block}

Now answer the user."""


def _format_files(files: list[dict]) -> str:
    parts = []
    for f in files:
        path = f["path"]
        content = f["content"][:4000]
        # Detect language for fenced code blocks
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        lang_map = {"py": "python", "js": "javascript", "ts": "typescript",
                    "rs": "rust", "go": "go", "md": "markdown",
                    "toml": "toml", "json": "json", "yaml": "yaml", "yml": "yaml"}
        lang = lang_map.get(ext, "")
        parts.append(f"--- {path} ---\n```{lang}\n{content}\n```\n")
    return "\n".join(parts)


# Triggers: GitHub URL OR explicit mention of "repo"/"repository" with a URL
_REPO_VERBS = re.compile(
    r"\b(explain|summari[sz]e|describe|tell\s+me\s+about|what\s+does|"
    r"how\s+does|what['']?s\s+in|analy[sz]e|review|"
    r"break\s+down|walk\s+(?:me\s+)?through)\b",
    re.I,
)


class RepoExplorerSkill(Skill):
    name        = "repo_explorer"
    label       = "GitHub repo"
    description = "Reads README + key files of a GitHub repo and answers questions about it"
    priority    = 11   # before web_fetch (12) so GitHub URLs route here, not generic fetch

    def matches(self, ctx: SkillContext) -> bool:
        # Must have a github.com URL in the query
        return parse_github_url(ctx.query) is not None

    async def execute(self, ctx: SkillContext) -> AsyncIterator[SkillEvent]:
        parsed = parse_github_url(ctx.query)
        if not parsed:
            return
        owner, repo, branch = parsed["owner"], parsed["repo"], parsed["branch"]

        yield SkillEvent(kind="status", content={
            "skill": self.name, "label": self.label,
            "stage": "fetching", "owner": owner, "repo": repo, "branch": branch,
        })

        # Fetch key files
        files = []
        async def _progress(ev):
            pass   # placeholder — could stream sub-status if desired
        try:
            files = await explore_github_repo(owner, repo, branch, on_progress=_progress)
        except Exception as e:
            yield SkillEvent(kind="answer_chunk",
                              content=f"Couldn't explore the repo {owner}/{repo}: {e}")
            yield SkillEvent(kind="done", content={"skill": self.name, "ok": False})
            return

        if not files:
            yield SkillEvent(kind="answer_chunk",
                              content=f"I couldn't read any files from {owner}/{repo}. "
                                       f"The repo may be private, empty, or use an unusual default branch.")
            yield SkillEvent(kind="done", content={"skill": self.name, "ok": False, "files": 0})
            return

        yield SkillEvent(kind="status", content={
            "skill": self.name, "stage": "synthesizing",
            "files_read": len(files),
            "paths": [f["path"] for f in files],
        })

        sources_block = (
            f"Repository: {owner}/{repo} (branch: {branch})\n\n"
            f"Files I was able to read:\n{_format_files(files)}"
        )
        async for ev in synthesize(
            query         = ctx.query,
            sources       = sources_block,
            system_prompt = _REPO_SYSTEM,
            model         = ctx.model,
            use_reasoning = ctx.use_reasoning,
            task_label    = f"exploring {owner}/{repo}",
            num_predict   = 1200,
        ):
            yield ev

        # Citations: each file we read
        yield SkillEvent(kind="citations", content={
            "sources": [{
                "n":       i + 1,
                "title":   f"{owner}/{repo} - {f['path']}",
                "url":     f"https://github.com/{owner}/{repo}/blob/{branch}/{f['path']}",
                "snippet": f["content"][:160],
            } for i, f in enumerate(files)],
        })

        yield SkillEvent(kind="done", content={
            "skill": self.name, "ok": True,
            "files_read": len(files),
        })
