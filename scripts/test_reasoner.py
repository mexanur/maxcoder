"""End-to-end test of the MaxThink reasoning pipeline (streaming-aware)."""
import json, sys, time, urllib.request

REQ = {
    "messages": [{"role": "user", "content": "Why does my useEffect fire twice in development?"}],
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
print("Streaming MaxThink pipeline...\n", flush=True)
with urllib.request.urlopen(req, timeout=600) as resp:
    answer_chars = 0
    thinking_chars = 0
    last_print_t = 0
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
            print(f"[{elapsed:6.1f}s] CLASSIFY  task={ev.get('task_type')}", flush=True)
        elif kind == "plan":
            print(f"[{elapsed:6.1f}s] PLAN  ({len(ev.get('content',''))} chars)", flush=True)
        elif kind == "thinking_start":
            print(f"[{elapsed:6.1f}s] THINKING_START", flush=True)
        elif kind == "thinking_chunk":
            thinking_chars += len(ev.get("content", ""))
            # Print progress every ~2 seconds
            if elapsed - last_print_t > 2:
                print(f"[{elapsed:6.1f}s] thinking... {thinking_chars} chars", flush=True)
                last_print_t = elapsed
        elif kind == "thinking_done":
            print(f"[{elapsed:6.1f}s] THINKING_DONE  ({len(ev.get('content',''))} chars)", flush=True)
        elif kind == "answer_chunk":
            answer_chars += len(ev.get("content", ""))
            if elapsed - last_print_t > 2:
                print(f"[{elapsed:6.1f}s] answering... {answer_chars} chars", flush=True)
                last_print_t = elapsed
        elif kind == "done":
            result = ev.get("result", {})
            print(f"[{elapsed:6.1f}s] DONE  answer={len(result.get('answer',''))} chars", flush=True)
            print("\n--- FINAL ANSWER ---")
            print(result.get("answer", "")[:1200])

print(f"\nTotal time: {time.time()-t0:.1f}s", flush=True)
