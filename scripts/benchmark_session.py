"""
Session benchmark — exercises every system touched in this development session
and produces a pass/fail report so we know exactly what's strong and what's weak.

Run with:
    .venv/Scripts/python.exe scripts/benchmark_session.py

Output: structured report grouped by subsystem. Each subsystem has a list of
checks; each check is either PASS, FAIL (hard problem — needs fixing) or WARN
(degraded but tolerable). At the end, an overall scorecard.

NOTE: this is deliberately fast — most checks are pure-Python or single-call.
The NLLB round-trip checks take longer because they hit the model. Skip them
with --skip-nllb if you just want quick correctness checks.
"""
from __future__ import annotations
import asyncio, sys, time, json, traceback, pathlib
from pathlib import Path

# Make the project importable when run from scripts/ directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── Reporting helpers ───────────────────────────────────────────────────────
COLORS = {"PASS":"\x1b[32m", "FAIL":"\x1b[31m", "WARN":"\x1b[33m", "RESET":"\x1b[0m"}
sections: list[dict] = []

def record(section: str, name: str, status: str, detail: str = ""):
    """status ∈ {PASS, FAIL, WARN}"""
    if not sections or sections[-1]["name"] != section:
        sections.append({"name": section, "checks": []})
    sections[-1]["checks"].append({"name": name, "status": status, "detail": detail})


def _print_report():
    print("\n" + "═" * 78)
    print(" SESSION BENCHMARK REPORT")
    print("═" * 78)
    totals = {"PASS":0, "FAIL":0, "WARN":0}
    for sec in sections:
        print(f"\n▸ {sec['name']}")
        for c in sec["checks"]:
            totals[c["status"]] += 1
            col = COLORS.get(c["status"], "")
            print(f"   {col}{c['status']:4}{COLORS['RESET']}  {c['name']}")
            if c["detail"] and c["status"] != "PASS":
                print(f"          └─ {c['detail']}")
    print("\n" + "─" * 78)
    total = sum(totals.values()) or 1
    pct = totals["PASS"] * 100 / total
    print(f"  PASS {totals['PASS']:>3} · WARN {totals['WARN']:>3} · FAIL {totals['FAIL']:>3}"
          f"   →   {pct:.1f}% pass rate ({total} checks)")
    print("─" * 78)
    return totals


# ── 1. Skill routing & intent detection ─────────────────────────────────────
def bench_routing():
    sect = "1. Routing & intent detection"
    from core.skills.translation        import TranslationSkill, _ensure_compiled
    from core.skills.file_generation    import (
        _detect_format, _detect_bilingual_targets, extract_literal_source,
    )
    from core.skills.base               import SkillContext
    from core.prompt_builder            import _is_conversational
    _ensure_compiled()

    t = TranslationSkill()

    # Translation skill matches
    cases = [
        ("translate this to russian: hello",             True,  "explicit verb"),
        ("how do you say goodbye in japanese",           True,  "how-do-you-say"),
        ("convert this to french",                       True,  "convert verb"),
        ('what does "bonjour" mean',                     True,  "what does ... mean"),
        ("tell me a joke in spanish",                    False, "bare 'in <lang>' must NOT match"),
        ("what is the capital of france in russian",     False, "general question in <lang>"),
        ("tell me a fact in uzbek about the universe",   False, "general question in <lang>"),
        ("generate a pdf with translation to russian",   False, "must defer to file_generation"),
    ]
    for q, expected, why in cases:
        ctx = SkillContext(query=q, history=[], model="m")
        got = t.matches(ctx)
        record(sect, f"translation matches: {why}",
               "PASS" if got == expected else "FAIL",
               f"query={q!r} got={got} expected={expected}")

    # Format detection
    for q, expected in [
        ("generate a pdf about cats", "pdf"),
        ("make me a docx report",     "docx"),
        ("export csv of users",       "csv"),
        ("just answer in english",    None),
    ]:
        got = _detect_format(q)
        record(sect, f"detect_format: {q[:40]}",
               "PASS" if got == expected else "FAIL",
               f"got={got!r} expected={expected!r}")

    # Multilingual targets
    multi_cases = [
        ("Generate a pdf bilingual english russian about cats",        ["russian"]),
        ("Generate a pdf translation into russian and uzbek",          ["russian", "uzbek"]),
        ("Make a pdf about the universe",                              []),
        ("Translate to spanish and make a comparison pdf",             ["spanish"]),
    ]
    for q, exp in multi_cases:
        got = _detect_bilingual_targets(q)
        record(sect, f"multilingual targets: {q[:50]}",
               "PASS" if got == exp else "FAIL",
               f"got={got} expected={exp}")

    # Literal source extraction
    lit_cases = [
        ("Generate a pdf with translation of sentences: This week is fun. into Russian and Uzbek.",
            "This week is fun."),
        ("Translate this paragraph: The sky is blue. into French",
            "The sky is blue."),
        ("Generate a pdf about cats", None),
    ]
    for q, exp in lit_cases:
        got = extract_literal_source(q)
        norm_got = (got or "").rstrip(".").strip().lower()
        norm_exp = (exp or "").rstrip(".").strip().lower()
        record(sect, f"literal extraction: {q[:50]}",
               "PASS" if norm_got == norm_exp else "FAIL",
               f"got={got!r} expected={exp!r}")

    # Conversational vs code intent
    conv_cases = [
        ("Tell me a joke",                              True),
        ("Why is the sky blue?",                        True),
        ("Tell me a fact in uzbek about the universe",  True),
        ("write a python function to sort a list",      False),
        ("debug my regex",                              False),
        ("generate a pdf invoice",                      False),
    ]
    for q, exp in conv_cases:
        got = _is_conversational(q)
        record(sect, f"conversational intent: {q[:45]}",
               "PASS" if got == exp else "FAIL",
               f"got={got} expected={exp}")


