"""
MaxCoder Dataset Ingester — populate the RAG indexes with expert knowledge.

Sources:
  language_docs    — Python, FastAPI, Pydantic, React, Next.js, TS, Node, Rust, Go
  snippets         — curated Q/A patterns + awesome-list idioms
  codebase         — this MaxCoder repo itself
  error_solutions  — common error→fix patterns

Usage:
  python scripts/ingest_datasets.py                # all sources, standard budget
  python scripts/ingest_datasets.py --source python_docs
  python scripts/ingest_datasets.py --rebuild      # wipe existing indexes first
  python scripts/ingest_datasets.py --light        # quick first pass
"""
from __future__ import annotations
import argparse, hashlib, json, os, pathlib, re, sys, time
from typing import Iterator

# Make project root importable
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.rag_retriever import index_texts, INDEX_DIR  # noqa: E402

CACHE_DIR = ROOT / "scripts" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── HTTP fetch with caching ──────────────────────────────────────────────────
def fetch(url: str, ttl_days: int = 14) -> str | None:
    """Fetch URL with on-disk cache. Returns text or None on failure."""
    h = hashlib.md5(url.encode()).hexdigest()
    cache_file = CACHE_DIR / f"{h}.txt"
    if cache_file.exists():
        age_days = (time.time() - cache_file.stat().st_mtime) / 86400
        if age_days < ttl_days:
            try:
                return cache_file.read_text(encoding="utf-8")
            except Exception:
                pass
    try:
        import httpx
        with httpx.Client(timeout=20, follow_redirects=True) as c:
            r = c.get(url)
            if r.status_code != 200:
                return None
            text = r.text
            cache_file.write_text(text, encoding="utf-8")
            return text
    except Exception as e:
        print(f"  [fetch error] {url}: {e}")
        return None


def raw_url(repo: str, branch: str, path: str) -> str:
    """Build a raw.githubusercontent.com URL (no API rate limit)."""
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"


# ── Chunking ────────────────────────────────────────────────────────────────
def chunk_markdown(text: str, max_chars: int = 1200) -> list[str]:
    """Split markdown by ## / ### headings, then by size."""
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    parts = re.split(r"(?=^#{1,3}\s)", text, flags=re.M)
    chunks: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) <= max_chars:
            chunks.append(p)
        else:
            paragraphs = p.split("\n\n")
            buf = ""
            for para in paragraphs:
                if len(buf) + len(para) + 2 > max_chars and buf:
                    chunks.append(buf.strip())
                    buf = para
                else:
                    buf = (buf + "\n\n" + para).strip()
            if buf:
                chunks.append(buf.strip())
    return [c for c in chunks if len(c) > 80]


def chunk_code(text: str, max_lines: int = 60) -> list[str]:
    """Split code by top-level definitions or fixed window."""
    text = text.expandtabs(4)
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return [text] if text.strip() else []
    # Group by top-level defs (functions / classes)
    chunks: list[str] = []
    buf: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        is_top_def = (
            (stripped.startswith(("def ", "class ", "async def ", "function ", "export ", "const ", "let ", "fn ", "func "))
             and not line.startswith((" ", "\t")))
        )
        if is_top_def and buf and len("\n".join(buf)) > 100:
            chunks.append("\n".join(buf).strip())
            buf = [line]
        else:
            buf.append(line)
            if len(buf) >= max_lines:
                chunks.append("\n".join(buf).strip())
                buf = []
    if buf:
        chunks.append("\n".join(buf).strip())
    return [c for c in chunks if c and len(c) > 80]


# ── Ingesters ───────────────────────────────────────────────────────────────
class Ingester:
    name = "base"
    index = "language_docs"

    def iter_chunks(self) -> Iterator[tuple[str, dict]]:
        yield from ()

    def run(self, max_chunks: int | None = None) -> int:
        print(f"\n── {self.name} → index: {self.index} ──")
        batch_texts: list[str] = []
        batch_metas: list[dict] = []
        total = 0
        for text, meta in self.iter_chunks():
            if max_chunks and total >= max_chunks:
                break
            batch_texts.append(text)
            batch_metas.append(meta)
            total += 1
            if len(batch_texts) >= 64:
                added = index_texts(batch_texts, self.index, batch_metas)
                print(f"  +{added} chunks  (total: {total})")
                batch_texts.clear()
                batch_metas.clear()
        if batch_texts:
            added = index_texts(batch_texts, self.index, batch_metas)
            print(f"  +{added} chunks  (total: {total})")
        print(f"  [OK] {self.name}: {total} chunks indexed")
        return total


