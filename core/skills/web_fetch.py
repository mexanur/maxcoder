"""
WebFetchSkill — Level 1 web usage.

Triggers when the user includes a URL in their message OR asks to read/summarize
a specific page. Fetches the page (Jina reader → fallback to direct HTTP),
extracts the structure, and answers the user's question about it.

Examples:
  "summarize https://example.com/article"
  "read this page and extract the pricing: https://..."
  "what does this site say about X? https://..."
"""
from __future__ import annotations
import re
from typing import AsyncIterator

from core.skills.base import Skill, SkillContext, SkillEvent
from core.generator    import stream as llm_stream
from core.web_search   import fetch_page_with_links, filter_links_by_topic, PAGE_KEYWORDS
from core.web_navigator import fetch_smart
from core.skills._synthesize import synthesize

# Strong URL match — definitely a URL.
_HTTP_URL_RE = re.compile(
    r"https?://[^\s<>\"\'\)\]]+|www\.[a-zA-Z0-9][a-zA-Z0-9\-]*\.[a-zA-Z]{2,}[^\s<>\"\'\)\]]*",
    re.I,
)

# Bare domain — looks like "sher-expressllc.com" or "example.org/path".
# Must have a real-world TLD to avoid matching things like "next.js" or "v1.0".
# Common TLDs allowlist keeps this precise.
_BARE_DOMAIN_RE = re.compile(
    r"(?<![\w./])"                                # not preceded by word char or slash
    r"([a-zA-Z0-9][a-zA-Z0-9\-]{1,62}"            # subdomain/domain label
    r"(?:\.[a-zA-Z0-9][a-zA-Z0-9\-]{1,62})*"      # optional more labels (subdomains)
    r"\.(?:com|org|net|io|ai|dev|app|co|uk|us|ca|de|fr|jp|au|in|"
    r"info|biz|me|tv|fm|gg|xyz|cloud|tech|store|"
    r"edu|gov|mil|int))"                          # TLDs only — excludes "js", "py"
    r"(?:/[^\s<>\"\'\)\]]*)?",                    # optional path
    re.I,
)


def _extract_explicit_urls(text: str) -> list[str]:
    """Find URLs (explicit or bare-domain) in the text. Returns normalized https URLs."""
    urls = []
    # First try explicit (https://... or www....)
    for m in _HTTP_URL_RE.findall(text):
        urls.append(m if m.startswith("http") else f"https://{m}")
    # Then bare domains (only if no explicit URL already found in same query)
    if not urls:
        for m in _BARE_DOMAIN_RE.findall(text):
            # The findall returns groups — m[0] is the captured domain
            domain = m if isinstance(m, str) else m[0]
            urls.append(f"https://{domain}")
    return urls


_READ_VERBS_RE = re.compile(
    r"\b(read|summari[sz]e|extract|fetch|grab|tell\s+me\s+about|"
    r"what\s+does|what['']?s\s+on|content\s+of|article\s+at|"
    r"what\s+is\s+(?:the|this)|explain\s+this|describe\s+this|info\s+(?:from|on)|"
    r"go\s+to|visit|check\s+out|check\s+this|look\s+at|see\s+what|"
    r"what['']?s\s+(?:on|in|at|this)|"
    r"find\s+(?:the\s+|their\s+|me\s+)?(?:links?|pages?|info|terms?|privacy|"
                       r"contact|about|pricing|careers?|jobs?|blog|docs|"
                       r"phone|email|address|policies?)|"
    r"give\s+me\s+(?:the\s+|their\s+)?(?:links?|urls?|pages?))\b",
    re.I,
)

# When reference resolution adds a URL via "[Context — earlier in this chat: on the website ...]"
# we should ALWAYS treat it as a fetch request, regardless of verb in the original text.
_RESOLVED_CONTEXT_RE = re.compile(r'\[Context\s+—\s+earlier\s+in\s+this\s+chat:.*?https?://', re.I | re.S)


_FETCH_SYSTEM = """You are reading a web page for the user. Answer their question using ONLY the page content and the [LINKS ON PAGE] list provided.

CRITICAL: Do NOT analyze the page as a web-development artifact unless explicitly asked.
- If the user asks "what is this about" / "what does this site do" / "summarize this":
  → Describe what the BUSINESS / TOPIC / CONTENT is — like a human visitor would
  → NOT a security audit, performance analysis, SEO review, or UX review

- If the user asks for SPECIFIC LINKS (privacy policy, terms of service, contact page,
  pricing page, docs, blog, etc.) or asks to "find" certain pages:
  → DO NOT make up URLs or invent paths like "/terms-of-service"
  → ONLY return URLs from the [LINKS ON PAGE] section below
  → Use this format:
       **[Page Type]:** [Link Text](URL)
  → If a requested link isn't in the list, say "No [page type] link found on this page."
     (Do NOT invent one.)

- If the user asks for specific data (prices, dates, names, addresses, phone, hours):
  → Extract precisely from the page content (NOT the link list).
  → If not present, say "Not visible on this page."

Default response format for "what is this site about":

**[Company/Site name]** — one-sentence description of what they do.

- Bullet of key fact 1 from the page
- Bullet of key fact 2
- (3-6 bullets, only facts found on the page)

Notable links if relevant (only from the [LINKS ON PAGE] list).

Rules:
- Use ONLY what's in the page content + link list. NEVER invent URLs, SSL details,
  performance metrics, contact info, or any data not present.
- If the page is empty / paywalled / unreadable, say so honestly.
- Be concise. No padding, no recommendations."""

_FETCH_USER = """User's request:
{query}

URL: {url}

Page content (text):
---
{content}
---

[LINKS ON PAGE] (use these for URL references — do NOT invent paths):
{links}

Now answer the user."""