# ── 2. Translation memory: domain, glossary, corpus ─────────────────────────
def bench_translation_memory():
    sect = "2. Translation memory"
    from core.translation_memory import (
        _classify_domain, apply_domain_rewrites, load_glossary,
        find_relevant_examples, append_example,
    )
    from core.skills.translation import _glossary_for

    # Domain classification
    cases = [
        ("Python is a programming language with garbage collection",  "programming"),
        ("При этом показаны особенности языка художественного произведения", "literature"),
        ("The bug was caused by an off-by-one error",                  "programming"),
        ("The weather is sunny today",                                  "general"),
    ]
    for text, expected in cases:
        got = _classify_domain(text)
        record(sect, f"domain classify: {text[:40]}",
               "PASS" if got == expected else "FAIL",
               f"got={got} expected={expected}")

    # Domain-aware glossary — programming glossary must NOT inject into literary text
    lit_ru = "При этом показаны особенности языка художественного произведения"
    prog_en = "Python is a programming language with garbage collection and a standard library"
    g_lit = _glossary_for("Uzbek", source_text=lit_ru)
    g_prog = _glossary_for("Uzbek", source_text=prog_en)
    record(sect, "glossary suppressed on literary text",
           "PASS" if not g_lit.strip() else "FAIL",
           f"len(g_lit)={len(g_lit)} — should be 0")
    record(sect, "glossary applied on programming text",
           "PASS" if len(g_prog) > 100 else "FAIL",
           f"len(g_prog)={len(g_prog)} — should be > 100")

    # Literary rewrites
    raw = ("Bunda san'at asarining tilini ifodalashning o'ziga xos xususiyatlari, "
           "ijodiy matndagi tashqi his-tuyg'ular va tasvirlarning ifodasi ko'rsatiladi. "
           "San'at asari tilini o'rganish muallif nutqi va shaxslarning nutqi o'rtasidagi bog'liqlikni tahlil qiladi.")
    rewritten = apply_domain_rewrites(raw, "uzbek", "literature")
    checks = [
        ("badiiy asar"   in rewritten, "rewrites 'san'at asari' → 'badiiy asar'"),
        ("badiiy matn"   in rewritten, "rewrites 'ijodiy matn' → 'badiiy matn'"),
        ("qahramonlar"   in rewritten, "rewrites 'shaxslar' → 'qahramonlar'"),
        ("obrazlar"      in rewritten, "rewrites 'tasvirlar' → 'obrazlar'"),
        (rewritten[:1].isupper(),     "preserves sentence-start capitalization"),
    ]
    for ok, label in checks:
        record(sect, label, "PASS" if ok else "FAIL", f"output={rewritten[:140]!r}")


# ── 3. PDF generation (Unicode + multilingual) ──────────────────────────────
def bench_pdf():
    sect = "3. PDF generation"
    from core.file_generator import generate_pdf, generate_pdf_bilingual, generate_file

    # Unicode PDF (Cyrillic)
    try:
        data = generate_pdf("# Тест\n\nЭто проверка кириллицы. Здесь греческий: αβγ.")
        record(sect, "Unicode PDF generation (Cyrillic + Greek)",
               "PASS" if len(data) > 1000 else "FAIL",
               f"bytes={len(data)}")
    except Exception as e:
        record(sect, "Unicode PDF generation (Cyrillic + Greek)", "FAIL", f"{type(e).__name__}: {e}")

    # Bilingual PDF (legacy 2-arg form)
    try:
        pairs = [
            ({"type":"paragraph","text":"Hello world"}, "Привет мир"),
            ({"type":"paragraph","text":"Cats are nice"}, "Кошки приятные"),
        ]
        data = generate_pdf_bilingual(pairs, primary_label="English", target_label="Русский")
        record(sect, "Bilingual PDF (legacy 2-arg form)",
               "PASS" if len(data) > 1000 else "FAIL",
               f"bytes={len(data)}")
    except Exception as e:
        record(sect, "Bilingual PDF (legacy 2-arg form)", "FAIL", f"{type(e).__name__}: {e}")

    # Multilingual PDF (N languages)
    try:
        entries = [
            {"block":{"type":"paragraph","text":"Hello world"},
             "translations":{"russian":"Привет мир","uzbek":"Salom dunyo"}},
            {"block":{"type":"paragraph","text":"Cats are nice"},
             "translations":{"russian":"Кошки приятные","uzbek":"Mushuklar yoqimli"}},
        ]
        data = generate_pdf_bilingual(entries=entries, target_labels=["Русский","O'zbek"])
        record(sect, "Multilingual PDF (3-way)",
               "PASS" if len(data) > 1000 else "FAIL",
               f"bytes={len(data)}")
    except Exception as e:
        record(sect, "Multilingual PDF (3-way)", "FAIL", f"{type(e).__name__}: {e}")

    # Routing via generate_file
    try:
        payload = json.dumps({
            "primary_label": "English",
            "target_labels": ["Русский"],
            "target_langs":  ["russian"],
            "entries": [{"block":{"type":"paragraph","text":"Hi there"},
                         "translations":{"russian":"Привет"}}],
        }, ensure_ascii=False)
        data, mime, ext = generate_file("pdf-bilingual", payload)
        ok = mime == "application/pdf" and ext == ".pdf" and len(data) > 500
        record(sect, "pdf-bilingual via generate_file router",
               "PASS" if ok else "FAIL",
               f"mime={mime} ext={ext} bytes={len(data)}")
    except Exception as e:
        record(sect, "pdf-bilingual via generate_file router", "FAIL", f"{type(e).__name__}: {e}")


# ── 4. Streaming code-fence filter (conversation sanitization) ──────────────
def bench_sanitizer():
    sect = "4. Code-fence sanitizer (conversational mode)"
    # Reproduce the streaming filter inline so the test is independent of the
    # HTTP server. Same algorithm as in server/app.py gen().
    def filter_stream(tokens: "list[str]", suppress: bool) -> str:
        out, buf, in_fence = [], "", False
        for tok in tokens:
            if not suppress:
                out.append(tok)
                continue
            buf += tok
            while buf:
                if in_fence:
                    end = buf.find("```")
                    if end == -1:
                        if len(buf) > 3:
                            buf = buf[-3:]
                        break
                    buf = buf[end + 3:]
                    in_fence = False
                else:
                    start = buf.find("```")
                    if start == -1:
                        if len(buf) > 2:
                            out.append(buf[:-2])
                            buf = buf[-2:]
                        break
                    if start > 0:
                        out.append(buf[:start])
                    buf = buf[start + 3:]
                    in_fence = True
        if buf and not in_fence:
            out.append(buf)
        return "".join(out)

    cases = [
        # Plain text — passes through
        (["Here is a joke about cats. ", "They like fish."], True,
            "Here is a joke about cats. They like fish."),
        # Single inline fence — stripped
        (["Joke: cats are silly. ", "```css\n:root{}\n```", " The end."], True,
            "Joke: cats are silly.  The end."),
        # Multiple fences — all stripped
        (["A. ", "```py\nx=1\n```", " B. ", "```js\nlet x=1\n```", " C."], True,
            "A.  B.  C."),
        # Suppress off → fence preserved
        (["Code: ", "```py\nx=1\n```"], False,
            "Code: ```py\nx=1\n```"),
        # Token boundary inside fence marker — must still strip
        (["Joke. ", "``", "`css\nbody{}\n```", " End."], True,
            "Joke.  End."),
    ]
    for i, (tokens, suppress, expected) in enumerate(cases):
        got = filter_stream(tokens, suppress)
        record(sect, f"case {i+1}: suppress={suppress}",
               "PASS" if got == expected else "FAIL",
               f"got={got!r} expected={expected!r}")


