"""
Smart File Generation Skill — multi-file, planning-aware, dependency-aware.

This is not a one-shot wrapper. It runs a small agent loop:

  1. PLAN: ask the LLM to break the request into a list of file tasks
     (one task per file). Each task has format, title, brief, dependencies.

  2. EXECUTE: for each task in order:
       - Gather context from prior task outputs it depends on
       - If complex (math, analysis, requires reasoning) → run reasoner
       - Else direct LLM content generation
       - Wrap in @@GENERATE:fmt ... @@END
       - Stream to UI

  3. SYNTHESIS: if the original request asks for a summary/overview file
     that depends on multiple prior outputs, generate it last.

Examples it handles:
  • "Generate a TXT with Hello"
       → 1 task, fast path
  • "Generate a CSV with employee data and a PDF report about it"
       → 2 tasks, task 2 depends on task 1
  • "Solve these 3 math problems, each in a PDF with explanation"
       → 3 tasks, each independent, each uses reasoner
  • "Generate 5 files and a TXT summary of all of them"
       → 5 tasks + 1 synthesis task depending on tasks 1-5
"""
from __future__ import annotations
import json, re
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

from core.skills.base import Skill, SkillContext, SkillEvent
from core.generator    import generate, stream as llm_stream
from core.reasoner     import (
    reason as run_reason,
    reason_stream as run_reason_stream,
    classify as classify_task,
    extract_thinking,
)
from core.chat_memory  import memory_summary

# Bilingual support — pulled in lazily so file_generation still works
# without NLLB (e.g. on CI with no transformers install).
try:
    from core.translators import nllb_translate, supported_languages as _nllb_langs
    _BILINGUAL_OK = True
except Exception:
    _BILINGUAL_OK = False
    _nllb_langs   = lambda: set()
from core.file_generator import parse_markdown_blocks, block_text_for_translation

# ── Intent detection ────────────────────────────────────────────────────────
_TRIGGER_RE = re.compile(
    r"\b(generate|create|make|produce|build|write|give\s+me|solve|answer)\b"
    r"[\s\S]{0,200}?\b("
    r"pdf|docx|doc|word\s+(?:document|doc|file)?|"
    r"xlsx|xls|excel(?:\s+(?:sheet|file|spreadsheet))?|spreadsheet|"
    r"csv|comma[- ]separated|"
    r"txt|text\s+file|plain\s+text|file"
    r")\b",
    re.I,
)

_FMT_MAP = {
    "pdf":          "pdf",
    "docx":         "docx",  "doc":  "docx",  "word":  "docx",
    "xlsx":         "xlsx",  "xls":  "xlsx",  "excel": "xlsx",  "spreadsheet": "xlsx",
    "csv":          "csv",
    "txt":          "txt",   "text": "txt",   "file":  "txt",
}

# Heuristic — does this query need real reasoning before content?
_COMPLEX_RE = re.compile(
    r"\b("
    r"analy(?:ze|sis|tic|tical)|report|summary|summarize|"
    r"based\s+on|comprehensive|detailed|research|review|"
    r"explain|explanation|why|how\s+does|how\s+do|"
    r"compare|evaluate|assess|"
    r"math(?:s|ematic|ematical)|problem|solve|prove|"
    r"calculat|derivative|integrate|equation|formula|"
    r"algorithm|design|architecture|tradeoffs?|"
    r"from\s+(?:the|my|attached|uploaded)"
    r")\b",
    re.I,
)

# Heuristic — does this request multiple files?
_MULTI_RE = re.compile(
    r"\b("
    r"\d+\s+(?:files?|pdfs?|docs?|txts?|csvs?|xlsxs?)|"
    r"several|multiple|each|every|all\s+\w+|"
    r"\w+\s+and\s+(?:a\s+)?\w+\s+(?:and|file)|"
    r"as\s+well\s+as|"
    r"plus\s+a|and\s+also"
    r")\b",
    re.I,
)


def _detect_format(query: str) -> Optional[str]:
    m = _TRIGGER_RE.search(query)
    if not m:
        return None
    keyword = m.group(2).lower().split()[0]
    return _FMT_MAP.get(keyword)


