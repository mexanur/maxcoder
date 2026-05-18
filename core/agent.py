"""
Agent loop — multi-step plan→think→act→observe→reflect→repeat.

This is the agentic layer Claude Opus / Claude Code uses. The model picks
tools, sees results, picks the next tool, and keeps going until it has
enough information to answer — or hits a safety cap.

Public API:
    state = await run_agent(query, model="maxcoder")
    state.answer       — the final answer
    state.steps        — list[AgentStep] for transcript/UI
    state.usage_summary() — quick "ran 4 tools in 12s" string

The loop is built defensively:
  • Max steps (default 8) — never run forever
  • Repeated-action detection — if the same tool+args appears twice in a
    row, force a `finish` to break the loop
  • JSON-validation of the model's decisions — bad JSON gets one retry
    with a stricter reminder, then we fall back to summarizing what we
    have
  • Every step is timed and recorded — perfect for UI streaming
"""
from __future__ import annotations
import asyncio, json, re, time
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

from core.generator    import generate
from core.agent_tools  import TOOLS, dispatch, tools_for_prompt


# ── State ───────────────────────────────────────────────────────────────────
@dataclass
class AgentStep:
    kind:        str               # plan | thought | tool_call | observation | answer | error | reflect
    content:     str               = ""
    tool:        Optional[str]     = None
    args:        Optional[dict]    = None
    duration_s:  float             = 0.0

    def to_dict(self) -> dict:
        return {
            "kind": self.kind, "content": self.content,
            "tool": self.tool, "args": self.args,
            "duration_s": round(self.duration_s, 2),
        }


@dataclass
class AgentState:
    query:     str
    plan:      str         = ""
    steps:     list[AgentStep] = field(default_factory=list)
    answer:    str         = ""
    done:      bool        = False
    max_steps: int         = 8
    started:   float       = field(default_factory=time.time)

    def add(self, step: AgentStep) -> None:
        self.steps.append(step)

    @property
    def tool_calls(self) -> int:
        return sum(1 for s in self.steps if s.kind == "tool_call")

    def usage_summary(self) -> str:
        dt = time.time() - self.started
        return (f"ran {self.tool_calls} tool call(s) in {dt:.1f}s "
                f"across {len(self.steps)} step(s)")

    def to_dict(self) -> dict:
        return {
            "query": self.query, "plan": self.plan,
            "answer": self.answer, "done": self.done,
            "steps": [s.to_dict() for s in self.steps],
            "tool_calls": self.tool_calls,
            "elapsed_s": round(time.time() - self.started, 2),
        }


# ── Prompts ────────────────────────────────────────────────────────────────
# Reflection runs after every N successful tool calls to keep the agent
# on track. It's a brief check-in: "given what I've learned, am I still
# pursuing the right goal? Should I change strategy?" — modeled on the
# inner-loop reflection Opus/Claude Code does between tool invocations.
_REFLECT_SYSTEM = """You are the reflection component of an agentic assistant.

You've just completed a few tool calls. Briefly examine what you've learned
and decide whether to (a) continue with the current approach, (b) change
strategy, or (c) finish — you may already have enough information.

Output ONE SHORT PARAGRAPH (under 80 words, plain text — no JSON, no code
fences) covering:
  • What the observations tell us so far
  • Whether the current direction is working
  • What the next concrete step should be

Do NOT call any tools here. Do NOT output JSON. This reflection feeds into
your next decision step."""


_PLAN_SYSTEM = """You are the planning component of an agentic assistant.

The user has asked a question or given a task. Before any tool is called,
your job is to think about HOW to solve it. Output a numbered plan with
2-4 short steps describing what tools you'll likely need (read_file,
search_web, run_python, etc.) and what you expect each step to produce.

Output ONLY the plan, as plain text. No JSON. No code fences. No preamble.
Maximum 6 lines."""


