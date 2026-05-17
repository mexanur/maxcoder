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


# DDG search results cached in-memory for 2 minutes to handle rapid-fire follow-ups
_DDG_CACHE_TTL = 120
import time as _time
_DDG_CACHE: dict[str, tuple[float, list[dict]]] = {}


def _ddg_search(query: str, max_results: int = 5) -> list[dict]:
    """Search DuckDuckGo HTML endpoint with caching + retry. Returns list of {title, url, snippet}."""
    # Check cache
    cache_key = f"{query}::{max_results}"
    cached = _DDG_CACHE.get(cache_key)
    if cached and _time.time() - cached[0] < _DDG_CACHE_TTL:
        return cached[1]

    # Try up to 2 times with a short backoff (DDG sometimes returns 202/empty on rapid requests)
    text = ""
    last_err: str = ""
    for attempt in range(2):
        try:
            r = httpx.post(
                DDG_URL,
                data={"q": query, "b": "", "kl": "us-en"},
                headers=HEADERS,
                timeout=12,
                follow_redirects=True,
            )
            text = r.text
            if r.status_code == 200 and len(text) > 200 and "result__a" in text:
                break
            last_err = f"HTTP {r.status_code} ({len(text)} bytes)"
        except Exception as e:
            last_err = str(e)
        if attempt == 0:
            _time.sleep(0.8)   # brief backoff before retry
        text = ""

    if not text:
        return [{"title": "Error", "url": "", "snippet": last_err or "Search failed"}]

    results: list[dict] = []
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

    if results:
        # Cap cache + store
        if len(_DDG_CACHE) > 100:
            oldest = min(_DDG_CACHE.items(), key=lambda x: x[1][0])
            _DDG_CACHE.pop(oldest[0], None)
        _DDG_CACHE[cache_key] = (_time.time(), results)
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
    """
    Fetch a URL and return cleaned text.
    Tries Jina.ai reader first (handles JS-rendered pages),
    falls back to direct httpx fetch.
    """
    if not url or not url.startswith("http"):
        return ""
    try:
        jina_url = f"https://r.jina.ai/{url}"
        async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as c:
            r = await c.get(jina_url)
            if r.status_code == 200 and r.text.strip():
                return r.text.strip()[:MAX_PAGE_CHARS]
    except Exception:
        pass
    # Fallback: direct fetch + strip HTML
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=10, follow_redirects=True) as c:
            r = await c.get(url)
            if "text/html" not in r.headers.get("content-type", ""):
                return ""
            return _clean_html(r.text)[:MAX_PAGE_CHARS]
    except Exception:
        return ""


# ── Link extraction from fetched pages ─────────────────────────────────────
_MD_LINK_RE     = re.compile(r'\[([^\]]{1,120}?)\]\((https?://[^\s\)]+)\)')
_MD_IMAGE_RE    = re.compile(r'!\[([^\]]{0,120}?)\]\((https?://[^\s\)]+)\)')
_IMG_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp', '.avif')


async def fetch_page_with_links(url: str) -> tuple[str, list[dict]]:
    """Fetch a page and ALSO extract a list of links found on it.

    Returns: (page_text, [{ text, url, kind }])
      kind: 'link' (default) or 'image' for image URLs
    """
    text = await fetch_page(url)
    if not text:
        return "", []

    seen: set[str] = set()
    links: list[dict] = []

    # Markdown-style IMAGES first (they have a leading ! that's significant)
    for alt, img_url in _MD_IMAGE_RE.findall(text):
        if img_url not in seen:
            seen.add(img_url)
            links.append({"text": alt.strip()[:120], "url": img_url, "kind": "image"})

    # Markdown-style LINKS (Jina reader emits these)
    for label, link_url in _MD_LINK_RE.findall(text):
        if link_url in seen:
            continue
        seen.add(link_url)
        kind = "image" if any(link_url.lower().endswith(ext) for ext in _IMG_EXTENSIONS) else "link"
        links.append({"text": label.strip()[:120], "url": link_url, "kind": kind})

    # Also catch any bare http URLs not already captured
    for m in re.finditer(r'(?<![\(\[])https?://[^\s<>")\]]+', text):
        u = m.group(0).rstrip('.,;:!?)')
        if u in seen or len(seen) >= 100:
            continue
        seen.add(u)
        kind = "image" if any(u.lower().endswith(ext) for ext in _IMG_EXTENSIONS) else "link"
        links.append({"text": "", "url": u, "kind": kind})

    return text, links


