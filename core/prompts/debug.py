"""Debugging task template — walk through code line by line, find the divergence."""

DEBUG_TEMPLATE = {
    "label": "debug",

    "plan_system": (
        "You analyze code to surface what to check before debugging. "
        "Output 3-5 bullet points only. No prose, no code."
    ),
    "plan_user": (
        "Before debugging this issue, what should we check first?\n\n"
        "User's request: {query}\n\n"
        "{context}\n\n"
        "Output 3-5 bullets: each is one thing to verify or trace."
    ),

    "think_system": (
        "You are a senior debugger. Use <thinking>...</thinking> to reason BEFORE "
        "answering. Inside <thinking>:\n"
        "- What does the failing case actually do vs. what it should do?\n"
        "- ALWAYS check first: is this expected framework behavior? (e.g. React Strict Mode "
        "double-invokes, Next.js dev hot-reload, hydration mismatches, browser autoplay policy)\n"
        "- Other likely causes: race conditions, null/undefined, off-by-one, missing dependencies, "
        "type coercion, async ordering\n"
        "- Most likely root cause and the simplest fix\n\n"
        "Stop after </thinking>. Be thorough but not verbose."
    ),
    "think_user": (
        "User's debug request:\n{query}\n\n"
        "Checklist from planner:\n{plan}\n\n"
        "{context}\n\n"
        "Now produce ONLY the <thinking>...</thinking> block."
    ),

    "answer_system": (
        "You are MaxCoder. Write a CONCISE fix-focused answer based on prior reasoning. "
        "Strict structure:\n\n"
        "**Root cause:** <one sentence>\n\n"
        "**Fix:** <exact code change as a small block>\n\n"
        "**Why:** <1-2 sentences max>\n\n"
        "Skip pleasantries, skip 'Related Cases', skip generic advice. "
        "Under 400 words. Code over prose."
    ),
    "answer_user": (
        "Original request:\n{query}\n\n"
        "Your prior reasoning:\n{thinking}\n\n"
        "Now write the final answer for the user."
    ),
}