# ── GitHub markdown documentation ingester (uses raw CDN, no API) ───────────
class GitHubMarkdownIngester(Ingester):
    """Fetch a hardcoded list of markdown files via raw.githubusercontent.com.

    Avoids the GitHub API entirely — works behind firewalls that block api.github.com
    but allow the raw CDN.
    """

    def __init__(
        self,
        name:   str,
        repo:   str,
        files:  list[str],
        branch: str = "main",
        index:  str = "language_docs",
    ):
        self.name   = name
        self.repo   = repo
        self.files  = files
        self.branch = branch
        self.index  = index

    def iter_chunks(self) -> Iterator[tuple[str, dict]]:
        print(f"  fetching {len(self.files)} files from {self.repo}@{self.branch}")
        ok = 0
        for path in self.files:
            url = raw_url(self.repo, self.branch, path)
            text = fetch(url)
            if not text:
                continue
            ok += 1
            for chunk in chunk_markdown(text):
                yield chunk, {
                    "source": f"github:{self.repo}",
                    "path":   path,
                    "name":   self.name,
                }
        print(f"  fetched {ok}/{len(self.files)} files")


# ── Local codebase ingester ─────────────────────────────────────────────────
class LocalCodebaseIngester(Ingester):
    name = "MaxCoder source code"
    index = "codebase"

    SKIP_DIRS = {".git", "node_modules", "__pycache__", "dist", "build",
                 ".venv", "venv", ".cache", "scripts/cache", "feedback_store",
                 "memory_store", "rag", "logs", "uploads", "workspaces"}
    CODE_EXTS = {".py", ".jsx", ".tsx", ".js", ".ts", ".rs", ".go",
                 ".rb", ".java", ".c", ".cpp", ".h", ".css", ".html"}

    def __init__(self, root: pathlib.Path = ROOT):
        self.root = root

    def iter_chunks(self) -> Iterator[tuple[str, dict]]:
        for p in self.root.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(self.root)
            if any(part in self.SKIP_DIRS for part in rel.parts):
                continue
            if p.suffix not in self.CODE_EXTS:
                continue
            if p.stat().st_size > 200_000:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for i, chunk in enumerate(chunk_code(text)):
                yield (
                    f"# File: {rel.as_posix()}\n\n```{p.suffix.lstrip('.')}\n{chunk}\n```",
                    {"source": "maxcoder_repo", "path": rel.as_posix(), "chunk": i},
                )


