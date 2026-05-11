"""
Web Search Tool for MaxCoder.
Uses DuckDuckGo (no API key needed) to search the web,
then fetches and cleans the top results for the model to use.

Flow:
  search(query) → top N result URLs
  fetch_page(url) → clean text
  web_context(query) → formatted string injected into prompt
"""
from __future__ import annotations
import re, httpx, urllib.parse

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}
DDG_URL  = "https://html.duckduckgo.com/html/"
MAX_PAGE_CHARS = 3000   # chars to keep per page
MAX_PAGES      = 3      # how many pages to fetch


def _ddg_search(query: str, max_results: int = 5) -> list[dict]:
    """Search DuckDuckGo HTML endpoint. Returns list of {title, url, snippet}."""
    try:
        r = httpx.post(
            DDG_URL,
            data={"q": query, "b": "", "kl": "us-en"},
            headers=HEADERS,
            timeout=10,
            follow_redirects=True,
        )
        text = r.text
    except Exception as e:
        return [{"title": "Error", "url": "", "snippet": str(e)}]

    results = []
    # Parse result blocks
    blocks = re.findall(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
        text, re.DOTALL
    )
    for url, title, snippet in blocks[:max_results]:
        # DuckDuckGo wraps URLs — extract real URL
        real_url = url
        if "uddg=" in url:
            m = re.search(r"uddg=([^&]+)", url)
            if m:
                real_url = urllib.parse.unquote(m.group(1))
        results.append({
            "title":   re.sub(r"<[^>]+>", "", title).strip(),
            "url":     real_url,
            "snippet": re.sub(r"<[^>]+>", "", snippet).strip(),
        })
    return results


def _clean_html(html: str) -> str:
    """Strip HTML tags, scripts, styles. Return plain text."""
    # Remove scripts and styles
    html = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", "", html,
                  flags=re.DOTALL | re.IGNORECASE)
    # Remove tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Collapse whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def fetch_page(url: str) -> str:
    """Fetch a URL and return cleaned text (first MAX_PAGE_CHARS chars)."""
    if not url or not url.startswith("http"):
        return ""
    try:
        async with httpx.AsyncClient(
            headers=HEADERS, timeout=10, follow_redirects=True
        ) as c:
            r = await c.get(url)
            if "text/html" not in r.headers.get("content-type", ""):
                return ""
            return _clean_html(r.text)[:MAX_PAGE_CHARS]
    except Exception:
        return ""


async def web_context(query: str) -> str:
    """
    Full pipeline: search → fetch top pages → return formatted context string.
    This is what gets injected into the prompt.
    """
    results = _ddg_search(query, max_results=MAX_PAGES + 2)
    if not results:
        return ""

    sections = [f"WEB SEARCH RESULTS for: {query}\n"]

    fetched = 0
    for res in results:
        if fetched >= MAX_PAGES:
            break
        url     = res["url"]
        title   = res["title"]
        snippet = res["snippet"]

        # Always include snippet
        section = f"### {title}\nURL: {url}\nSummary: {snippet}\n"

        # Try to fetch full page for richer context
        page_text = await fetch_page(url)
        if page_text:
            section += f"Content:\n{page_text}\n"
            fetched += 1

        sections.append(section)

    return "\n".join(sections)


def should_search(query: str) -> bool:
    """
    Heuristic: decide if this query likely needs a web search.
    Triggers on: version questions, "latest", "how to install",
    library names with dots, error codes, etc.
    """
    triggers = [
        r"\blatest\b", r"\bcurrent\b", r"\b202[4-9]\b",
        r"\binstall\b", r"\bdocs?\b", r"\bdocumentation\b",
        r"\bchangelog\b", r"\brelease\b", r"\bversion\b",
        r"\berror\b", r"\bexception\b", r"\bhow to\b",
        r"\bwhat is\b", r"\bexample\b", r"\.js\b", r"\.py\b",
        r"npm\b", r"pip\b", r"cargo\b", r"\bapi\b",
    ]
    q = query.lower()
    return any(re.search(p, q) for p in triggers)