def _looks_multi(query: str) -> bool:
    return bool(_MULTI_RE.search(query))


def _looks_complex(query: str) -> bool:
    return bool(_COMPLEX_RE.search(query))


# ── Bilingual intent detection ──────────────────────────────────────────────
# Patterns that indicate the user wants a side-by-side / dual-language file:
#   "translate [it / the answer / this] to <lang>"  + a file format
#   "in <lang>"  +  "compar" / "side by side" / "bilingual"  + format
#   "bilingual <lang>"
# We only emit the bilingual variant for PDF — other formats (xlsx/csv/docx)
# don't have a clean dual-language layout yet.
_BILINGUAL_CUE_RE = re.compile(
    r"\b("
    r"bilingual|multilingual|side[-\s]by[-\s]side|compar(?:e|ison)|both\s+versions?|"
    r"in\s+english\s+and|english\s+and|"
    r"translate(?:\s+(?:it|this|the\s+\w+))?\s+(?:to|into|in)|"
    r"translation\s+(?:to|into|of|in)|"
    r"translated\s+(?:to|into|in)"
    r")\b",
    re.I,
)

def _detect_bilingual_targets(query: str) -> list[str]:
    """Return the list of target languages for a multilingual PDF request.

    Empty list means no multilingual flow (request goes through plain PDF).
    For "translate to Russian and Uzbek" returns ["russian", "uzbek"].
    For "in English and Russian for comparison" returns ["russian"] (English
    is treated as the source).
    """
    if not _BILINGUAL_OK or not _BILINGUAL_CUE_RE.search(query):
        return []
    if _detect_format(query) != "pdf":
        return []
    langs = _nllb_langs()
    if not langs:
        return []
    pattern = "|".join(sorted((re.escape(l) for l in langs), key=len, reverse=True))

    seen: list[str] = []
    # Priority 1: every "to/into <lang>" / "in <lang>" mention after a cue.
    for m in re.finditer(rf"\b(?:to|into)\s+({pattern})\b", query, re.I):
        c = m.group(1).lower()
        if c not in seen:
            seen.append(c)

    # Priority 2: connector form "<lang> and <lang>" — catches the second
    # target in "translate to Russian and Uzbek" since "and Uzbek" doesn't
    # have a to/into prefix.
    for m in re.finditer(rf"\band\s+({pattern})\b", query, re.I):
        c = m.group(1).lower()
        if c not in seen and c != "english":
            seen.append(c)

    # Priority 3: any other bare language mention (skip english — it's the source).
    if not seen:
        for m in re.finditer(rf"\b({pattern})\b", query, re.I):
            c = m.group(1).lower()
            if c != "english" and c not in seen:
                seen.append(c)

    return seen


def _detect_bilingual_target(query: str) -> Optional[str]:
    """Back-compat single-target helper."""
    targets = _detect_bilingual_targets(query)
    return targets[0] if targets else None


_LANG_LABELS = {
    "english": "English", "spanish": "Español", "french": "Français",
    "german": "Deutsch", "italian": "Italiano", "portuguese": "Português",
    "russian": "Русский", "chinese": "中文", "mandarin": "中文",
    "japanese": "日本語", "korean": "한국어", "arabic": "العربية",
    "hebrew": "עברית", "uzbek": "O'zbek", "kazakh": "Қазақша",
    "ukrainian": "Українська", "turkish": "Türkçe", "vietnamese": "Tiếng Việt",
    "thai": "ภาษาไทย", "hindi": "हिन्दी", "urdu": "اردو", "bengali": "বাংলা",
    "tamil": "தமிழ்", "polish": "Polski", "dutch": "Nederlands",
    "swedish": "Svenska", "greek": "Ελληνικά",
}