_DECIDE_SYSTEM = """You are the action component of an agentic assistant.

You decide what tool to call next, ONE at a time. Output is a STRICT JSON
object — no markdown, no code fences, no prose, no commentary, no explanation.

═══════════════════════════════════════════════════════════════════════════
AVAILABLE TOOLS
═══════════════════════════════════════════════════════════════════════════
{tools_block}

═══════════════════════════════════════════════════════════════════════════
OUTPUT SCHEMA — copy this shape exactly
═══════════════════════════════════════════════════════════════════════════
{{"tool": "<tool_name>", "args": {{<tool args here>}}, "reasoning": "<short why>"}}

The three top-level keys MUST be: "tool", "args", "reasoning".
- "tool":      string — one of the tool names listed above
- "args":      object — keys match the tool's declared parameter names
- "reasoning": string — one short sentence explaining your choice

DO NOT use other key names like "action", "function", "name", "code",
"query" at the top level. ALL tool arguments go INSIDE the "args" object.

═══════════════════════════════════════════════════════════════════════════
COMPLETE EXAMPLES — these are the ONLY valid output formats
═══════════════════════════════════════════════════════════════════════════
Example 1 — calculate a number:
{{"tool": "run_python", "args": {{"code": "print(2**50)"}}, "reasoning": "Compute 2 to the 50."}}

Example 2 — look up information online:
{{"tool": "search_web", "args": {{"query": "current bitcoin price USD"}}, "reasoning": "Need live price."}}

Example 3 — read a file:
{{"tool": "read_file", "args": {{"rel_path": "README.md"}}, "reasoning": "Check the project description."}}

Example 4 — finish the task:
{{"tool": "finish", "args": {{"answer": "The result of 2^50 is 1125899906842624."}}, "reasoning": "I have the answer."}}

═══════════════════════════════════════════════════════════════════════════
RULES
═══════════════════════════════════════════════════════════════════════════
1. Output ONE JSON object on ONE line. Nothing before, nothing after.
2. NO code fences (no triple backticks). NO ```json blocks. Just raw JSON.
3. When you have enough info to answer, call `finish` with your full answer.
4. If a previous tool errored, try a DIFFERENT tool or different args.
5. Read OBSERVATIONS in the history below — if the answer is already there,
   immediately call `finish` instead of re-running tools.
"""


# ── Plan stage ─────────────────────────────────────────────────────────────
async def _plan(query: str, model: str) -> str:
    msgs = [
        {"role": "system", "content": _PLAN_SYSTEM},
        {"role": "user",   "content": query},
    ]
    try:
        return (await generate(
            msgs, model=model,
            options={"num_predict": 250, "temperature": 0.2, "num_ctx": 4096},
        )).strip()
    except Exception as e:
        return f"(planning failed: {e})"


# ── Decide stage ───────────────────────────────────────────────────────────
def _format_history(state: AgentState, max_obs_chars: int = 1200) -> str:
    """Render history for the decision prompt. Tool observations get truncated
    to keep the context window under control as the loop progresses."""
    lines = [f"USER QUERY: {state.query}", f"PLAN:\n{state.plan}", ""]
    for i, st in enumerate(state.steps, 1):
        if st.kind == "tool_call":
            args_repr = json.dumps(st.args, ensure_ascii=False)
            lines.append(f"--- Step {i}: TOOL {st.tool}({args_repr}) ---")
        elif st.kind == "observation":
            content = st.content
            if len(content) > max_obs_chars:
                content = content[:max_obs_chars] + f"\n... (truncated, {len(st.content)} chars total)"
            lines.append(f"OBSERVATION:\n{content}\n")
        elif st.kind == "reflect":
            lines.append(f"REFLECTION:\n{st.content}\n")
        elif st.kind == "error":
            lines.append(f"ERROR: {st.content}\n")
    lines.append("\nWhat is your next action? Reply with one JSON line.")
    return "\n".join(lines)