# ── Curated patterns ingester (bundled JSON of common Q/A pairs) ────────────
CURATED_PATTERNS: list[dict] = [
    # Python idioms
    {"q": "Reverse a string in Python", "a": "Use slicing with step -1: `s[::-1]`. Works on any sequence. O(n) time, O(n) space."},
    {"q": "Read a file line by line in Python", "a": "Use `with open(path) as f: for line in f: ...` — this streams without loading the full file. Wrap path in `pathlib.Path` for cross-platform compatibility."},
    {"q": "Parse JSON in Python with type safety", "a": "Use Pydantic v2: `class Model(BaseModel): name: str; age: int` then `Model.model_validate_json(raw)`. Raises ValidationError on bad input."},
    {"q": "Run async code in Python", "a": "Top-level: `asyncio.run(main())`. Inside a coroutine: `await foo()`. For parallel: `await asyncio.gather(t1, t2, t3)`."},
    {"q": "Memoize a Python function", "a": "Use `@functools.lru_cache(maxsize=None)` for pure functions. For instance methods, use `functools.cache` (Python 3.9+). Don't memoize functions with side effects."},
    {"q": "Iterate dict in sorted order Python", "a": "`for k in sorted(d): ...` for keys; `for k, v in sorted(d.items()): ...` for items. Dicts preserve insertion order since 3.7 but aren't sorted."},
    {"q": "Type-hint a function returning multiple types Python", "a": "Use union types: `def f(x: int) -> str | None:`. For older Python: `Optional[str]` from typing module."},
    {"q": "Catch multiple exception types Python", "a": "`except (ValueError, TypeError) as e:` — tuple of exception classes. Don't bare-except; that catches KeyboardInterrupt and SystemExit."},
    {"q": "Format string with f-string Python", "a": "`f'{name} is {age}'`. For padding: `f'{n:>5}'` (right-align), `f'{x:.2f}'` (2 decimals), `f'{x:,}'` (thousands sep). Python 3.6+."},
    {"q": "Make HTTP request in Python", "a": "Use `httpx`: `with httpx.Client() as c: r = c.get(url)` — supports HTTP/2, async, and is a drop-in for requests. For async: `httpx.AsyncClient()`."},

    # JavaScript / TypeScript
    {"q": "Clone object in JavaScript", "a": "Deep clone: `structuredClone(obj)` (modern). Shallow: `{...obj}` or `Object.assign({}, obj)`. Avoid `JSON.parse(JSON.stringify(obj))` — loses functions, dates, undefined."},
    {"q": "Wait for promise to resolve JS", "a": "`const result = await promise` inside async function. For multiple: `await Promise.all([p1, p2])`. For first to resolve: `Promise.race([p1, p2])`."},
    {"q": "Debounce function calls JavaScript", "a": "```js\nfunction debounce(fn, ms) {\n  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };\n}\n```\nUse for search input, resize handlers."},
    {"q": "TypeScript narrow type after null check", "a": "TS auto-narrows after `if (x !== null)`. For unions, use `typeof` or `instanceof`. For discriminated unions: `if (x.kind === 'a')`."},
    {"q": "TypeScript readonly array vs Array", "a": "`readonly string[]` or `ReadonlyArray<string>` — can't push/pop. Prefer for function parameters to prevent mutation."},
    {"q": "React useEffect cleanup", "a": "Return a cleanup function: `useEffect(() => { const id = setInterval(...); return () => clearInterval(id); }, [])`. Runs before next effect and on unmount."},
    {"q": "React derived state without useState", "a": "Compute it during render: `const isValid = name.length > 0`. Don't useState for derived values — it causes extra renders and gets out of sync."},
    {"q": "Fetch data in React", "a": "Use TanStack Query / SWR. They handle caching, retries, dedup. Avoid raw useEffect for fetching — easy to leak and race-condition."},
    {"q": "Next.js server component data fetching", "a": "In a `'use server'` or default server component, `await fetch(url, { cache: 'no-store' })` for fresh, or `{ next: { revalidate: 60 } }` for ISR."},

    # Rust
    {"q": "Iterate Vec without consuming Rust", "a": "`for x in &v { ... }` (immutable ref) or `for x in &mut v { ... }` (mutable ref). `for x in v { ... }` moves out of v."},
    {"q": "Read file Rust", "a": "Simple: `std::fs::read_to_string(path)?`. Streaming: `BufReader::new(File::open(path)?).lines()`. For async: `tokio::fs`."},
    {"q": "Rust error handling with anyhow", "a": "`fn main() -> anyhow::Result<()>` and use `?` everywhere. For libraries, prefer `thiserror` for typed errors."},
    {"q": "Box vs Rc vs Arc Rust", "a": "Box<T>: single owner, heap. Rc<T>: multi-owner, single-threaded. Arc<T>: multi-owner, thread-safe (uses atomics)."},

    # Go
    {"q": "Read file Go", "a": "`data, err := os.ReadFile(path); if err != nil { ... }`. Streaming: `bufio.NewScanner(file)`. Always defer Close."},
    {"q": "Go goroutine with wait", "a": "Use `sync.WaitGroup`: wg.Add(1) before launch, defer wg.Done() inside goroutine, wg.Wait() to block until all finish."},
    {"q": "Go channel buffered vs unbuffered", "a": "Unbuffered `make(chan int)`: sender blocks until receiver. Buffered `make(chan int, 10)`: sender blocks only when buffer full. Close to signal completion."},

    # SQL / DB
    {"q": "SQL find duplicate rows", "a": "`SELECT col, COUNT(*) FROM t GROUP BY col HAVING COUNT(*) > 1`. To get all duplicate rows: `SELECT * FROM t WHERE col IN (SELECT col FROM t GROUP BY col HAVING COUNT(*) > 1)`."},
    {"q": "SQL window function rank", "a": "`SELECT *, ROW_NUMBER() OVER (PARTITION BY group_col ORDER BY sort_col) AS rn FROM t`. Use RANK() for ties (gaps) or DENSE_RANK() for ties (no gaps)."},

    # DevOps / Bash
    {"q": "Bash check if file exists", "a": "`if [[ -f \"$path\" ]]; then ...; fi`. `-d` for directory, `-e` for any (file/dir/symlink), `-r` for readable."},
    {"q": "Bash loop over files safely", "a": "`while IFS= read -r -d '' f; do ...; done < <(find . -type f -print0)`. Handles spaces and newlines in filenames."},
    {"q": "Docker reduce image size", "a": "Multi-stage build: builder stage compiles, final stage copies binary. Use Alpine or distroless base. .dockerignore to skip node_modules / .git."},
    {"q": "Git undo last commit keep changes", "a": "`git reset --soft HEAD~1` — moves HEAD back, keeps staged. `git reset HEAD~1` keeps unstaged. `git reset --hard HEAD~1` discards everything (dangerous)."},

    # General CS
    {"q": "Big-O of common algorithms", "a": "Hash lookup: O(1) avg, O(n) worst. Binary search: O(log n). Sort: O(n log n). Naive substring: O(nm). Graph BFS/DFS: O(V+E)."},
    {"q": "When to use a Set vs Array", "a": "Set: uniqueness check, frequent contains() lookups (O(1)), no order needed. Array: ordered data, indexing by position, duplicates allowed, iteration speed."},
]

