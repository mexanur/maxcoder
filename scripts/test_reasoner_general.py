"""Test the trivial/general-knowledge path: no reasoning, direct answer."""
import json, sys, time, urllib.request

REQ = {
    "messages": [{"role": "user", "content": "Why is Earth round but not flat?"}],
    "use_reasoning": True,
    "use_rag":        False,
    "use_memory":     False,
    "use_rewriter":   False,
    "use_web_search": False,
}

req = urllib.request.Request(
    "http://localhost:8000/chat",
    data=json.dumps(REQ).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)

t0 = time.time()
print("Testing general-knowledge query...\n", flush=True)
with urllib.request.urlopen(req, timeout=300) as resp:
    answer_chars = 0
    for raw in resp:
        line = raw.decode("utf-8", errors="ignore").strip()
        if not line.startswith("@@THINK_EVENT:"):
            continue
        try:
            ev = json.loads(line[len("@@THINK_EVENT:"):])
        except Exception:
            continue
        elapsed = time.time() - t0
        kind = ev.get("event")
        if kind == "classify":
            print(f"[{elapsed:5.1f}s] CLASSIFY  task={ev.get('task_type')}", flush=True)
        elif kind == "plan":
            print(f"[{elapsed:5.1f}s] PLAN  (UNEXPECTED — trivial path should skip plan!)", flush=True)
        elif kind == "thinking_done":
            print(f"[{elapsed:5.1f}s] THINKING_DONE  (UNEXPECTED — trivial path should skip thinking!)", flush=True)
        elif kind == "answer_chunk":
            answer_chars += len(ev.get("content", ""))
        elif kind == "done":
            result = ev.get("result", {})
            print(f"[{elapsed:5.1f}s] DONE  ({len(result.get('answer',''))} chars)", flush=True)
            print("\n--- ANSWER ---")
            print(result.get("answer", "")[:800])

print(f"\nTotal: {time.time()-t0:.1f}s", flush=True)