def _extract_json_object(text: str) -> Optional[dict]:
    """Extract the first balanced JSON object from text. Uses Python's
    JSONDecoder.raw_decode which handles trailing content and nested objects
    correctly — unlike a regex which would break on `{"a": {"b": 1}}`.
    """
    text = text.strip()
    if not text:
        return None
    # Find candidate start positions (every '{')
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[i:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None


def _normalize_action(parsed: dict) -> Optional[dict]:
    """Forgive common schema mistakes — small models often invent their own
    JSON shapes. We canonicalize to {"tool", "args", "reasoning"} from
    several known-bad variants.

    Accepts:
      • {"tool": ..., "args": {...}, "reasoning": ...}                ← canonical
      • {"action": "X", ...}             → tool=X, args=other-keys
      • {"name": "X", "parameters": {...}}                            → tool, args
      • {"function": "X", "arguments": {...}}                         → tool, args
      • {"tool": "X", "code": "..."}     → tool, args={code: ...}     (flat→packed)
      • {"tool": "X", "query": "..."}    → tool, args={query: ...}    (flat→packed)
    """
    if not isinstance(parsed, dict):
        return None

    tool = (parsed.get("tool") or parsed.get("action") or
             parsed.get("name") or parsed.get("function"))
    if not isinstance(tool, str) or not tool:
        return None

    args = (parsed.get("args") or parsed.get("parameters") or
             parsed.get("arguments") or parsed.get("input"))
    if not isinstance(args, dict):
        # Maybe args are flat at the top level — pack everything except the
        # known control keys into args. Common with small-model output like
        # {"action": "run_python", "code": "print(1)"}
        flat_args = {k: v for k, v in parsed.items()
                     if k not in {"tool", "action", "name", "function",
                                   "args", "parameters", "arguments", "input",
                                   "reasoning", "thought", "thoughts", "rationale"}}
        args = flat_args if flat_args else {}

    reasoning = (parsed.get("reasoning") or parsed.get("thought") or
                  parsed.get("thoughts") or parsed.get("rationale") or "")

    return {"tool": tool, "args": args, "reasoning": str(reasoning)}


async def _decide(state: AgentState, model: str) -> Optional[dict]:
    """Ask the model for the next action. Returns a parsed dict or None on
    unrecoverable parse failure."""
    system = _DECIDE_SYSTEM.format(tools_block=tools_for_prompt())
    user   = _format_history(state)
    msgs = [{"role": "system", "content": system},
            {"role": "user",   "content": user}]

    for attempt in range(2):
        try:
            raw = (await generate(
                msgs, model=model,
                options={"num_predict": 500, "temperature": 0.05, "num_ctx": 8192},
            )).strip()
        except Exception as e:
            state.add(AgentStep(kind="error", content=f"model call failed: {e}"))
            return None

        # Strip code fences if the model wrapped JSON in ```json ... ```
        raw_clean = re.sub(r"```(?:json)?\s*\n?", "", raw).replace("```", "")
        parsed = _extract_json_object(raw_clean)
        if parsed is None:
            if attempt == 0:
                msgs.append({"role": "assistant", "content": raw})
                msgs.append({"role": "user",
                              "content": ('Your output was not parseable JSON. Reply with EXACTLY '
                                          'one JSON object: {"tool": "<name>", "args": {...}, "reasoning": "..."}')})
                continue
            return None

        action = _normalize_action(parsed)
        if action is None:
            if attempt == 0:
                msgs.append({"role": "assistant", "content": raw})
                msgs.append({"role": "user",
                              "content": ('Your JSON is missing the "tool" key. '
                                          'Reply with EXACTLY: '
                                          '{"tool": "<name>", "args": {...}, "reasoning": "..."}')})
                continue
            return None
        return action
    return None


# ── Reflection: brief mid-flight strategy check ─────────────────────────────
async def _reflect(state: AgentState, model: str) -> str:
    """Produce a short reflection on progress. Returns a plain-text paragraph
    that gets appended to history so the next decision step is informed by it."""
    msgs = [
        {"role": "system", "content": _REFLECT_SYSTEM},
        {"role": "user",   "content": _format_history(state, max_obs_chars=800)},
    ]
    try:
        out = (await generate(
            msgs, model=model,
            options={"num_predict": 180, "temperature": 0.2, "num_ctx": 8192},
        )).strip()
        # Strip any stray JSON / code fences the model might emit anyway
        out = re.sub(r"```[\s\S]*?```", "", out).strip()
        return out or "(no reflection)"
    except Exception as e:
        return f"(reflection failed: {e})"


# Tunable — after every N successful tool calls, do a reflection step.
_REFLECT_EVERY = 2


# ── Termination safety: detect a loop of identical tool calls ──────────────
def _is_repeat_loop(state: AgentState, lookback: int = 2) -> bool:
    """Detect if the same (tool, args) pair just repeated. Cuts off infinite
    loops where the model keeps re-trying the same failing tool."""
    tool_calls = [s for s in state.steps if s.kind == "tool_call"]
    if len(tool_calls) < lookback + 1:
        return False
    recent = tool_calls[-(lookback + 1):]
    signatures = {(s.tool, json.dumps(s.args, sort_keys=True)) for s in recent}
    return len(signatures) == 1   # all identical


# ── Forced-summary fallback when we hit max steps without `finish` ─────────
_SUMMARY_SYSTEM = """You are an agentic assistant that has been working on a task.
You've run several tools but haven't called `finish` yet, and you've hit your
step budget. Based on the OBSERVATIONS you've collected, produce the BEST
final answer you can to the user's original query.

Output plain text — your answer to the user. No JSON. No commentary about
hitting limits."""


async def _force_summary(state: AgentState, model: str) -> str:
    msgs = [
        {"role": "system", "content": _SUMMARY_SYSTEM},
        {"role": "user",   "content": _format_history(state)},
    ]
    try:
        return (await generate(
            msgs, model=model,
            options={"num_predict": 600, "temperature": 0.2, "num_ctx": 8192},
        )).strip()
    except Exception as e:
        return (f"I gathered some information but ran out of steps before I could "
                f"synthesize a complete answer. (summary failed: {e})")


# ── Main loop ──────────────────────────────────────────────────────────────
async def run_agent(query:     str,
                     model:     str = "maxcoder",
                     max_steps: int = 8) -> AgentState:
    """Run an agent on `query` and return the final state.

    The loop:
      1. Plan
      2. Loop until done or max_steps reached:
         a. Decide next tool
         b. If tool=='finish', record answer and exit
         c. Else dispatch tool, record observation
         d. Check for repeat-loop → force finish
      3. If we exited without finishing, force a summary from the collected
         observations.
    """
    state = AgentState(query=query, max_steps=max_steps)

    # Plan
    t0 = time.time()
    plan = await _plan(query, model)
    state.plan = plan
    state.add(AgentStep(kind="plan", content=plan, duration_s=time.time() - t0))

    # Tool loop
    while state.tool_calls < max_steps and not state.done:
        t0 = time.time()
        action = await _decide(state, model)
        if action is None:
            state.add(AgentStep(kind="error",
                                  content="model failed to produce a valid action",
                                  duration_s=time.time() - t0))
            break

        tool = action.get("tool", "")
        args = action.get("args", {}) or {}
        reasoning = action.get("reasoning", "")
        if reasoning:
            state.add(AgentStep(kind="thought", content=reasoning,
                                  duration_s=time.time() - t0))

        if tool == "finish":
            ans = (args.get("answer") or "").strip()
            if not ans:
                ans = "(empty answer)"
            state.answer = ans
            state.add(AgentStep(kind="answer", content=ans))
            state.done = True
            break

        if tool not in TOOLS:
            state.add(AgentStep(kind="error",
                                  content=f"unknown tool {tool!r}"))
            continue

        # Dispatch
        state.add(AgentStep(kind="tool_call", tool=tool, args=args))
        t1 = time.time()
        result = await dispatch(tool, args)
        state.add(AgentStep(kind="observation", content=result,
                              tool=tool, duration_s=time.time() - t1))

        # Loop guard — same tool+args twice in a row → force finish
        if _is_repeat_loop(state):
            state.add(AgentStep(kind="reflect",
                                  content="repeat-action loop detected — forcing summary"))
            break

        # Reflection — every N tool calls, take stock of progress. The
        # reflection is added to history so the next decide() sees it.
        if (state.tool_calls > 0 and state.tool_calls % _REFLECT_EVERY == 0
                and state.tool_calls < max_steps):
            t2 = time.time()
            reflection = await _reflect(state, model)
            state.add(AgentStep(kind="reflect", content=reflection,
                                  duration_s=time.time() - t2))

    # Fall-through summary if we never called finish
    if not state.done:
        ans = await _force_summary(state, model)
        state.answer = ans
        state.add(AgentStep(kind="answer", content=ans))
        state.done = True

    return state


# ── Streaming variant (for UIs that want per-step events) ──────────────────
async def run_agent_stream(query:     str,
                            model:     str = "maxcoder",
                            max_steps: int = 8) -> AsyncIterator[dict]:
    """Same as run_agent but yields each step as a dict for live display.

    Yields events of shape:
        {"event": "plan"|"thought"|"tool_call"|"observation"|"answer"|"error"|"done",
         "content": str, "tool": str?, "args": dict?, "duration_s": float?}
    """
    # Re-implement run loop here so we can yield in the middle. Reuses helpers.
    state = AgentState(query=query, max_steps=max_steps)

    t0 = time.time()
    plan = await _plan(query, model)
    state.plan = plan
    state.add(AgentStep(kind="plan", content=plan, duration_s=time.time() - t0))
    yield {"event": "plan", "content": plan, "duration_s": time.time() - t0}

    while state.tool_calls < max_steps and not state.done:
        action = await _decide(state, model)
        if action is None:
            yield {"event": "error", "content": "model failed to produce a valid action"}
            state.add(AgentStep(kind="error", content="invalid action"))
            break

        tool = action.get("tool", "")
        args = action.get("args", {}) or {}
        reasoning = action.get("reasoning", "")
        if reasoning:
            state.add(AgentStep(kind="thought", content=reasoning))
            yield {"event": "thought", "content": reasoning}

        if tool == "finish":
            ans = (action.get("args") or {}).get("answer", "").strip() or "(empty)"
            state.answer = ans
            state.add(AgentStep(kind="answer", content=ans))
            state.done = True
            yield {"event": "answer", "content": ans}
            break

        if tool not in TOOLS:
            state.add(AgentStep(kind="error", content=f"unknown tool {tool!r}"))
            yield {"event": "error", "content": f"unknown tool {tool!r}"}
            continue

        state.add(AgentStep(kind="tool_call", tool=tool, args=args))
        yield {"event": "tool_call", "tool": tool, "args": args}

        t1 = time.time()
        result = await dispatch(tool, args)
        dt = time.time() - t1
        state.add(AgentStep(kind="observation", content=result,
                              tool=tool, duration_s=dt))
        yield {"event": "observation", "tool": tool, "content": result, "duration_s": dt}

        if _is_repeat_loop(state):
            state.add(AgentStep(kind="reflect", content="repeat loop — forcing summary"))
            yield {"event": "reflect", "content": "repeat-action loop detected — forcing summary"}
            break

        # Reflection every N tool calls — stream as its own event
        if (state.tool_calls > 0 and state.tool_calls % _REFLECT_EVERY == 0
                and state.tool_calls < max_steps):
            t2 = time.time()
            reflection = await _reflect(state, model)
            state.add(AgentStep(kind="reflect", content=reflection,
                                  duration_s=time.time() - t2))
            yield {"event": "reflect", "content": reflection,
                   "duration_s": time.time() - t2}

    if not state.done:
        ans = await _force_summary(state, model)
        state.answer = ans
        state.add(AgentStep(kind="answer", content=ans))
        state.done = True
        yield {"event": "answer", "content": ans, "forced": True}

    yield {"event": "done", "summary": state.usage_summary(),
           "tool_calls": state.tool_calls,
           "elapsed_s": round(time.time() - state.started, 2)}
