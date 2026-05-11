"""
MaxCoder Evaluation Runner.

Usage:
    python eval/run_eval.py                         # all prompts, default model
    python eval/run_eval.py --model maxcoder        # quality model
    python eval/run_eval.py --ids py_001 py_002     # specific prompts
    python eval/run_eval.py --out eval/results/     # custom output dir

Results saved as:
    eval/results/YYYY-MM-DD_HH-MM_<model>.jsonl    # raw scores
    eval/results/YYYY-MM-DD_HH-MM_<model>.md       # human-readable report
"""
from __future__ import annotations
import sys, os, asyncio, json, time, argparse, pathlib, datetime
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import httpx
from core.eval import score_response, EvalResult

BACKEND = os.getenv("MAXCODER_BACKEND", "http://127.0.0.1:8000")


async def call_model(prompt: str, model: str) -> tuple[str, float, int]:
    """Call the backend and return (response_text, latency_s, approx_token_count)."""
    msgs = [{"role": "user", "content": prompt}]
    payload = {
        "messages": msgs, "model": model,
        "use_rag": False, "use_memory": False,
        "use_rewriter": False, "use_critic": False,
    }
    t0  = time.perf_counter()
    buf = ""
    async with httpx.AsyncClient(timeout=None) as c:
        async with c.stream("POST", f"{BACKEND}/chat", json=payload) as r:
            async for chunk in r.aiter_text():
                buf += chunk
    latency = time.perf_counter() - t0
    tokens  = len(buf.split())   # rough estimate
    return buf, latency, tokens


def load_prompts(ids: list[str] | None = None) -> list[dict]:
    p = pathlib.Path(__file__).parent / "prompts.jsonl"
    prompts = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    if ids:
        prompts = [p for p in prompts if p["id"] in ids]
    return prompts


def make_report(results: list[EvalResult], model: str) -> str:
    lines = [
        f"# MaxCoder Eval Report",
        f"**Model:** `{model}`  ",
        f"**Date:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}  ",
        f"**Prompts:** {len(results)}",
        "",
        "## Summary",
        "",
        "| Metric | Score |",
        "|---|---|",
    ]

    def avg(attr): return round(sum(getattr(r, attr) for r in results) / len(results), 3)

    lines += [
        f"| Overall | **{avg('overall')}** |",
        f"| Correctness | {avg('correctness')} |",
        f"| Completeness | {avg('completeness')} |",
        f"| Code Quality | {avg('code_quality')} |",
        f"| Instruction Follow | {avg('instruction_follow')} |",
        f"| Avg Latency | {avg('latency_s')}s |",
        f"| Avg Tokens/sec | {avg('tokens_per_sec')} |",
        "",
        "## Per-Prompt Results",
        "",
        "| ID | Prompt | Overall | Correct | Complete | Quality | CoT | Latency |",
        "|---|---|---|---|---|---|---|---|",
    ]

    for r in results:
        prompt_short = r.prompt[:55] + "..." if len(r.prompt) > 55 else r.prompt
        lines.append(
            f"| {r.prompt_id} | {prompt_short} | **{r.overall}** | "
            f"{r.correctness} | {r.completeness} | {r.code_quality} | "
            f"{r.instruction_follow} | {r.latency_s}s |"
        )

    lines += ["", "## Detailed Notes", ""]
    for r in results:
        lines.append(f"### {r.prompt_id}")
        lines.append(f"**Prompt:** {r.prompt}")
        for i, note in enumerate(r.notes):
            labels = ["Correctness","Completeness","Code Quality","CoT Structure"]
            lines.append(f"- **{labels[i]}:** {note}")
        lines.append("")

    return "\n".join(lines)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="maxcoder-fast")
    ap.add_argument("--ids",   nargs="*", default=None)
    ap.add_argument("--out",   default="eval/results")
    args = ap.parse_args()

    prompts = load_prompts(args.ids)
    if not prompts:
        print("No prompts found."); return

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp   = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
    jsonl_p = out_dir / f"{stamp}_{args.model}.jsonl"
    md_p    = out_dir / f"{stamp}_{args.model}.md"

    results: list[EvalResult] = []
    print(f"\n🔍 Running {len(prompts)} eval prompts on [{args.model}]\n")

    for i, p in enumerate(prompts, 1):
        print(f"  [{i}/{len(prompts)}] {p['id']} — {p['prompt'][:60]}...")
        try:
            response, latency, tokens = await call_model(p["prompt"], args.model)
            result = await score_response(
                prompt_id         = p["id"],
                prompt            = p["prompt"],
                response          = response,
                model             = args.model,
                lang              = p.get("lang", "python"),
                required_keywords = p.get("required", []),
                latency_s         = latency,
                token_count       = tokens,
            )
        except Exception as e:
            print(f"    ⚠️  Error: {e}")
            continue

        results.append(result)
        bar = "█" * int(result.overall * 20) + "░" * (20 - int(result.overall * 20))
        print(f"    Overall: {result.overall:.3f} [{bar}]  "
              f"Correct:{result.correctness}  "
              f"Latency:{result.latency_s}s")

    if not results:
        print("No results to save."); return

    # Save JSONL
    with open(jsonl_p, "w") as f:
        for r in results:
            f.write(json.dumps(r.to_dict()) + "\n")

    # Save Markdown report
    report = make_report(results, args.model)
    md_p.write_text(report, encoding="utf-8")

    # Print summary
    avg_overall = sum(r.overall for r in results) / len(results)
    print(f"\n{'='*55}")
    print(f"  ✅  Eval complete — {len(results)} prompts")
    print(f"  📊  Average overall score: {avg_overall:.3f} / 1.000")
    print(f"  📄  Report: {md_p}")
    print(f"  🗃️   Raw:    {jsonl_p}")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    asyncio.run(main())
