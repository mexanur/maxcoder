"""
Web Navigator — Level 2 web capabilities.

Builds on core/web_search.py with:
  • PDF / binary URL detection and parsing
  • Multi-page crawl with depth + budget caps
  • Same-domain link following for docs/repos
  • Source ranking by domain authority + quality
  • GitHub repo file fetching via raw.githubusercontent
"""
from __future__ import annotations
import asyncio, io, re, urllib.parse
import httpx

from core.web_search import fetch_page_with_links, _clean_html, HEADERS, MAX_PAGE_CHARS


# ── Domain authority heuristic for source ranking ──────────────────────────
# Higher score = more trusted. Lower bound 0.
_HIGH_AUTHORITY = {
    # Official docs
    "docs.python.org": 100, "fastapi.tiangolo.com": 95, "react.dev": 95,
    "nextjs.org": 95, "rust-lang.org": 95, "doc.rust-lang.org": 95,
    "developer.mozilla.org": 100, "mdn": 100, "go.dev": 95,
    "kubernetes.io": 90, "docker.com": 85,
    # Tech publishers
    "github.com": 80, "stackoverflow.com": 75, "wikipedia.org": 85,
    "anthropic.com": 90, "openai.com": 85,
    # News / vendors
    "aws.amazon.com": 80, "cloud.google.com": 80, "azure.microsoft.com": 80,
}
_MED_AUTHORITY = ("medium.com", "dev.to", "hashnode.dev", "freecodecamp.org",
                  "geeksforgeeks.org", "tutorialspoint.com", "w3schools.com")
_LOW_AUTHORITY = ("blogspot.com", "wordpress.com",
                  ".info", "answers.com", "quora.com")


def score_source(url: str, content: str = "") -> int:
    """Return 0-100 quality score for a source URL+content."""
    if not url:
        return 0
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except Exception:
        return 30
    host = host.lower().lstrip("www.")

    # Domain authority
    base = 50  # neutral default
    for known, score in _HIGH_AUTHORITY.items():
        if known in host:
            base = score
            break
    else:
        if any(m in host for m in _MED_AUTHORITY):
            base = 55
        elif any(l in host for l in _LOW_AUTHORITY):
            base = 30

    # Content quality bonuses
    if content:
        if len(content) > 1500:           base += 5      # substantial content
        if "```" in content or "    def " in content: base += 5  # has code
        if re.search(r'\b202[3-9]\b', content):       base += 3  # recent year mention
        if content.count("\n") > 20:      base += 2      # structured

    return max(0, min(100, base))


# ── PDF / binary detection and parsing ─────────────────────────────────────
async def fetch_pdf_url(url: str) -> str:
    """Download a PDF URL and extract its text via pypdf. Returns plain text."""
    try:
        from pypdf import PdfReader
    except Exception:
        return ""
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as c:
            r = await c.get(url)
            if r.status_code != 200:
                return ""
            ctype = r.headers.get("content-type", "")
            if "pdf" not in ctype.lower() and not url.lower().endswith(".pdf"):
                return ""
            buf = io.BytesIO(r.content)
            reader = PdfReader(buf)
            pages = []
            for i, page in enumerate(reader.pages):
                if i >= 25:    # cap at 25 pages
                    break
                try:
                    pages.append(page.extract_text() or "")
                except Exception:
                    continue
            text = "\n\n".join(pages).strip()
            return text[:20000]   # generous cap for PDFs
    except Exception:
        return ""


async def fetch_smart(url: str) -> tuple[str, str, list[dict]]:
    """Fetch a URL and auto-detect PDF vs HTML.

    Returns: (kind, content, links)
      kind:  'html' | 'pdf' | 'empty'
      content: extracted text
      links: links found on the page (HTML only, empty for PDF)
    """
    if not url or not url.startswith("http"):
        return "empty", "", []

    # Quick content-type probe via HEAD (lots of servers don't allow HEAD; that's fine)
    looks_like_pdf = url.lower().endswith(".pdf")

    if looks_like_pdf:
        text = await fetch_pdf_url(url)
        if text:
            return "pdf", text, []

    # Try HTML path
    text, links = await fetch_page_with_links(url)
    if text:
        return "html", text, links

    # Maybe the URL didn't say .pdf but is one
    text = await fetch_pdf_url(url)
    if text:
        return "pdf", text, []

    return "empty", "", []


# ── Same-domain link following ──────────────────────────────────────────────
def same_domain(url_a: str, url_b: str) -> bool:
    try:
        a = urllib.parse.urlparse(url_a).hostname
        b = urllib.parse.urlparse(url_b).hostname
        if not a or not b:
            return False
        return a.lstrip("www.").lower() == b.lstrip("www.").lower()
    except Exception:
        return False