def _format_links_for_prompt(links: list[dict], topics_requested: list[str]) -> str:
    """Format the discovered links as a numbered list. Prioritize topic matches."""
    if not links:
        return "(no links found on this page)"
    # Topic-matched links first
    matched = filter_links_by_topic(links, topics_requested) if topics_requested else []
    matched_urls = {l["url"] for l in matched}
    other = [l for l in links if l["url"] not in matched_urls]
    # Show topic matches first (in full), then up to 25 others
    out_lines = []
    if matched:
        out_lines.append("PAGES MATCHING THE USER'S REQUEST:")
        for l in matched:
            out_lines.append(f"  - {l['text'] or '(no label)'}: {l['url']}")
        out_lines.append("")
    out_lines.append("OTHER LINKS ON THE PAGE:")
    for l in other[:25]:
        out_lines.append(f"  - {l['text'] or '(no label)'}: {l['url']}")
    if len(other) > 25:
        out_lines.append(f"  ... and {len(other) - 25} more")
    return "\n".join(out_lines)


def _detect_link_topics(query: str) -> list[str]:
    """Find which page topics the user is asking for (terms, privacy, contact, etc.)."""
    topics = []
    ql = query.lower()
    if any(k in ql for k in ["term", "tos", "condition", "legal", "eula"]):
        topics.append("terms")
    if "privacy" in ql or "data protection" in ql:
        topics.append("privacy")
    if "contact" in ql or "phone" in ql or "email" in ql or "address" in ql:
        topics.append("contact")
    if "about" in ql or "who" in ql:
        topics.append("about")
    if "pricing" in ql or "price" in ql or "cost" in ql or "plan" in ql:
        topics.append("pricing")
    if "career" in ql or "job" in ql or "hiring" in ql:
        topics.append("careers")
    if "blog" in ql or "news" in ql or "article" in ql:
        topics.append("blog")
    if "doc" in ql or "documentation" in ql or "guide" in ql:
        topics.append("docs")
    if "api" in ql:
        topics.append("api")
    if "login" in ql or "signin" in ql or "sign in" in ql:
        topics.append("login")
    return topics


class WebFetchSkill(Skill):
    name        = "web_fetch"
    label       = "Web page fetch"
    description = "Reads a specific URL deeply, summarizes or extracts data the user asked for"
    priority    = 12   # before web_search so URLs go here first

    def matches(self, ctx: SkillContext) -> bool:
        urls = _extract_explicit_urls(ctx.query)
        if not urls:
            return False
        # ALWAYS trigger if URL came in via reference resolution (continuation case)
        if _RESOLVED_CONTEXT_RE.search(ctx.query):
            return True
        # Trigger if explicit verb OR URL dominates the message (drive-by paste)
        has_verb = bool(_READ_VERBS_RE.search(ctx.query))
        url_chars = sum(len(u) for u in urls)
        if has_verb or url_chars > 0.4 * len(ctx.query):
            return True
        return False

    async def execute(self, ctx: SkillContext) -> AsyncIterator[SkillEvent]:
        urls = _extract_explicit_urls(ctx.query)
        if not urls:
            return
        url = urls[0]  # Use the first URL (multi-URL handled by WebCompareSkill or summary chain)

        yield SkillEvent(kind="status", content={
            "skill": self.name, "label": self.label,
            "stage": "fetching", "url": url,
        })

        # Smart fetch: auto-detects PDF vs HTML
        kind, content, links = await fetch_smart(url)
        if not content:
            yield SkillEvent(kind="answer_chunk",
                              content=f"I couldn't fetch readable content from {url}. "
                                       "It may be paywalled, JavaScript-heavy, or unreachable.")
            yield SkillEvent(kind="done", content={"skill": self.name, "ok": False, "url": url})
            return

        # Detect what kind of page-links the user is asking for (terms, privacy, etc.)
        topics_requested = _detect_link_topics(ctx.query)
        # PDFs don't have HTML links, so skip the link block for them
        links_block = _format_links_for_prompt(links, topics_requested) if links else "(N/A — this is a PDF)"

        yield SkillEvent(kind="status", content={
            "skill": self.name, "stage": "synthesizing", "url": url,
            "kind":  kind, "chars": len(content),
            "links_found": len(links),
            "topics": topics_requested,
        })

        # Build the system prompt + source block based on PDF vs HTML
        if kind == "pdf":
            system_msg = (
                "You are reading a PDF document the user provided.\n"
                "Answer their question using ONLY the PDF text below.\n"
                "If they asked for a summary, give: title (if present), 3-7 key points,\n"
                "and any specific data they asked for.\n"
                "Use ONLY content present in the PDF. Don't invent."
            )
            sources_block = f"PDF source: {url}\n\nPDF text content:\n{content[:8000]}"
        else:
            system_msg = _FETCH_SYSTEM
            sources_block = (
                f"URL: {url}\n\nPage content:\n{content[:5000]}\n\n"
                f"{links_block}"
            )

        async for ev in synthesize(
            query         = ctx.query,
            sources       = sources_block,
            system_prompt = system_msg,
            model         = ctx.model,
            use_reasoning = ctx.use_reasoning,
            task_label    = f"reading {url.split('/')[2] if '://' in url else url}",
            num_predict   = 900,
        ):
            yield ev

        # Emit the URL as a citation footer so it's clickable
        yield SkillEvent(kind="citations", content={
            "sources": [{"n": 1, "title": url, "url": url, "snippet": content[:160]}],
        })

        yield SkillEvent(kind="done", content={"skill": self.name, "ok": True, "url": url})