class CuratedPatternsIngester(Ingester):
    name = "Curated patterns & idioms"
    index = "snippets"

    def iter_chunks(self) -> Iterator[tuple[str, dict]]:
        for p in CURATED_PATTERNS:
            text = f"## Q: {p['q']}\n\n{p['a']}"
            yield text, {"source": "curated_patterns", "topic": p["q"][:80]}


# ── Error→solution patterns ─────────────────────────────────────────────────
ERROR_SOLUTIONS: list[dict] = [
    {"err": "ModuleNotFoundError in Python", "fix": "1. Confirm venv is active: `which python` should match your project venv. 2. `pip install <pkg>`. 3. If installed in a different env, the IDE may be using global Python — check interpreter setting."},
    {"err": "TypeError: 'NoneType' object is not subscriptable Python", "fix": "A function returned None where you expected a list/dict. Add `if result is None: ...` guard. Check the function — it likely has a code path that doesn't return."},
    {"err": "CORS error in browser", "fix": "Backend must set `Access-Control-Allow-Origin` header. In FastAPI: `app.add_middleware(CORSMiddleware, allow_origins=['*'])`. For credentials, must specify exact origin (not '*')."},
    {"err": "Cannot read properties of undefined JavaScript", "fix": "Object is undefined when you tried to access a property. Use optional chaining: `obj?.prop?.nested`. For arrays: `arr?.[0]`. Or default with `obj || {}`."},
    {"err": "Hydration mismatch error Next.js / React", "fix": "Server and client rendered different HTML. Causes: Date.now(), Math.random(), window/localStorage in render. Fix: useEffect for client-only logic, or `'use client'` directive in Next.js."},
    {"err": "ECONNREFUSED Node.js", "fix": "Service on the target port isn't running. 1. Confirm server started. 2. Check port — `lsof -i :PORT` or `netstat -ano | findstr PORT`. 3. Verify localhost vs 127.0.0.1 vs 0.0.0.0 binding."},
    {"err": "OOM Killed in Docker container", "fix": "Container exceeded memory limit. 1. Raise limit: `--memory=2g`. 2. Profile your app — often a leak or unbounded queue. 3. For Node: set `--max-old-space-size=1536`. 4. For Python: use generators, not lists."},
    {"err": "Pydantic ValidationError", "fix": "Input data doesn't match the model schema. Check `e.errors()` for exact field/reason. Common: missing required field, wrong type (str vs int), enum value not in choices."},
    {"err": "SQLAlchemy DetachedInstanceError", "fix": "Accessed a lazy-loaded attribute after the session was closed. Fix: 1. Eager-load with `selectinload`. 2. Keep session open for the request lifetime. 3. Refresh: `session.refresh(obj)`."},
    {"err": "React 'Cannot update component while rendering' error", "fix": "You called setState during render. Move into useEffect or an event handler. If it's derived state, compute during render instead of storing in state."},
    {"err": "ImportError: cannot import name 'X' (most likely circular)", "fix": "Two modules import each other. Fixes: 1. Import inside function instead of top-level. 2. Move shared code to a third module. 3. Use TYPE_CHECKING for type-only imports."},
    {"err": "Out of memory error machine learning training", "fix": "Reduce batch size first (biggest impact). Then: enable gradient checkpointing, use mixed precision (fp16/bf16), reduce sequence length, freeze early layers. As last resort: use a smaller model or quantize."},
    {"err": "git merge conflict", "fix": "1. `git status` shows conflicted files. 2. Open each, look for <<<<<<< / ======= / >>>>>>> markers. 3. Edit to keep the right code. 4. `git add <file>` then `git commit`. Abort with `git merge --abort`."},
    {"err": "npm ERR! peer dep conflict", "fix": "1. Try `npm install --legacy-peer-deps`. 2. Better: update conflicting packages to compatible versions. 3. Check `npm ls <pkg>` to see the dependency tree."},
    {"err": "Permission denied EACCES port 80", "fix": "Ports below 1024 need root on Linux. Either: run with sudo (bad), use a reverse proxy (Caddy/nginx on 80, your app on 8000), or `setcap` to grant the binary the capability."},
]

