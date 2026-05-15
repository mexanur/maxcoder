"""Unit-test the hedge detector + verbalize_confidence helpers."""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.uncertainty import detect_hedges, verbalize_confidence, assess

# ── 1) Hedge detector tests ─────────────────────────────────────────────────
print("─── Hedge detection ───")
samples = [
    ("Confident",     "Use slicing with step -1: s[::-1]. Done."),
    ("Mild hedge",    "Probably this could be the cause. Likely a config issue."),
    ("Heavy hedge",   "I'm not sure but I believe it may not exist. Without more context, I cannot confirm."),
    ("Verify hint",   "You should check the documentation for the exact API."),
    ("Mixed",         "I think this is probably right, but you should verify it in the docs."),
]
for name, text in samples:
    r = detect_hedges(text)
    print(f"  {name:14} score={r['score']:>2}  verify={str(r['verify_suggested']):>5}  matches={len(r['matches'])}")

# ── 2) Verbalize confidence test (uses LLM) ────────────────────────────────
print("\n─── Verbalize confidence (uses qwen2.5-coder:3b) ───")
async def run_verbalize():
    for name, text in [
        ("Sure answer",   "To reverse a string in Python use slicing: `s[::-1]`. This is a standard Python idiom."),
        ("Made-up API",   "Use the `fooBarLib.async_handler()` method which manages concurrent operations through an internal event loop."),
    ]:
        r = await verbalize_confidence(text)
        print(f"  {name:14}  {r['level']:8}  {r['reason'][:80]}")

asyncio.run(run_verbalize())

# ── 3) Full assessment test ────────────────────────────────────────────────
print("\n─── Full assessment (hedge + verbalize) ───")
async def run_assess():
    for name, text in [
        ("Solid answer",   "FastAPI provides CORS middleware via `from fastapi.middleware.cors import CORSMiddleware`."),
        ("Uncertain answer", "I think the SuperFastLib.foo() method might be what you need, but I'm not entirely sure."),
    ]:
        r = await assess(text)
        print(f"  {name:16}  level={r.level:7}  hedge_score={r.hedge_score:>2}  badge={r.show_badge}  web={r.suggest_web}")

asyncio.run(run_assess())