# ── 5. NLLB end-to-end (real model — slower) ────────────────────────────────
async def bench_nllb(skip: bool):
    sect = "5. NLLB translation quality (real model)"
    if skip:
        record(sect, "NLLB tests (skipped via --skip-nllb)", "WARN", "rerun without --skip-nllb")
        return

    from core.translators import nllb_translate, detect_source_language
    from core.skills.translation import _verify_and_save, _char_similarity, _is_translation_failure

    # Source language detection
    det_cases = [
        ("При этом показаны особенности",     "russian"),
        ("The quick brown fox jumps",           "english"),
        ("Le langage de programmation",         "french"),
        ("Hola mundo, ¿cómo estás?",            "spanish"),
        ("Bu hafta juda qiziqarli",             "uzbek"),
    ]
    for text, exp in det_cases:
        got = detect_source_language(text)
        record(sect, f"detect_source_language: {exp}",
               "PASS" if got == exp else "WARN",
               f"got={got!r} expected={exp!r}")

    # Round-trip faithfulness — translate EN→target, then back to EN. We
    # measure trigram-Jaccard similarity. Empirically:
    #   ~0.40-0.55 = faithful, ~0.20-0.40 = lossy, < 0.20 = drifted.
    rt_cases = [
        ("The quick brown fox jumps over the lazy dog.",         "russian"),
        ("Python is a high-level programming language.",          "russian"),
        ("Hello, how are you today?",                              "uzbek"),
        ("The sky is blue and the grass is green.",                "spanish"),
        ("Machine learning models can recognize images.",          "french"),
    ]
    for en, target in rt_cases:
        t0 = time.time()
        try:
            tr   = await nllb_translate(en, target=target, source="english")
            back = await nllb_translate(tr, target="english", source=target)
            sim  = _char_similarity(en, back)
            dt   = time.time() - t0
            if sim >= 0.40:
                record(sect, f"round-trip EN→{target}→EN", "PASS",
                       f"sim={sim:.2f} ({dt:.1f}s)")
            elif sim >= 0.25:
                record(sect, f"round-trip EN→{target}→EN", "WARN",
                       f"lossy: sim={sim:.2f}")
            else:
                record(sect, f"round-trip EN→{target}→EN", "FAIL",
                       f"drifted: sim={sim:.2f} back={back[:90]!r}")
        except Exception as e:
            record(sect, f"round-trip EN→{target}→EN", "FAIL", f"{type(e).__name__}: {e}")

    # Validator must NOT reject valid Russian→Uzbek output
    try:
        src_ru = ("При этом показаны особенности выражения языка художественного "
                   "произведения, а также выражения внешних чувств.")
        tr     = await nllb_translate(src_ru, target="uzbek", source="russian")
        failure, reason = _is_translation_failure(src_ru, tr, "uzbek")
        record(sect, "validator accepts good RU→UZ output",
               "PASS" if not failure else "FAIL",
               reason or "validator returned failure=True on a clean translation")
    except Exception as e:
        record(sect, "validator accepts good RU→UZ output", "FAIL", str(e))


# ── 6. File-generation full bilingual pipeline (no LLM) ─────────────────────
async def bench_full_pipeline(skip_nllb: bool):
    sect = "6. End-to-end bilingual pipeline"
    if skip_nllb:
        record(sect, "Pipeline test (requires NLLB — skipped)", "WARN", "rerun without --skip-nllb")
        return

    from core.skills.file_generation import (
        extract_literal_source, _detect_bilingual_targets,
        _translate_blocks_for_multilingual,
    )
    from core.file_generator import generate_file

    query = ("Generate a pdf file with this translation of sentences: "
             "This week is very fun. Every day there is a special activity. "
             "For example, on Tuesdays there are separate games in the fresh air. "
             "into Russian and Uzbek.")
    try:
        src = extract_literal_source(query)
        targets = _detect_bilingual_targets(query)
        entries, labels = await _translate_blocks_for_multilingual(src, targets)
        payload = json.dumps({
            "primary_label": "English",
            "target_labels": labels,
            "target_langs":  targets,
            "entries":       entries,
        }, ensure_ascii=False)
        pdf, mime, ext = generate_file("pdf-bilingual", payload)
        # Spot-check the entries
        all_have_trans = all(
            all(t.strip() for t in ent["translations"].values())
            for ent in entries if ent["block"]["type"] == "paragraph"
        )
        record(sect, "extract → translate(N) → render PDF",
               "PASS" if len(pdf) > 1000 and mime == "application/pdf" else "FAIL",
               f"bytes={len(pdf)} mime={mime} entries={len(entries)}")
        record(sect, "every translatable block has all-language translations",
               "PASS" if all_have_trans else "FAIL",
               f"entries={json.dumps([e['translations'] for e in entries], ensure_ascii=False)[:300]}")
    except Exception as e:
        record(sect, "extract → translate(N) → render PDF", "FAIL",
               f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}")


