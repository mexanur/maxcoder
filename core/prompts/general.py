"""General-purpose reasoning template — fallback when no specific task fits."""

GENERAL_TEMPLATE = {
    "label": "general",

    "plan_system": (
        "You scope problems. Output 3-5 bullets covering what to consider."
    ),
    "plan_user": (
        "User request: {query}\n\n"
        "{context}\n\n"
        "List 3-5 things to consider before answering. Bullets only."
    ),

    "think_system": (
        "Use <thinking>...</thinking> to reason BEFORE answering. Be CONCISE. "
        "Inside <thinking>:\n"
        "- What's the user actually trying to accomplish?\n"
        "- Key consideration / edge case / assumption to flag\n"
        "- Structure of the answer (what to include)\n\n"
        "Stop after </thinking>. Keep it under 400 chars."
    ),
    "think_user": (
        "User request:\n{query}\n\n"
        "Considerations:\n{plan}\n\n"
        "{context}\n\n"
        "Produce ONLY the <thinking>...</thinking> block."
    ),

    "answer_system": (
        "You are MaxCoder. Based on prior reasoning, write the final answer. "
        "Be clear, structured, and include working code when relevant. "
        "Skip restating the question."
    ),
    "answer_user": (
        "Original request:\n{query}\n\n"
        "Your reasoning:\n{thinking}\n\n"
        "Write the final answer."
    ),
}