class ErrorSolutionsIngester(Ingester):
    name = "Error → solution patterns"
    index = "error_solutions"

    def iter_chunks(self) -> Iterator[tuple[str, dict]]:
        for p in ERROR_SOLUTIONS:
            text = f"## Error: {p['err']}\n\n### Fix\n{p['fix']}"
            yield text, {"source": "curated_errors", "topic": p["err"][:80]}


# ── Curated file lists per source (use canonical doc filenames) ─────────────
FASTAPI_FILES = [
    "docs/en/docs/index.md",
    "docs/en/docs/tutorial/index.md",
    "docs/en/docs/tutorial/first-steps.md",
    "docs/en/docs/tutorial/path-params.md",
    "docs/en/docs/tutorial/query-params.md",
    "docs/en/docs/tutorial/body.md",
    "docs/en/docs/tutorial/body-fields.md",
    "docs/en/docs/tutorial/body-multiple-params.md",
    "docs/en/docs/tutorial/body-nested-models.md",
    "docs/en/docs/tutorial/response-model.md",
    "docs/en/docs/tutorial/handling-errors.md",
    "docs/en/docs/tutorial/dependencies/index.md",
    "docs/en/docs/tutorial/security/index.md",
    "docs/en/docs/tutorial/security/oauth2-jwt.md",
    "docs/en/docs/tutorial/middleware.md",
    "docs/en/docs/tutorial/cors.md",
    "docs/en/docs/tutorial/sql-databases.md",
    "docs/en/docs/tutorial/bigger-applications.md",
    "docs/en/docs/tutorial/background-tasks.md",
    "docs/en/docs/tutorial/testing.md",
    "docs/en/docs/async.md",
    "docs/en/docs/deployment/index.md",
    "docs/en/docs/deployment/docker.md",
    "docs/en/docs/advanced/index.md",
    "docs/en/docs/advanced/response-directly.md",
    "docs/en/docs/advanced/custom-response.md",
    "docs/en/docs/advanced/middleware.md",
    "docs/en/docs/advanced/websockets.md",
    "docs/en/docs/advanced/events.md",
]

PYDANTIC_FILES = [
    "docs/index.md",
    "docs/concepts/models.md",
    "docs/concepts/fields.md",
    "docs/concepts/validators.md",
    "docs/concepts/serialization.md",
    "docs/concepts/types.md",
    "docs/concepts/json_schema.md",
    "docs/concepts/strict_mode.md",
    "docs/concepts/dataclasses.md",
    "docs/concepts/config.md",
    "docs/concepts/unions.md",
    "docs/concepts/conversion_table.md",
    "docs/migration.md",
]