# ── 7. Tools & file I/O ─────────────────────────────────────────────────────
def bench_tools():
    sect = "7. Tools (file I/O + dispatcher)"
    import os, tempfile
    from core import tools
    from core.tools import safe_path, read_file, write_file, list_dir, delete_file, parse_tool_calls

    # Write → read → delete round-trip in the workspace
    fname = "_bench_tmp.txt"
    try:
        msg = write_file(fname, "hello from benchmark\nline 2")
        record(sect, "write_file", "PASS" if "Wrote" in msg or "saved" in msg.lower() or "ok" in msg.lower() else "WARN",
               f"returned: {msg!r}")
    except Exception as e:
        record(sect, "write_file", "FAIL", f"{type(e).__name__}: {e}")

    try:
        content = read_file(fname)
        record(sect, "read_file round-trip",
               "PASS" if "hello from benchmark" in content else "FAIL",
               f"got: {content[:80]!r}")
    except Exception as e:
        record(sect, "read_file round-trip", "FAIL", f"{type(e).__name__}: {e}")

    try:
        listing = list_dir(".")
        record(sect, "list_dir",
               "PASS" if fname in listing else "WARN",
               f"listing did not contain {fname}")
    except Exception as e:
        record(sect, "list_dir", "FAIL", f"{type(e).__name__}: {e}")

    try:
        delete_file(fname)
        record(sect, "delete_file", "PASS")
    except Exception as e:
        record(sect, "delete_file", "FAIL", f"{type(e).__name__}: {e}")

    # Path safety — must reject path traversal
    try:
        safe_path("../../etc/passwd")
        record(sect, "safe_path blocks traversal", "FAIL", "did not raise on ../../etc/passwd")
    except Exception:
        record(sect, "safe_path blocks traversal", "PASS")

    # Tool-call parsing — XML-style <tool:name path="..."/> format
    sample = 'Some text\n<tool:read_file path="a.txt"/>\n more text'
    parsed = parse_tool_calls(sample)
    record(sect, "parse_tool_calls extracts well-formed call",
           "PASS" if parsed and parsed[0].get("tool") == "read_file" else "FAIL",
           f"got: {parsed!r}")


# ── 8. File parser ──────────────────────────────────────────────────────────
def bench_file_parser():
    sect = "8. File parser"
    from core.file_parser import parse_file

    # Plain text
    txt = parse_file("note.txt", b"hello world\nline 2")
    record(sect, "parse plain text",
           "PASS" if "hello world" in txt else "FAIL", f"got: {txt[:80]!r}")

    # CSV
    csv_data = b"name,age\nalice,30\nbob,25\n"
    csv_out = parse_file("people.csv", csv_data)
    ok = "alice" in csv_out and "30" in csv_out
    record(sect, "parse CSV", "PASS" if ok else "FAIL", f"got: {csv_out[:120]!r}")

    # Unknown extension → graceful fallback (text or warning)
    try:
        out = parse_file("weird.xyz", b"plain content here")
        record(sect, "parse unknown extension (graceful)",
               "PASS" if "plain content here" in out or len(out) > 0 else "WARN",
               f"got: {out[:80]!r}")
    except Exception as e:
        record(sect, "parse unknown extension (graceful)", "FAIL", str(e))


# ── 9. Code executor ────────────────────────────────────────────────────────
def bench_executor():
    sect = "9. Code executor (sandboxed)"
    from core.executor import run_snippet

    # Python — print
    try:
        r = run_snippet("print('hello from sandbox')", "python", auto_install=False)
        ok = r.get("ok") and "hello from sandbox" in (r.get("stdout", "") or "")
        record(sect, "python: print", "PASS" if ok else "FAIL", f"result: {r}")
    except Exception as e:
        record(sect, "python: print", "FAIL", str(e))

    # Python — arithmetic
    try:
        r = run_snippet("print(2 ** 10)", "python", auto_install=False)
        ok = r.get("ok") and "1024" in (r.get("stdout", "") or "")
        record(sect, "python: arithmetic", "PASS" if ok else "FAIL", f"result: {r}")
    except Exception as e:
        record(sect, "python: arithmetic", "FAIL", str(e))

    # Python — error captured
    try:
        r = run_snippet("1/0", "python", auto_install=False)
        ok = not r.get("ok") and "ZeroDivisionError" in (r.get("stderr", "") or "")
        record(sect, "python: error captured", "PASS" if ok else "FAIL", f"result: {r}")
    except Exception as e:
        record(sect, "python: error captured", "FAIL", str(e))


# ── 10. Long-term memory (ChromaDB) ─────────────────────────────────────────
def bench_memory():
    sect = "10. Long-term memory"
    try:
        from core import memory
    except Exception as e:
        record(sect, "import memory module", "FAIL", str(e))
        return

    # Save a unique marker and try to retrieve it
    marker = f"BENCHMARK_MARKER_{int(time.time())} user prefers dark mode and tabs over spaces"
    try:
        memory.save(marker, category="preference")
        record(sect, "memory.save", "PASS")
    except Exception as e:
        record(sect, "memory.save", "FAIL", str(e))
        return

    try:
        ctx = memory.retrieve("dark mode preference", k=3)
        record(sect, "memory.retrieve finds saved marker",
               "PASS" if "dark mode" in ctx else "WARN",
               f"retrieved ctx (first 200): {ctx[:200]!r}")
    except Exception as e:
        record(sect, "memory.retrieve finds saved marker", "FAIL", str(e))


# ── 11. Chat memory (entity extraction + reference resolution) ──────────────
def bench_chat_memory():
    sect = "11. Chat memory (within-session)"
    from core.chat_memory import extract_memory, resolve_references, memory_summary

    history = [
        {"role": "user",      "content": "I'm building a FastAPI app called Bluebird."},
        {"role": "assistant", "content": "Great, FastAPI is a solid choice."},
        {"role": "user",      "content": "Generate a PDF report about Python decorators."},
        {"role": "assistant", "content": "@@GENERATE:pdf\n# Decorators in Python\n@@END"},
    ]
    mem = extract_memory(history)
    record(sect, "extract_memory returns ChatMemory",
           "PASS" if mem is not None else "FAIL",
           f"type={type(mem).__name__}")

    summary = memory_summary(mem, max_items=8)
    has_fastapi = "FastAPI" in summary or "fastapi" in summary.lower()
    has_pdf     = "pdf" in summary.lower() or "decorat" in summary.lower()
    record(sect, "memory_summary captures named entities",
           "PASS" if (has_fastapi or has_pdf) else "WARN",
           f"summary: {summary[:200]!r}")

    # Reference resolution: "deploy it" with FastAPI in memory → should expand
    resolved = resolve_references("deploy it to production", mem)
    record(sect, "resolve_references runs",
           "PASS" if isinstance(resolved, str) and len(resolved) > 0 else "FAIL",
           f"resolved: {resolved[:120]!r}")


# ── 12. Uncertainty assessor (hedge detection) ──────────────────────────────
def bench_uncertainty():
    sect = "12. Uncertainty / hedging"
    from core.uncertainty import detect_hedges

    confident = "The capital of France is Paris."
    hedgy     = "I think maybe Paris is probably the capital, though I'm not 100% sure."

    c = detect_hedges(confident)
    h = detect_hedges(hedgy)
    record(sect, "low hedges on confident statement",
           "PASS" if c.get("score", 0) <= 1 else "WARN",
           f"confident hedges: {c}")
    record(sect, "high hedges on uncertain statement",
           "PASS" if h.get("score", 0) >= 2 else "WARN",
           f"hedgy hedges: {h}")