def filter_images(links: list[dict]) -> list[dict]:
    """Return only the image entries from a links list."""
    return [l for l in links if l.get("kind") == "image"]


# Common page-type keywords for filtering link extraction results
PAGE_KEYWORDS = {
    "privacy":   ["privacy", "data-protection"],
    "terms":     ["terms", "tos", "conditions", "legal", "eula"],
    "contact":   ["contact", "support", "help", "get-in-touch"],
    "about":     ["about", "who-we-are", "company"],
    "pricing":   ["pricing", "plans", "price"],
    "careers":   ["careers", "jobs", "hiring"],
    "blog":      ["blog", "news", "articles"],
    "docs":      ["docs", "documentation", "guide", "manual"],
    "api":       ["api", "developer"],
    "login":     ["login", "signin", "sign-in", "account"],
}


def filter_links_by_topic(links: list[dict], topics: list[str]) -> list[dict]:
    """Return links whose URL or text matches any of the given topic keywords."""
    out, seen = [], set()
    for topic in topics:
        kws = PAGE_KEYWORDS.get(topic.lower(), [topic.lower()])
        for link in links:
            haystack = (link.get("url", "") + " " + link.get("text", "")).lower()
            if any(k in haystack for k in kws) and link["url"] not in seen:
                seen.add(link["url"])
                out.append(link)
    return out


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


def extract_urls(text: str) -> list[str]:
    """
    Return all URLs found in the text.
    Handles both full URLs (https://example.com) and
    bare domains (example.com, www.example.com).
    """
    # Full URLs first
    full = re.findall(r'https?://[^\s<>"\'\)\]]+', text)
    if full:
        return full
    # Bare domains — e.g. sher-expressllc.com or www.example.co.uk/path
    bare = re.findall(
        r'(?<!\w)((?:www\.)?[a-zA-Z0-9][a-zA-Z0-9\-]*\.[a-zA-Z]{2,}(?:/[^\s<>"\'\)\]]*)?)',
        text
    )
    # Prepend https:// and exclude common false positives
    excluded = {"e.g", "i.e", "etc"}
    return [f"https://{u}" for u in bare if u.lower() not in excluded]


async def fetch_url_context(urls: list[str]) -> str:
    """
    Directly fetch user-provided URLs and return formatted context.
    Used when the user pastes a URL instead of a search query.
    """
    sections = ["FETCHED WEB PAGES (user-provided URLs):\n"]
    for url in urls[:MAX_PAGES]:
        page_text = await fetch_page(url)
        if page_text:
            sections.append(f"### {url}\nContent:\n{page_text}\n")
    return "\n".join(sections) if len(sections) > 1 else ""


def should_search(query: str) -> bool:
    """
    Heuristic: decide if this query likely needs a web search.
    Triggers on: version questions, "latest", "how to install",
    library names with dots, error codes, URLs, etc.
    """
    triggers = [
        r"https?://",
        r"\blatest\b", r"\bcurrent\b", r"\b202[4-9]\b",
        r"\binstall\b", r"\bdocs?\b", r"\bdocumentation\b",
        r"\bchangelog\b", r"\brelease\b", r"\bversion\b",
        r"\berror\b", r"\bexception\b", r"\bhow to\b",
        r"\bwhat is\b", r"\bexample\b", r"\.js\b", r"\.py\b",
        r"npm\b", r"pip\b", r"cargo\b", r"\bapi\b",
    ]
    q = query.lower()
    return any(re.search(p, q) for p in triggers)