REACT_LEARN_FILES = [
    "src/content/learn/index.md",
    "src/content/learn/describing-the-ui.md",
    "src/content/learn/your-first-component.md",
    "src/content/learn/importing-and-exporting-components.md",
    "src/content/learn/writing-markup-with-jsx.md",
    "src/content/learn/javascript-in-jsx-with-curly-braces.md",
    "src/content/learn/passing-props-to-a-component.md",
    "src/content/learn/conditional-rendering.md",
    "src/content/learn/rendering-lists.md",
    "src/content/learn/keeping-components-pure.md",
    "src/content/learn/adding-interactivity.md",
    "src/content/learn/responding-to-events.md",
    "src/content/learn/state-a-components-memory.md",
    "src/content/learn/render-and-commit.md",
    "src/content/learn/state-as-a-snapshot.md",
    "src/content/learn/queueing-a-series-of-state-updates.md",
    "src/content/learn/updating-objects-in-state.md",
    "src/content/learn/updating-arrays-in-state.md",
    "src/content/learn/managing-state.md",
    "src/content/learn/reacting-to-input-with-state.md",
    "src/content/learn/choosing-the-state-structure.md",
    "src/content/learn/sharing-state-between-components.md",
    "src/content/learn/preserving-and-resetting-state.md",
    "src/content/learn/escape-hatches.md",
    "src/content/learn/referencing-values-with-refs.md",
    "src/content/learn/manipulating-the-dom-with-refs.md",
    "src/content/learn/synchronizing-with-effects.md",
    "src/content/learn/you-might-not-need-an-effect.md",
    "src/content/learn/lifecycle-of-reactive-effects.md",
    "src/content/learn/separating-events-from-effects.md",
    "src/content/learn/removing-effect-dependencies.md",
    "src/content/learn/reusing-logic-with-custom-hooks.md",
]

REACT_REFERENCE_FILES = [
    "src/content/reference/react/useState.md",
    "src/content/reference/react/useEffect.md",
    "src/content/reference/react/useContext.md",
    "src/content/reference/react/useReducer.md",
    "src/content/reference/react/useCallback.md",
    "src/content/reference/react/useMemo.md",
    "src/content/reference/react/useRef.md",
    "src/content/reference/react/useImperativeHandle.md",
    "src/content/reference/react/useLayoutEffect.md",
    "src/content/reference/react/useTransition.md",
    "src/content/reference/react/useDeferredValue.md",
    "src/content/reference/react/useId.md",
    "src/content/reference/react/Suspense.md",
    "src/content/reference/react/memo.md",
    "src/content/reference/react/forwardRef.md",
    "src/content/reference/react/lazy.md",
    "src/content/reference/react/Fragment.md",
]

TS_HANDBOOK_FILES = [
    "packages/documentation/copy/en/handbook-v2/Basics.md",
    "packages/documentation/copy/en/handbook-v2/Everyday Types.md",
    "packages/documentation/copy/en/handbook-v2/Narrowing.md",
    "packages/documentation/copy/en/handbook-v2/More on Functions.md",
    "packages/documentation/copy/en/handbook-v2/Object Types.md",
    "packages/documentation/copy/en/handbook-v2/Type Manipulation/Generics.md",
    "packages/documentation/copy/en/handbook-v2/Type Manipulation/Keyof Type Operator.md",
    "packages/documentation/copy/en/handbook-v2/Type Manipulation/Typeof Type Operator.md",
    "packages/documentation/copy/en/handbook-v2/Type Manipulation/Indexed Access Types.md",
    "packages/documentation/copy/en/handbook-v2/Type Manipulation/Conditional Types.md",
    "packages/documentation/copy/en/handbook-v2/Type Manipulation/Mapped Types.md",
    "packages/documentation/copy/en/handbook-v2/Type Manipulation/Template Literal Types.md",
    "packages/documentation/copy/en/handbook-v2/Classes.md",
    "packages/documentation/copy/en/handbook-v2/Modules.md",
]

