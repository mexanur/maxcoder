"""
Compare two eval result files side by side.
Usage:
    python eval/compare.py eval/results/file_a.jsonl eval/results/file_b.jsonl
"""
from __future__ import annotations
import sys, json, pathlib

def load(path: str) -> dict[str, dict]:
    results = {}
    for line in pathlib.Path(path).read_text().splitlines():
        if line.strip():
            d = json.loads(line)
            results[d["prompt_id"]] = d
    return results

def main():
    if len(sys.argv) < 3:
        print("Usage: python eval/compare.py file_a.jsonl file_b.jsonl")
        sys.exit(1)

    a = load(sys.argv[1])
    b = load(sys.argv[2])
    model_a = next(iter(a.values()))["model"]
    model_b = next(iter(b.values()))["model"]

    ids = sorted(set(a) | set(b))

    print(f"\n{'ID':<12} {'Metric':<22} {model_a:<20} {model_b:<20} {'Delta':>8}")
    print("─" * 85)

    metrics = ["overall","correctness","completeness","code_quality","instruction_follow"]
    totals  = {m: [0.0, 0.0, 0] for m in metrics}

    for pid in ids:
        if pid not in a or pid not in b:
            continue
        ra, rb = a[pid], b[pid]
        for m in metrics:
            va, vb = ra.get(m, 0), rb.get(m, 0)
            delta  = vb - va
            arrow  = "▲" if delta > 0.01 else ("▼" if delta < -0.01 else "=")
            print(f"{pid:<12} {m:<22} {va:<20.3f} {vb:<20.3f} {arrow}{delta:+.3f}")
            totals[m][0] += va
            totals[m][1] += vb
            totals[m][2] += 1

    print("─" * 85)
    print("AVERAGES")
    for m in metrics:
        va  = totals[m][0] / totals[m][2] if totals[m][2] else 0
        vb  = totals[m][1] / totals[m][2] if totals[m][2] else 0
        delta = vb - va
        arrow = "▲" if delta > 0.01 else ("▼" if delta < -0.01 else "=")
        print(f"{'':12} {m:<22} {va:<20.3f} {vb:<20.3f} {arrow}{delta:+.3f}")
    print()

if __name__ == "__main__":
    main()