# ── 13. Reasoner (LLM — math + logic) ───────────────────────────────────────
async def bench_reasoner(skip: bool):
    sect = "13. Reasoner (LLM)"
    if skip:
        record(sect, "Reasoner tests (skipped via --skip-llm)", "WARN", "rerun without --skip-llm")
        return
    from core.reasoner import reason, classify, looks_technical

    # Classification is pure-Python — always test
    cls_cases = [
        ("solve x^2 = 25",                "math"),
        ("what is 17 * 23",                "math"),
        ("compare REST vs GraphQL",        "math"),  # reasoning task
        ("hello",                          "trivial"),
        ("generate a pdf invoice",         "trivial"),
        ("debug my python function",       "debug"),
    ]
    for q, exp in cls_cases:
        got = classify(q)
        record(sect, f"classify({q[:40]!r}) → {exp}",
               "PASS" if got == exp else "WARN",
               f"got={got!r} expected={exp!r}")

    record(sect, "looks_technical on code question",
           "PASS" if looks_technical("write a Python function") else "WARN")

    # Real reasoner call
    try:
        t0 = time.time()
        result = await reason(
            query="What is 17 * 23? Reply with the integer only.",
            context="", task_type="math",
            fast_model="maxcoder-fast", strong_model="maxcoder-fast",
        )
        dt = time.time() - t0
        answer = (getattr(result, "answer", None) or
                  (result.get("answer") if isinstance(result, dict) else str(result)))
        ok = answer and "391" in str(answer)
        record(sect, f"reasoner: 17 * 23 ({dt:.1f}s)",
               "PASS" if ok else "WARN",
               f"answer: {str(answer)[:160]!r}")
    except Exception as e:
        record(sect, "reasoner: 17 * 23", "FAIL", f"{type(e).__name__}: {e}")


# ── 14. Query rewriter (LLM) ────────────────────────────────────────────────
async def bench_rewriter(skip: bool):
    sect = "14. Query rewriter (LLM)"
    if skip:
        record(sect, "Rewriter tests (skipped)", "WARN", "rerun without --skip-llm")
        return
    from core.query_rewriter import rewrite

    try:
        t0 = time.time()
        out = await rewrite("fix it", model="maxcoder-fast")
        dt = time.time() - t0
        # We can't predict the exact rewrite without context, but it should
        # return SOMETHING longer or at least a string.
        ok = isinstance(out, str) and len(out) > 0
        record(sect, f"rewrite returns string ({dt:.1f}s)",
               "PASS" if ok else "FAIL",
               f"out: {out[:160]!r}")
    except Exception as e:
        record(sect, "rewrite returns string", "FAIL", f"{type(e).__name__}: {e}")


# ── 15. RAG retriever ───────────────────────────────────────────────────────
def bench_rag():
    sect = "15. RAG retriever"
    try:
        from core.rag_retriever import retrieve
    except Exception as e:
        record(sect, "import rag_retriever", "FAIL", str(e))
        return

    try:
        ctx = retrieve("python list comprehension syntax", k_per_index=3)
        # Retrieval may return empty if indexes are not populated; treat empty
        # as WARN (a fresh install would hit this) not FAIL.
        if not ctx or not ctx.strip():
            record(sect, "retrieve('python list comprehension')",
                   "WARN", "indexes empty — run scripts/ingest_datasets.py to populate")
        else:
            ok = "comprehension" in ctx.lower() or "python" in ctx.lower() or len(ctx) > 50
            record(sect, "retrieve('python list comprehension')",
                   "PASS" if ok else "WARN",
                   f"ctx (first 200): {ctx[:200]!r}")
    except Exception as e:
        record(sect, "retrieve('python list comprehension')", "FAIL", str(e))


# ── 16. Web skills (DuckDuckGo + page fetch) ────────────────────────────────
async def bench_web(skip: bool):
    sect = "16. Web skills (network)"
    if skip:
        record(sect, "Web tests (skipped via --skip-net)", "WARN", "rerun without --skip-net")
        return
    from core.web_search    import should_search, extract_urls
    from core.web_navigator import fetch_smart

    # Pure-python helpers — broader coverage now that should_search has
    # time-sensitive triggers.
    ss_cases = [
        ("today's weather",                              True),
        ("latest news on AI",                            True),
        ("current stock price of NVDA",                  True),
        ("who won the game tonight",                     True),
        ("how do I write a for loop",                    False),
        ("what is recursion",                            False),
        ("install fastapi",                              True),    # info lookup
        ("write a sorting function",                     False),
    ]
    for q, exp in ss_cases:
        got = should_search(q)
        record(sect, f"should_search({q[:35]!r}) → {exp}",
               "PASS" if got == exp else "WARN",
               f"got={got}")
    record(sect, "extract_urls",
           "PASS" if extract_urls("see https://example.com here") == ["https://example.com"] else "FAIL",
           f"got: {extract_urls('see https://example.com here')}")

    # Real network — fetch_smart on a stable page
    try:
        t0 = time.time()
        kind, content, links = await fetch_smart("https://example.com")
        dt = time.time() - t0
        ok = content and ("Example Domain" in content or "example" in content.lower()) and len(content) > 50
        record(sect, f"fetch_smart('example.com') ({dt:.1f}s)",
               "PASS" if ok else "WARN",
               f"kind={kind} bytes={len(content or '')} first={(content or '')[:100]!r}")
    except Exception as e:
        record(sect, "fetch_smart('example.com')", "FAIL", f"{type(e).__name__}: {e}")


