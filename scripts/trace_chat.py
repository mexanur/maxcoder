"""Trace EVERY line the backend streams to see what frontend should be receiving."""
import json, urllib.request, time

REQ = {
    "messages": [{"role": "user", "content": "Solve any 3 math problems and show each solved problem with one pdf file for each with explanation"}],
    "use_reasoning": False, "use_rag": True, "use_memory": True,
    "use_rewriter": True, "use_web_search": True,
}
req = urllib.request.Request(
    "http://127.0.0.1:8000/chat",
    data=json.dumps(REQ).encode("utf-8"),
    headers={"Content-Type": "application/json"}, method="POST",
)

print("Streaming raw lines from chat endpoint...\n")
t0 = time.time()
line_count = 0
skill_event_count = 0
generate_count = 0
with urllib.request.urlopen(req, timeout=600) as resp:
    buf = b""
    for raw in resp:
        buf += raw
        # Split into lines as bytes
        while b"\n" in buf:
            idx = buf.index(b"\n")
            line = buf[:idx].decode("utf-8", errors="ignore")
            buf = buf[idx+1:]
            line_count += 1
            elapsed = time.time() - t0

            # Categorize
            if line.startswith("@@SKILL_EVENT:"):
                skill_event_count += 1
                try:
                    ev = json.loads(line[len("@@SKILL_EVENT:"):])
                    c = ev.get("content", {})
                    stage = c.get("stage", "?")
                    # Truncate delta lines so we don't spam
                    if "delta" in c:
                        print(f"[{elapsed:5.1f}s] SKILL_EVENT stage={stage} delta={c['delta']!r}")
                    else:
                        print(f"[{elapsed:5.1f}s] SKILL_EVENT stage={stage} {json.dumps({k:v for k,v in c.items() if k not in ('skill','label','delta','tasks')})[:200]}")
                except Exception as e:
                    print(f"[{elapsed:5.1f}s] SKILL_EVENT PARSE FAIL: {line[:120]}")
            elif "@@GENERATE:" in line:
                generate_count += 1
                print(f"[{elapsed:5.1f}s] @@GENERATE start: {line[:80]}")
            elif line.strip() and not line.startswith("@@"):
                # Plain text content (preamble, tail, etc.)
                print(f"[{elapsed:5.1f}s] TEXT: {line[:80]!r}")

print(f"\n=== SUMMARY ===")
print(f"Total time:       {time.time()-t0:.1f}s")
print(f"Total lines:      {line_count}")
print(f"SKILL_EVENTs:     {skill_event_count}")
print(f"@@GENERATE blocks: {generate_count}")