def filter_relevant_links(
    links: list[dict],
    base_url: str,
    topic_keywords: list[str],
    max_links: int = 10,
) -> list[dict]:
    """Pick the most promising links for follow-up crawling.

    Rules:
      - Must be same domain as base_url
      - URL or text must contain one of the topic keywords
      - Skip media files (.jpg, .png, .mp4, etc.)
      - Dedupe + cap
    """
    SKIP_EXT = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".mp4",
                ".mp3", ".zip", ".tar", ".gz", ".css", ".js")
    out, seen = [], set()
    kws = [k.lower() for k in topic_keywords]
    for l in links:
        url = l.get("url", "")
        if not url or url in seen:
            continue
        if not same_domain(url, base_url):
            continue
        if any(url.lower().endswith(ext) for ext in SKIP_EXT):
            continue
        haystack = (url + " " + (l.get("text") or "")).lower()
        if not kws or any(k in haystack for k in kws):
            out.append(l)
            seen.add(url)
            if len(out) >= max_links:
                break
    return out


async def crawl(
    start_url:    str,
    topic_keywords: list[str],
    max_pages:    int = 4,
    on_progress:  callable | None = None,
) -> list[dict]:
    """Fetch the start URL, then follow up to N relevant same-domain links.

    Returns: list of {url, kind, content, links_found, score}
    """
    results: list[dict] = []
    visited: set[str] = {start_url}

    # Fetch the start page
    kind, content, links = await fetch_smart(start_url)
    if on_progress:
        on_progress({"stage": "fetched_root", "url": start_url, "kind": kind, "links": len(links)})
    if not content:
        return results
    results.append({
        "url": start_url, "kind": kind, "content": content,
        "links_found": links, "score": score_source(start_url, content),
    })

    if kind != "html":
        return results

    # Pick the top sub-links by keyword match
    sub_links = filter_relevant_links(links, start_url, topic_keywords, max_links=max_pages * 2)
    sub_urls = [l["url"] for l in sub_links if l["url"] not in visited][: max_pages - 1]

    if on_progress:
        on_progress({"stage": "following", "count": len(sub_urls)})

    # Fetch them in parallel
    sub_results = await asyncio.gather(*[fetch_smart(u) for u in sub_urls])
    for u, (k, txt, lnks) in zip(sub_urls, sub_results):
        if not txt:
            continue
        visited.add(u)
        results.append({
            "url": u, "kind": k, "content": txt,
            "links_found": lnks, "score": score_source(u, txt),
        })

    return results


# ── GitHub repo helpers ─────────────────────────────────────────────────────
_GH_REPO_RE = re.compile(
    r'https?://github\.com/([\w\.\-]+)/([\w\.\-]+)(?:/(?:tree|blob)/([\w\.\-]+))?',
    re.I,
)


def parse_github_url(url: str) -> dict | None:
    """Parse a GitHub URL into {owner, repo, branch} or return None."""
    m = _GH_REPO_RE.search(url)
    if not m:
        return None
    owner, repo, branch = m.group(1), m.group(2), m.group(3) or "main"
    # Strip .git suffix if present
    repo = repo.replace(".git", "")
    return {"owner": owner, "repo": repo, "branch": branch}


async def fetch_github_file(owner: str, repo: str, path: str, branch: str = "main") -> str:
    """Fetch a single file from a GitHub repo via raw.githubusercontent."""
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            r = await c.get(url)
            if r.status_code == 200:
                return r.text[:20000]
    except Exception:
        pass
    # Try other common default branches
    for alt_branch in ("master", "develop", "dev"):
        if alt_branch == branch:
            continue
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
                r = await c.get(f"https://raw.githubusercontent.com/{owner}/{repo}/{alt_branch}/{path}")
                if r.status_code == 200:
                    return r.text[:20000]
        except Exception:
            continue
    return ""


# Common file paths to probe when exploring an unknown repo
REPO_KEY_FILES = [
    "README.md", "README.rst", "README.txt", "readme.md",
    "package.json", "Cargo.toml", "pyproject.toml", "setup.py", "go.mod",
    "src/main.py", "src/index.js", "src/main.rs", "main.go",
    "src/lib.rs", "lib/index.js",
    "docs/README.md", "docs/index.md",
]


async def explore_github_repo(
    owner:        str,
    repo:         str,
    branch:       str = "main",
    on_progress:  callable | None = None,
) -> list[dict]:
    """Probe a GitHub repo for its README + a couple of key source files.

    Returns: list of {path, content} — only files that existed.
    """
    if on_progress:
        on_progress({"stage": "probing_repo", "owner": owner, "repo": repo, "branch": branch})

    results = await asyncio.gather(*[
        fetch_github_file(owner, repo, p, branch) for p in REPO_KEY_FILES
    ])
    found = []
    for path, content in zip(REPO_KEY_FILES, results):
        if content:
            found.append({"path": path, "content": content, "score": 80})
        if len(found) >= 4:    # cap so we don't overwhelm the model
            break

    if on_progress:
        on_progress({"stage": "repo_probed", "files_found": len(found)})

    return found