def extract_literal_source(query: str) -> Optional[str]:
    """If the user pasted the literal source text in the query (the common
    'translate this: <text> into X' pattern), pull it out so we can skip the
    LLM content-generation step entirely.

    Why this matters: when the user says "Generate a PDF with this translation
    of sentences: <text>", running content generation would (a) pull in
    chat_memory context the user doesn't want and (b) burn tokens to
    paraphrase content the user already provided exactly.

    Returns the literal source if confidently detected, else None.
    """
    # Pattern: a translate/translation phrase, then any words, then ":",
    # then the SOURCE TEXT, then "into"/"to" + language. We're permissive on
    # the words between trigger and colon (e.g. "translate this paragraph:",
    # "translation of these sentences:", "translation of:").
    # Form A: <translate phrase> ... : <SOURCE> into/to <LANG>
    m = re.search(
        r"\b(?:translate|translation)\b[^:\n]{0,40}:\s*(.+?)\s+(?:into|to)\s+\w+",
        query, re.I | re.S,
    )
    if m:
        src = m.group(1).strip()
        if 10 <= len(src) <= 5000:
            return src

    # Form B: translate <SOURCE> into/to <LANG> (no colon)
    # Form C: translate ... into/to <LANG>: <SOURCE>
    m = re.search(
        r"\b(?:translate|translation)\b[^:\n]{0,40}\b(?:into|to)\s+\w+\s*[:\-–—]\s*(.+)",
        query, re.I | re.S,
    )
    if m:
        src = m.group(1).strip().rstrip(".")
        if 10 <= len(src) <= 5000:
            return src
    return None


async def _translate_blocks_for_multilingual(
    primary_md: str, targets: list[str],
) -> "tuple[list[dict], list[str]]":
    """Parse the markdown, translate each translatable block into EACH target
    language via NLLB. Returns (entries, labels) where:
      entries = [{"block": <md_block>, "translations": {"russian": "...", "uzbek": "..."}}, ...]
      labels  = ["Русский", "O'zbek", ...]   (display labels in same order as targets)

    Per-block translation preserves markdown structure (single-shot translation
    of the whole markdown collapses paragraphs).
    """
    blocks = parse_markdown_blocks(primary_md)
    entries: list[dict] = []
    for block in blocks:
        text = block_text_for_translation(block)
        translations: dict[str, str] = {}
        if text is not None:
            for lang in targets:
                try:
                    translations[lang] = (
                        await nllb_translate(text, target=lang, source="english")
                    ) or ""
                except Exception:
                    translations[lang] = ""
        entries.append({"block": block, "translations": translations})

    labels = [_LANG_LABELS.get(t.lower(), t.title()) for t in targets]
    return entries, labels


# ── Plan data ───────────────────────────────────────────────────────────────
@dataclass
class GenTask:
    fmt:        str
    title:      str
    brief:      str
    depends_on: list[int] = field(default_factory=list)
    is_complex: bool      = False

    def to_dict(self) -> dict:
        return {"fmt": self.fmt, "title": self.title, "brief": self.brief,
                "depends_on": self.depends_on, "is_complex": self.is_complex}


@dataclass
class GenResult:
    task:    GenTask
    content: str
    ok:      bool          = True
    error:   Optional[str] = None


# ── Planning prompt ─────────────────────────────────────────────────────────
_PLAN_SYSTEM = """You are a file generation planner. The user wants files created.
Decompose their request into a JSON array of file tasks.

Each task object MUST have exactly these keys:
  "fmt":        one of "pdf" | "docx" | "xlsx" | "csv" | "txt"
  "title":      short snake_case label, max 30 chars (used as filename hint)
  "brief":      a clear 1-2 sentence description of what THIS file should contain
  "depends_on": array of zero-indexed task indices this file needs as context
                  (use [] if independent)

Rules:
- Output ONLY a JSON array. Nothing else. No markdown fences, no commentary.
- Maximum 8 tasks. If the user asks for more, pick the most important 8.
- For "solve N problems each as PDF" → emit N PDF tasks, each independent.
- For "generate X then summarize" → emit X tasks + 1 summary task depending on them.
- For a single simple file → emit a 1-element array.
- Match formats user requested. If unspecified, infer reasonably (default txt).
"""

_PLAN_USER = """User request:
{query}

Output the JSON plan."""


_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*\]")