RUST_BOOK_FILES = [
    "src/ch01-00-getting-started.md",
    "src/ch03-00-common-programming-concepts.md",
    "src/ch04-00-understanding-ownership.md",
    "src/ch04-01-what-is-ownership.md",
    "src/ch04-02-references-and-borrowing.md",
    "src/ch04-03-slices.md",
    "src/ch05-00-structs.md",
    "src/ch06-00-enums.md",
    "src/ch06-02-match.md",
    "src/ch08-00-common-collections.md",
    "src/ch09-00-error-handling.md",
    "src/ch10-00-generics.md",
    "src/ch10-01-syntax.md",
    "src/ch10-02-traits.md",
    "src/ch10-03-lifetime-syntax.md",
    "src/ch11-00-testing.md",
    "src/ch13-00-functional-features.md",
    "src/ch13-01-closures.md",
    "src/ch13-02-iterators.md",
    "src/ch15-00-smart-pointers.md",
    "src/ch16-00-concurrency.md",
    "src/ch17-00-oop.md",
]

GO_DOC_FILES = [
    "_content/doc/effective_go.md",
    "_content/doc/faq.md",
    "_content/doc/go1.22.md",
    "_content/doc/asm.md",
    "_content/doc/cmd.md",
    "_content/doc/modules/managing-dependencies.md",
    "_content/doc/modules/version-numbers.md",
]

# ── Registry of sources for the standard preset ─────────────────────────────
def build_sources(stack_filter: str = "all") -> list[Ingester]:
    """Build the list of ingesters to run."""
    sources: list[Ingester] = [
        LocalCodebaseIngester(),
        CuratedPatternsIngester(),
        ErrorSolutionsIngester(),

        # Python ecosystem
        GitHubMarkdownIngester("FastAPI docs",       "fastapi/fastapi",      FASTAPI_FILES,        branch="master"),
        GitHubMarkdownIngester("Pydantic docs",      "pydantic/pydantic",    PYDANTIC_FILES,       branch="main"),

        # JS / React / Web
        GitHubMarkdownIngester("React Learn",        "reactjs/react.dev",    REACT_LEARN_FILES,    branch="main"),
        GitHubMarkdownIngester("React Reference",    "reactjs/react.dev",    REACT_REFERENCE_FILES,branch="main"),
        GitHubMarkdownIngester("TypeScript handbook","microsoft/TypeScript-Website", TS_HANDBOOK_FILES, branch="v2"),

        # Rust / Go
        GitHubMarkdownIngester("Rust book",          "rust-lang/book",       RUST_BOOK_FILES,      branch="main"),
        GitHubMarkdownIngester("Go effective Go",    "golang/go.dev",        GO_DOC_FILES,         branch="master"),
    ]
    return sources


# ── Main ────────────────────────────────────────────────────────────────────
def wipe_indexes() -> None:
    import shutil
    for sub in ("language_docs", "codebase", "error_solutions", "snippets"):
        path = INDEX_DIR / sub
        if path.exists():
            shutil.rmtree(path)
            print(f"  wiped {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="Run only one source by name", default=None)
    ap.add_argument("--rebuild", action="store_true", help="Wipe indexes first")
    ap.add_argument("--light", action="store_true", help="Quick first pass (fewer chunks)")
    ap.add_argument("--heavy", action="store_true", help="Full ingestion, no caps")
    args = ap.parse_args()

    if args.rebuild:
        print("── Wiping existing indexes ──")
        wipe_indexes()

    sources = build_sources()
    if args.source:
        sources = [s for s in sources if args.source.lower() in s.name.lower()]
        if not sources:
            print(f"No source matches '{args.source}'")
            return

    if args.light:
        cap = 80
    elif args.heavy:
        cap = None
    else:
        cap = 300  # standard

    t0 = time.time()
    grand = 0
    for s in sources:
        try:
            grand += s.run(max_chunks=cap)
        except Exception as e:
            print(f"  [FAIL] {s.name} failed: {e}")

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"  TOTAL: {grand:,} chunks indexed across {len(sources)} sources")
    print(f"  TIME:  {elapsed:.1f}s")
    print(f"  INDEX: {INDEX_DIR}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