# ── 17. General intelligence + coding (LLM) ─────────────────────────────────
async def bench_intelligence(skip: bool):
    sect = "17. General intelligence + coding (LLM)"
    if skip:
        record(sect, "Intelligence tests (skipped)", "WARN", "rerun without --skip-llm")
        return
    from core.generator import generate

    async def ask(prompt: str, model: str = "maxcoder-fast", **opts) -> str:
        msgs = [{"role":"user", "content": prompt}]
        return await generate(msgs, model=model,
                               options={"num_predict": 200, "temperature": 0.1, **opts})

    # General knowledge
    try:
        t0 = time.time()
        out = await ask("What is the capital of France? Answer in one word.")
        dt = time.time() - t0
        record(sect, f"capital of France ({dt:.1f}s)",
               "PASS" if "paris" in out.lower() else "WARN",
               f"got: {out[:120]!r}")
    except Exception as e:
        record(sect, "capital of France", "FAIL", str(e))

    # Logical reasoning
    try:
        t0 = time.time()
        out = await ask(
            "Alice is taller than Bob. Bob is taller than Carol. Who is the shortest? "
            "Answer with just one name."
        )
        dt = time.time() - t0
        record(sect, f"logic: shortest of A>B>C ({dt:.1f}s)",
               "PASS" if "carol" in out.lower() else "WARN",
               f"got: {out[:120]!r}")
    except Exception as e:
        record(sect, "logic: shortest", "FAIL", str(e))

    # Code generation — must produce something that PARSES as Python
    import ast as _ast
    try:
        t0 = time.time()
        out = await ask(
            "Write a Python function named reverse_string that takes a string and "
            "returns it reversed. Output ONLY the code, no explanation, no markdown."
        )
        dt = time.time() - t0
        # Strip markdown fences if present
        code = out
        if "```" in code:
            parts = code.split("```")
            for p in parts:
                if "def " in p:
                    code = p.lstrip("python\n").lstrip()
                    break
        # Check it parses and has the expected function
        try:
            tree = _ast.parse(code)
            has_fn = any(isinstance(n, _ast.FunctionDef) and n.name == "reverse_string"
                          for n in _ast.walk(tree))
            record(sect, f"code: reverse_string parses + defines fn ({dt:.1f}s)",
                   "PASS" if has_fn else "WARN",
                   f"got: {out[:200]!r}")
        except SyntaxError as se:
            record(sect, f"code: reverse_string parses", "WARN",
                   f"SyntaxError — got: {out[:200]!r}")
    except Exception as e:
        record(sect, "code: reverse_string", "FAIL", str(e))