async def _plan(query: str, model: str) -> list[GenTask]:
    """Ask the LLM to plan tasks. Robust fallback to single-file on parse error."""
    msgs = [
        {"role": "system", "content": _PLAN_SYSTEM},
        {"role": "user",   "content": _PLAN_USER.format(query=query)},
    ]
    try:
        raw = await generate(
            msgs, model=model,
            options={"num_predict": 800, "temperature": 0.1, "num_ctx": 4096},
        )
    except Exception:
        return _fallback_plan(query)

    # Extract first JSON array from response
    m = _JSON_ARRAY_RE.search(raw)
    if not m:
        return _fallback_plan(query)
    try:
        items = json.loads(m.group(0))
    except Exception:
        return _fallback_plan(query)
    if not isinstance(items, list) or not items:
        return _fallback_plan(query)

    tasks: list[GenTask] = []
    for it in items[:8]:
        if not isinstance(it, dict):
            continue
        fmt = str(it.get("fmt", "txt")).lower()
        if fmt not in {"pdf", "docx", "xlsx", "csv", "txt"}:
            fmt = "txt"
        title = re.sub(r"[^\w-]", "_", str(it.get("title", "file"))[:30]) or "file"
        brief = str(it.get("brief", "Generate the requested content"))[:500]
        deps  = it.get("depends_on", [])
        if not isinstance(deps, list):
            deps = []
        deps = [int(d) for d in deps if isinstance(d, (int, float))]
        tasks.append(GenTask(
            fmt=fmt, title=title, brief=brief, depends_on=deps,
            is_complex=_looks_complex(brief),
        ))
    return tasks or _fallback_plan(query)


def _fallback_plan(query: str) -> list[GenTask]:
    """Single-task fallback when planning fails."""
    fmt = _detect_format(query) or "txt"
    return [GenTask(
        fmt=fmt, title="file", brief=query, depends_on=[],
        is_complex=_looks_complex(query),
    )]


# ── Content generation ─────────────────────────────────────────────────────
_CONTENT_SYSTEM = """You are a content writer. Write ONLY the file body in clean markdown.

Rules:
- Do NOT explain how to create files
- Do NOT suggest using echo / Notepad / VSCode / text editors
- Do NOT wrap the content in @@GENERATE markers — the system handles that
- Do NOT include "Here is the content:" or any preamble
- Just write the actual content that should be inside the file

Format-specific hints:
- xlsx/csv: use markdown table syntax with | columns | so rows map to cells
- docx/pdf: use # headings, paragraphs, bullets — make it polished
- txt: plain prose or simple lists, no markdown decoration needed
"""


def _build_content_prompt(task: GenTask, prior_results: list[GenResult],
                           ctx: SkillContext | None = None) -> str:
    """Build the user prompt for one task, injecting dependency + memory context."""
    parts = [f"Generate the {task.fmt} file body for the following request:\n",
             task.brief, ""]

    # Pull in chat memory so "that website" / "the file I generated" etc.
    # are grounded in concrete entities from earlier in the conversation.
    if ctx and ctx.chat_memory:
        mem_text = memory_summary(ctx.chat_memory, max_items=8)
        if mem_text:
            parts.append("---")
            parts.append(mem_text)
            parts.append("---")
            parts.append("Use the above context if the request references prior entities.\n")

    if task.depends_on:
        parts.append("---")
        parts.append("PRIOR FILES THIS BUILDS ON (use as context, do not repeat verbatim):")
        for idx in task.depends_on:
            if 0 <= idx < len(prior_results):
                r = prior_results[idx]
                parts.append(f"\n[file {idx + 1} — {r.task.fmt} — {r.task.title}]")
                parts.append(r.content[:2000])
        parts.append("---")

    parts.append("\nNow write the body of the new file. Just the content.")
    return "\n".join(parts)


