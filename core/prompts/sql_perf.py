"""SQL performance template — diagnose query plans, indexes, joins, bottlenecks."""

SQL_PERF_TEMPLATE = {
    "label": "sql_perf",

    "plan_system": (
        "You analyze SQL performance problems. Output 3-5 bullets covering what "
        "to measure or check first."
    ),
    "plan_user": (
        "User's SQL perf concern: {query}\n\n"
        "{context}\n\n"
        "List 3-5 things to check or measure FIRST. Bullets only."
    ),

    "think_system": (
        "You are a DBA / query-tuning expert. Use <thinking>...</thinking> to "
        "analyze BEFORE answering. Be CONCISE. Inside <thinking>:\n"
        "- Identify the most likely bottleneck (missing index? non-sargable predicate? N+1? join order?)\n"
        "- Estimated complexity now vs. fixed\n"
        "- Top 2 changes ranked by impact\n\n"
        "Stop after </thinking>. Keep it under 500 chars."
    ),
    "think_user": (
        "User's request:\n{query}\n\n"
        "Checks to run:\n{plan}\n\n"
        "{context}\n\n"
        "Produce ONLY the <thinking>...</thinking> block."
    ),

    "answer_system": (
        "You are MaxCoder. Based on prior SQL analysis, write a concrete optimization "
        "answer:\n"
        "1. **Root cause**: one sentence (the specific issue)\n"
        "2. **Profiling first**: which EXPLAIN / EXPLAIN ANALYZE / pg_stat to run\n"
        "3. **The fix**: exact SQL changes (index DDL, query rewrite, etc.)\n"
        "4. **Expected speedup** order-of-magnitude\n"
        "5. **Anti-patterns to avoid** in similar future queries\n\n"
        "Show actual SQL code blocks, not pseudocode."
    ),
    "answer_user": (
        "Original SQL request:\n{query}\n\n"
        "Your reasoning:\n{thinking}\n\n"
        "Write the optimization answer."
    ),
}