# ── 18. Agentic loop (multi-step tool use) ──────────────────────────────────
async def bench_agent(skip: bool):
    sect = "18. Agentic loop (multi-step)"
    if skip:
        record(sect, "Agent tests (skipped via --skip-llm)", "WARN", "rerun without --skip-llm")
        return
    from core.agent       import run_agent
    from core.agent_tools import TOOLS, dispatch

    # 18a. Tool registry sanity
    record(sect, "tool registry loaded",
           "PASS" if len(TOOLS) >= 8 and "finish" in TOOLS else "FAIL",
           f"got {len(TOOLS)} tools: {list(TOOLS.keys())}")

    # 18b. Dispatch unknown tool returns error (not raise)
    out = await dispatch("does_not_exist", {})
    record(sect, "dispatch unknown tool returns error string",
           "PASS" if out.startswith("ERROR") else "FAIL",
           f"got: {out[:120]!r}")

    # 18c. run_python via dispatch
    out = await dispatch("run_python", {"code": "print(7 * 11)"})
    record(sect, "dispatch run_python(7*11)",
           "PASS" if "77" in out else "FAIL",
           f"got: {out[:140]!r}")

    # 18c2. replace_in_file — happy path
    workspace_root = pathlib.Path(__file__).resolve().parent.parent / "workspace"
    workspace_root.mkdir(exist_ok=True)
    edit_file = workspace_root / "_edit_test.txt"
    try:
        edit_file.write_text("hello alpha\nhello beta\nhello gamma\n", encoding="utf-8")
        out = await dispatch("replace_in_file", {
            "rel_path": "_edit_test.txt",
            "old_string": "hello beta",
            "new_string": "GREETINGS_BETA",
        })
        after = edit_file.read_text(encoding="utf-8")
        record(sect, "replace_in_file: unique substitution",
               "PASS" if "GREETINGS_BETA" in after and "hello alpha" in after else "FAIL",
               f"after={after!r}  ret={out!r}")
    except Exception as e:
        record(sect, "replace_in_file: unique substitution", "FAIL", str(e))

    # 18c3. replace_in_file — ambiguous match must REFUSE
    try:
        edit_file.write_text("hello alpha\nhello beta\nhello gamma\n", encoding="utf-8")
        out = await dispatch("replace_in_file", {
            "rel_path": "_edit_test.txt",
            "old_string": "hello",
            "new_string": "GOODBYE",
        })
        record(sect, "replace_in_file: ambiguous match refused",
               "PASS" if out.startswith("ERROR") and "3 times" in out else "FAIL",
               f"got: {out!r}")
    except Exception as e:
        record(sect, "replace_in_file: ambiguous match refused", "FAIL", str(e))

    # 18c4. replace_in_file — replace_all allowed
    try:
        edit_file.write_text("hello alpha\nhello beta\nhello gamma\n", encoding="utf-8")
        out = await dispatch("replace_in_file", {
            "rel_path": "_edit_test.txt",
            "old_string": "hello",
            "new_string": "GOODBYE",
            "replace_all": True,
        })
        after = edit_file.read_text(encoding="utf-8")
        record(sect, "replace_in_file: replace_all=true",
               "PASS" if after.count("GOODBYE") == 3 and "hello" not in after else "FAIL",
               f"after={after!r}")
    except Exception as e:
        record(sect, "replace_in_file: replace_all=true", "FAIL", str(e))

    # 18c5. replace_in_file — old_string not found
    try:
        edit_file.write_text("only this content\n", encoding="utf-8")
        out = await dispatch("replace_in_file", {
            "rel_path": "_edit_test.txt",
            "old_string": "NOT THERE",
            "new_string": "X",
        })
        record(sect, "replace_in_file: missing old_string errors",
               "PASS" if out.startswith("ERROR") and "not found" in out else "FAIL",
               f"got: {out!r}")
    except Exception as e:
        record(sect, "replace_in_file: missing old_string errors", "FAIL", str(e))

    # 18c6. replace_in_file — missing file
    missing = workspace_root / "_bench_missing_file.txt"
    if missing.exists():
        try: missing.unlink()
        except Exception: pass
    out = await dispatch("replace_in_file", {
        "rel_path": "_bench_missing_file.txt",
        "old_string": "x",
        "new_string": "y",
    })
    record(sect, "replace_in_file: missing file errors",
           "PASS" if out.startswith("ERROR") and "not found" in out else "FAIL",
           f"got: {out!r}")

    # Cleanup
    if edit_file.exists():
        try: edit_file.unlink()
        except Exception: pass

    # 18c7. mkdir → list_dir round trip
    try:
        out = await dispatch("mkdir", {"rel_path": "_bench_mkdir/nested"})
        ok_mk = out.startswith("OK")
        # Cleanup
        import shutil
        mk_path = pathlib.Path(__file__).resolve().parent.parent / "workspace" / "_bench_mkdir"
        if mk_path.exists():
            shutil.rmtree(mk_path)
        record(sect, "mkdir creates nested dir",
               "PASS" if ok_mk else "FAIL", f"got: {out!r}")
    except Exception as e:
        record(sect, "mkdir creates nested dir", "FAIL", str(e))

    # 18c8. grep — find content + filter by glob
    try:
        ws_root = pathlib.Path(__file__).resolve().parent.parent / "workspace"
        (ws_root / "_grep_a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
        (ws_root / "_grep_b.py").write_text("def beta():\n    return 2\n", encoding="utf-8")
        (ws_root / "_grep_c.txt").write_text("def gamma():\n", encoding="utf-8")

        out = await dispatch("grep", {"pattern": r"def \w+", "glob": "_grep_*.py"})
        ok = ("alpha" in out and "beta" in out and "gamma" not in out)
        record(sect, "grep finds matches with glob filter",
               "PASS" if ok else "FAIL", f"got: {out!r}")

        # Regex error → graceful
        out = await dispatch("grep", {"pattern": "(unclosed", "glob": "_grep_*.py"})
        record(sect, "grep handles invalid regex",
               "PASS" if out.startswith("ERROR") else "FAIL", f"got: {out!r}")

        # Cleanup
        for f in ("_grep_a.py", "_grep_b.py", "_grep_c.txt"):
            (ws_root / f).unlink(missing_ok=True)
    except Exception as e:
        record(sect, "grep finds matches with glob filter", "FAIL", str(e))

    # 18c9. run_shell — allowlist + security
    try:
        out = await dispatch("run_shell", {"command": "echo hello-shell"})
        record(sect, "run_shell allowed verb (echo)",
               "PASS" if "hello-shell" in out and "exit 0" in out else "FAIL",
               f"got: {out!r}")

        out = await dispatch("run_shell", {"command": "rm -rf /"})
        record(sect, "run_shell blocks 'rm'",
               "PASS" if out.startswith("ERROR") and "allowlist" in out else "FAIL",
               f"got: {out[:120]!r}")

        out = await dispatch("run_shell", {"command": "ls | grep py"})
        record(sect, "run_shell blocks pipe character",
               "PASS" if out.startswith("ERROR") and "forbidden" in out else "FAIL",
               f"got: {out!r}")

        out = await dispatch("run_shell", {"command": "ls; rm file"})
        record(sect, "run_shell blocks semicolon chaining",
               "PASS" if out.startswith("ERROR") and "forbidden" in out else "FAIL",
               f"got: {out!r}")

        out = await dispatch("run_shell", {"command": "ls > /etc/passwd"})
        record(sect, "run_shell blocks redirect",
               "PASS" if out.startswith("ERROR") and "forbidden" in out else "FAIL",
               f"got: {out!r}")

        out = await dispatch("run_shell", {"command": ""})
        record(sect, "run_shell rejects empty command",
               "PASS" if out.startswith("ERROR") else "FAIL", f"got: {out!r}")
    except Exception as e:
        record(sect, "run_shell suite", "FAIL", str(e))

    # 18d. End-to-end agent: math verification — MUST use a tool and finish
    try:
        t0 = time.time()
        state = await run_agent(
            "What is 2 to the power of 50? Verify by computing with Python "
            "and respond with just the number.",
            model="maxcoder-fast", max_steps=4,
        )
        dt = time.time() - t0
        expected = str(2**50)   # 1125899906842624
        tool_used = any(s.kind == "tool_call" for s in state.steps)
        finished  = state.done and bool(state.answer)
        correct   = expected in state.answer
        record(sect, f"agent: math verify 2^50 ({dt:.1f}s, {state.tool_calls} tools)",
               "PASS" if (tool_used and finished and correct) else
               ("WARN" if (tool_used and finished) else "FAIL"),
               f"answer={state.answer[:160]!r}  expected to contain {expected!r}")
    except Exception as e:
        record(sect, "agent: math verify 2^50", "FAIL", f"{type(e).__name__}: {e}")

    # 18e. Agent uses write_file then read_file — exercises a real two-step
    # workflow inside the sandboxed workspace.
    try:
        import os
        # Pre-clean any leftover file from a previous run so the test is
        # idempotent and the agent must actually write it.
        ws_marker = pathlib.Path(__file__).resolve().parent.parent / "workspace" / "_agent_test.txt"
        if ws_marker.exists():
            ws_marker.unlink()

        t0 = time.time()
        state = await run_agent(
            "Write 'hello-from-agent-42' to the file '_agent_test.txt' in the workspace, "
            "then read it back and tell me what was in it. Use write_file then read_file.",
            model="maxcoder-fast", max_steps=5,
        )
        dt = time.time() - t0
        tools_used = [s.tool for s in state.steps if s.kind == "tool_call"]
        used_write = "write_file" in tools_used
        used_read  = "read_file"  in tools_used
        marker_in_answer = "hello-from-agent-42" in (state.answer or "")
        if used_write and used_read and marker_in_answer and state.done:
            status, detail = "PASS", f"tools={tools_used} answer={state.answer[:120]!r}"
        elif state.done and marker_in_answer:
            status, detail = "WARN", f"answer correct but tool usage atypical: {tools_used}"
        else:
            status, detail = "FAIL", f"tools={tools_used} answer={state.answer[:140]!r}"
        record(sect, f"agent: write+read round-trip ({dt:.1f}s, {state.tool_calls} tools)",
               status, detail)

        # Cleanup
        if ws_marker.exists():
            try: ws_marker.unlink()
            except Exception: pass
    except Exception as e:
        record(sect, "agent: write+read round-trip", "FAIL", str(e))

    # 18e2. Reflection fires after ≥2 tool calls
    try:
        # A query that genuinely needs multiple steps so reflection has a
        # chance to fire. write → read → expected to also do one more thing.
        ws_marker = pathlib.Path(__file__).resolve().parent.parent / "workspace" / "_reflect_test.txt"
        if ws_marker.exists():
            ws_marker.unlink()

        t0 = time.time()
        state = await run_agent(
            "Create a file '_reflect_test.txt' containing '42', then read it back, "
            "then compute the square of its value using Python. "
            "Use write_file, read_file, and run_python in that order.",
            model="maxcoder-fast", max_steps=6,
        )
        dt = time.time() - t0
        reflections = [s for s in state.steps if s.kind == "reflect"]
        record(sect, f"agent: reflection fires mid-flight ({dt:.1f}s, {state.tool_calls} tools, {len(reflections)} reflections)",
               "PASS" if reflections and state.done else
               ("WARN" if state.done else "FAIL"),
               f"reflections={len(reflections)} answer={state.answer[:140]!r}")

        if ws_marker.exists():
            try: ws_marker.unlink()
            except Exception: pass
    except Exception as e:
        record(sect, "agent: reflection fires mid-flight", "FAIL", str(e))

    # 18f. Max-steps safety — agent must terminate even when stuck
    try:
        t0 = time.time()
        state = await run_agent(
            # Deliberately vague — model may go in circles, must hit the cap
            "Tell me something true.",
            model="maxcoder-fast", max_steps=2,
        )
        dt = time.time() - t0
        record(sect, f"agent: terminates within max_steps ({dt:.1f}s)",
               "PASS" if state.done and state.tool_calls <= 2 else "FAIL",
               f"tool_calls={state.tool_calls} done={state.done}")
    except Exception as e:
        record(sect, "agent: terminates within max_steps", "FAIL", str(e))


# ── 19. Optimization layer (router + cache) ─────────────────────────────────
async def bench_optimizations(skip: bool):
    sect = "19. Optimization layer (router + cache)"

    # 19a. Model router — pure-Python, always test
    from core.model_router import pick_model
    cases = [
        # (query, expected_model_kind: "fast" | "strong")
        ("hi",                                           "fast"),
        ("hello",                                        "fast"),
        ("ok thanks",                                    "fast"),
        ("what time is it",                              "fast"),
        ("write a python function to merge sorted lists","strong"),
        ("debug this stack trace and explain the bug",   "strong"),
        ("generate a pdf invoice with three line items", "strong"),
        ("compare REST vs GraphQL trade-offs",           "strong"),
    ]
    for q, kind in cases:
        m = pick_model(q)
        is_fast = m.endswith("fast")
        ok = (kind == "fast" and is_fast) or (kind == "strong" and not is_fast)
        record(sect, f"router({q[:40]!r}) → {kind}",
               "PASS" if ok else "FAIL",
               f"got={m!r}")

    # 19b. Force-override env knob
    import os
    os.environ["MAXCODER_FORCE_MODEL"] = "test-override"
    try:
        # Re-import to pick up env change
        import importlib, core.model_router as mr
        importlib.reload(mr)
        m = mr.pick_model("anything")
        record(sect, "MAXCODER_FORCE_MODEL override works",
               "PASS" if m == "test-override" else "FAIL", f"got={m!r}")
    finally:
        del os.environ["MAXCODER_FORCE_MODEL"]
        importlib.reload(mr)

    # 19c. Response cache — miss, store, hit
    from core import response_cache as rc
    rc.clear()
    msgs = [{"role": "user", "content": "BENCH_TEST_CACHE_QUERY_xyz123"}]
    opts = {"temperature": 0.0}
    miss = rc.lookup(msgs, opts, "test-model")
    record(sect, "response_cache miss on first lookup",
           "PASS" if miss is None else "FAIL", f"got={miss!r}")

    rc.store(msgs, opts, "test-model", "the cached response")
    hit = rc.lookup(msgs, opts, "test-model")
    record(sect, "response_cache hit after store",
           "PASS" if hit == "the cached response" else "FAIL", f"got={hit!r}")

    # 19d. Different options → different cache key (NO false hit)
    diff_opts = {"temperature": 0.7}
    miss2 = rc.lookup(msgs, diff_opts, "test-model")
    record(sect, "response_cache distinguishes options",
           "PASS" if miss2 is None else "FAIL", f"got={miss2!r}")

    # 19e. Different model → different cache key
    miss3 = rc.lookup(msgs, opts, "other-model")
    record(sect, "response_cache distinguishes model",
           "PASS" if miss3 is None else "FAIL", f"got={miss3!r}")

    # 19f. Stats endpoint reports sensibly
    s = rc.stats()
    record(sect, "response_cache.stats() exposes hit/miss/hit_rate",
           "PASS" if {"hits","misses","hit_rate","enabled"} <= set(s.keys()) else "FAIL",
           f"got: {s}")
    rc.clear()

    # 19g. End-to-end: generate() returns from cache on second identical call
    if not skip:
        from core.generator import generate
        try:
            msgs_real = [{"role":"user", "content":"Reply with the single word PINEAPPLE."}]
            opts_real = {"temperature": 0.0, "num_predict": 10}
            t0 = time.time()
            r1 = await generate(msgs_real, model="maxcoder-fast", options=opts_real)
            dt1 = time.time() - t0
            t0 = time.time()
            r2 = await generate(msgs_real, model="maxcoder-fast", options=opts_real)
            dt2 = time.time() - t0
            # Same content, second should be drastically faster (cache hit)
            speedup = dt1 / max(dt2, 0.001)
            same = (r1.strip() == r2.strip())
            cached_fast = speedup >= 5    # cache hit should be at least 5× faster
            record(sect, f"generate() cache hit ({dt1:.2f}s → {dt2:.3f}s, {speedup:.0f}x)",
                   "PASS" if (same and cached_fast) else
                   ("WARN" if same else "FAIL"),
                   f"r1={r1[:40]!r} r2={r2[:40]!r}")
        except Exception as e:
            record(sect, "generate() cache hit", "FAIL", str(e))
    else:
        record(sect, "generate() cache hit test (skipped)", "WARN", "rerun without --skip-llm")


# ── Main ────────────────────────────────────────────────────────────────────
async def main():
    skip_nllb = "--skip-nllb" in sys.argv
    skip_llm  = "--skip-llm"  in sys.argv
    skip_net  = "--skip-net"  in sys.argv
    print(f"\nRunning benchmark (skip_nllb={skip_nllb}, skip_llm={skip_llm}, skip_net={skip_net})...\n")
    bench_routing()
    bench_translation_memory()
    bench_pdf()
    bench_sanitizer()
    await bench_nllb(skip=skip_nllb)
    await bench_full_pipeline(skip_nllb=skip_nllb)
    bench_tools()
    bench_file_parser()
    bench_executor()
    bench_memory()
    bench_chat_memory()
    bench_uncertainty()
    bench_rag()
    await bench_rewriter(skip=skip_llm)
    await bench_reasoner(skip=skip_llm)
    await bench_web(skip=skip_net)
    await bench_intelligence(skip=skip_llm)
    await bench_agent(skip=skip_llm)
    await bench_optimizations(skip=skip_llm)
    totals = _print_report()
    return 0 if totals["FAIL"] == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