async def _generate_one_stream(
    task:           GenTask,
    prior_results:  list[GenResult],
    ctx:            SkillContext,
    use_reasoning:  bool,
    task_index:     int,
):
    """Async generator that yields ('thinking_chunk'|'content_chunk'|'final', value) tuples.

    For complex+reasoning tasks: streams the thinking chain first, then content.
    For simple tasks: just streams the content tokens.
    Final tuple is ('final', sanitized_full_content) for the skill loop to wrap.
    """
    prompt = _build_content_prompt(task, prior_results, ctx)

    raw_content = ""

    if task.is_complex and use_reasoning:
        # ── Route through the streaming reasoner so user sees thinking live ──
        try:
            async for ev in run_reason_stream(
                query=prompt, context="", task_type="general",
                fast_model=ctx.model, strong_model=ctx.model,
            ):
                kind = ev.get("event")
                if kind == "plan":
                    yield ("plan", ev.get("content", ""))
                elif kind == "thinking_chunk":
                    yield ("thinking_chunk", ev.get("content", ""))
                elif kind == "thinking_done":
                    yield ("thinking_done", ev.get("content", ""))
                elif kind == "answer_chunk":
                    tok = ev.get("content", "")
                    raw_content += tok
                    yield ("content_chunk", tok)
                elif kind == "done":
                    pass  # we capture answer via answer_chunk already
            yield ("final", _sanitize(raw_content))
            return
        except Exception:
            # Fall through to direct generation if reasoning failed
            raw_content = ""

    # ── Fast path: direct streaming content generation ──
    msgs = [
        {"role": "system", "content": _CONTENT_SYSTEM},
        {"role": "user",   "content": prompt},
    ]
    async for tok in llm_stream(
        msgs, model=ctx.model,
        options={"num_predict": 1500, "temperature": 0.3, "num_ctx": 4096},
    ):
        raw_content += tok
        yield ("content_chunk", tok)

    yield ("final", _sanitize(raw_content))


_PREAMBLE_RE = re.compile(
    r"^\s*(certainly[!.,]?|sure[!.,]?|of\s+course[!.,]?|here\s+is|here['’]?s|"
    r"below\s+is|the\s+following\s+is|i['’]?ll\s+(?:write|create|generate))"
    r"[^\n]*?\n+",
    re.I,
)
_CLOSING_RE = re.compile(
    r"\n+\s*(this\s+(?:content|file|document)\s+(?:provides|covers|contains|is)"
    r"|hope\s+this\s+helps|let\s+me\s+know\s+if).*$",
    re.I | re.S,
)


def _sanitize(text: str) -> str:
    """Strip stray markers AND polite preambles/closings from the content."""
    text = re.sub(r"@@GENERATE:[\w-]+\s*\n?", "", text)
    text = re.sub(r"@@END\s*", "", text)
    text = text.strip()
    # Strip "Certainly! Below is..." preambles (small models can't suppress these)
    text = _PREAMBLE_RE.sub("", text, count=1).lstrip()
    # Strip "Hope this helps" type closings
    text = _CLOSING_RE.sub("", text)
    # Strip stray markdown fences if model wrapped whole output
    if text.startswith("```") and text.rstrip().endswith("```"):
        lines = text.split("\n")
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1])
    return text.strip()


# ── The skill ───────────────────────────────────────────────────────────────
class FileGenerationSkill(Skill):
    name        = "file_generation"
    label       = "File generation"
    description = "Generates downloadable PDF, DOCX, XLSX, CSV, or TXT files (multi-file aware, dependency-aware, reasoning-aware)"
    priority    = 10

    def matches(self, ctx: SkillContext) -> bool:
        return _detect_format(ctx.query) is not None

    async def execute(self, ctx: SkillContext) -> AsyncIterator[SkillEvent]:
        # Reasoning is used when EITHER:
        #   - the user enabled it in settings (best quality for everything), OR
        #   - the task complexity heuristic flags it (math problems, analysis, etc.)
        # When ctx.use_reasoning is True, EVERY task gets the reasoning path.
        use_reasoning_for_complex = True   # complex tasks always reason

        is_multi   = _looks_multi(ctx.query)
        is_complex = _looks_complex(ctx.query) or ctx.use_reasoning

        # ── Phase 0: literal-source shortcut ────────────────────────────────
        # If the user pasted the source text inline ("translate this: <text>
        # into X") AND a multilingual PDF was requested, skip the planner +
        # content generator entirely. Just use the literal text as the file
        # body and run NLLB on it. This prevents the LLM from inventing
        # "Translation Request" headers and pulling in unrelated chat memory.
        literal_source = extract_literal_source(ctx.query)
        ml_targets_top = _detect_bilingual_targets(ctx.query)
        if literal_source and ml_targets_top:
            yield SkillEvent(kind="status", content={
                "skill": self.name, "label": self.label,
                "stage": "literal_translate_shortcut",
                "targets": ml_targets_top, "chars": len(literal_source),
            })
            try:
                entries, target_labels = await _translate_blocks_for_multilingual(
                    literal_source, ml_targets_top,
                )
                payload = json.dumps({
                    "primary_label": "English",
                    "target_labels": target_labels,
                    "target_langs":  ml_targets_top,
                    "entries":       entries,
                }, ensure_ascii=False)
                yield SkillEvent(kind="status", content={
                    "skill": self.name, "stage": "task_complete",
                    "index": 0, "title": "translation", "fmt": "pdf-bilingual",
                    "targets": ml_targets_top,
                })
                block = f"@@GENERATE:pdf-bilingual\n{payload}\n@@END"
                yield SkillEvent(kind="answer_chunk", content=block + "\n\n")
                yield SkillEvent(kind="answer_chunk", content=
                    f"Your PDF is ready — click **Download** above to save it.")
                yield SkillEvent(kind="done", content={
                    "skill": self.name, "count": 1, "total": 1,
                    "files": [{"fmt": "pdf-bilingual", "title": "translation", "ok": True}],
                })
                return
            except Exception as e:
                # Fall through to the normal planning path on translation failure
                yield SkillEvent(kind="status", content={
                    "skill": self.name, "stage": "literal_shortcut_fallback",
                    "error": f"{type(e).__name__}: {e}",
                })

        # ── Phase 1: PLAN ───────────────────────────────────────────────────
        # Skip planning for trivially simple requests (single short query, no multi cue)
        if not is_multi and not is_complex and len(ctx.query) < 80:
            fmt  = _detect_format(ctx.query) or "txt"
            plan = [GenTask(fmt=fmt, title="file", brief=ctx.query, depends_on=[],
                             is_complex=ctx.use_reasoning)]
            yield SkillEvent(kind="status", content={
                "skill":  self.name, "label": self.label,
                "stage":  "fast_path", "tasks": [t.to_dict() for t in plan],
            })
        else:
            yield SkillEvent(kind="status", content={
                "skill": self.name, "label": self.label, "stage": "planning",
            })
            plan = await _plan(ctx.query, model=ctx.model)
            # If the user enabled reasoning, force all tasks to use the
            # thoughtful path — they explicitly want better quality.
            if ctx.use_reasoning:
                for t in plan:
                    t.is_complex = True
            yield SkillEvent(kind="status", content={
                "skill":  self.name, "label": self.label,
                "stage":  "plan_ready",
                "tasks":  [t.to_dict() for t in plan],
                "count":  len(plan),
                "complex": any(t.is_complex for t in plan),
            })

        if not plan:
            yield SkillEvent(kind="answer_chunk", content="I couldn't plan this request. Please try a simpler description.")
            yield SkillEvent(kind="done", content={"skill": self.name, "ok": False})
            return

        # ── Phase 2: EXECUTE each task in order ─────────────────────────────
        # Stream tokens live so the user watches generation happen, like
        # Anthropic's interface. Live tokens go via SKILL_EVENT (separate from
        # the @@GENERATE block) so they can be sanitized before the final file.
        results: list[GenResult] = []
        for i, task in enumerate(plan):
            yield SkillEvent(kind="status", content={
                "skill":  self.name, "label": self.label,
                "stage":  "generating",
                "index":  i, "total": len(plan),
                "fmt":    task.fmt, "title": task.title,
                "complex": task.is_complex,
            })

            final_content = ""
            try:
                async for kind, value in _generate_one_stream(
                    task, results, ctx, use_reasoning_for_complex, i,
                ):
                    if kind == "plan":
                        yield SkillEvent(kind="status", content={
                            "skill": self.name, "stage": "task_plan",
                            "index": i, "title": task.title, "plan": value,
                        })
                    elif kind == "thinking_chunk":
                        yield SkillEvent(kind="status", content={
                            "skill": self.name, "stage": "task_thinking_delta",
                            "index": i, "title": task.title, "delta": value,
                        })
                    elif kind == "thinking_done":
                        yield SkillEvent(kind="status", content={
                            "skill": self.name, "stage": "task_thinking_done",
                            "index": i, "title": task.title, "thinking": value,
                        })
                    elif kind == "content_chunk":
                        # Live content token — emitted as SKILL_EVENT (live preview),
                        # NOT inside the @@GENERATE block. This lets us sanitize
                        # the final content before wrapping it in markers.
                        yield SkillEvent(kind="status", content={
                            "skill": self.name, "stage": "task_content_delta",
                            "index": i, "title": task.title,
                            "fmt":   task.fmt, "delta": value,
                        })
                    elif kind == "final":
                        final_content = value

                # Multilingual path: if the original query asks for one or
                # more translated versions, run each markdown block through
                # NLLB for each target and emit a pdf-bilingual block.
                ml_targets = (
                    _detect_bilingual_targets(ctx.query)
                    if task.fmt == "pdf" else []
                )
                if ml_targets:
                    yield SkillEvent(kind="status", content={
                        "skill": self.name, "stage": "translating",
                        "index": i, "title": task.title,
                        "targets": ml_targets,
                    })
                    try:
                        entries, target_labels = await _translate_blocks_for_multilingual(
                            final_content, ml_targets
                        )
                        payload = json.dumps({
                            "primary_label": "English",
                            "target_labels": target_labels,
                            "target_langs":  ml_targets,
                            "entries":       entries,
                        }, ensure_ascii=False)
                        yield SkillEvent(kind="status", content={
                            "skill": self.name, "stage": "task_complete",
                            "index": i, "title": task.title, "fmt": "pdf-bilingual",
                            "targets": ml_targets,
                        })
                        block = f"@@GENERATE:pdf-bilingual\n{payload}\n@@END"
                        yield SkillEvent(kind="answer_chunk", content=block + "\n\n")
                        results.append(GenResult(task=task, content=final_content, ok=True))
                        continue
                    except Exception as e:
                        # Fall through to plain PDF on translation failure
                        yield SkillEvent(kind="status", content={
                            "skill": self.name, "stage": "multilingual_fallback",
                            "error": f"{type(e).__name__}: {e}",
                        })

                # NOW emit the clean, sanitized @@GENERATE block.
                # The frontend will see this and replace the live preview with
                # the final file card.
                yield SkillEvent(kind="status", content={
                    "skill": self.name, "stage": "task_complete",
                    "index": i, "title": task.title, "fmt": task.fmt,
                })
                block = f"@@GENERATE:{task.fmt}\n{final_content}\n@@END"
                yield SkillEvent(kind="answer_chunk", content=block + "\n\n")
                results.append(GenResult(task=task, content=final_content, ok=True))
            except Exception as e:
                yield SkillEvent(kind="answer_chunk",
                                  content=f"\n*(Task {i + 1} failed: {e})*\n\n")
                results.append(GenResult(task=task, content="", ok=False, error=str(e)))

        # ── Phase 3: SUMMARY MESSAGE ────────────────────────────────────────
        ok_count = sum(1 for r in results if r.ok)
        if len(plan) == 1:
            tail = f"Your {plan[0].fmt.upper()} file is ready — click **Download** above to save it."
        else:
            fmts = ", ".join(sorted({r.task.fmt.upper() for r in results if r.ok}))
            tail = f"Generated **{ok_count} of {len(plan)}** files ({fmts}). Click **Download** on each card to save."
        yield SkillEvent(kind="answer_chunk", content=tail)

        yield SkillEvent(kind="done", content={
            "skill":  self.name,
            "count":  ok_count,
            "total":  len(plan),
            "files":  [{"fmt": r.task.fmt, "title": r.task.title, "ok": r.ok} for r in results],
        })
