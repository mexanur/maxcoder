"""Per-task thinking templates for the MaxThink reasoning pipeline.

Each template provides three prompts:
  plan_prompt(query, context)    → asked to a fast model, returns a bullet plan
  think_prompt(query, plan, ctx) → asked to a strong model, returns <thinking>
  answer_prompt(query, thinking) → asked to a strong model, returns final answer

Task types are detected by `classify()` in core/reasoner.py.
"""
from .debug    import DEBUG_TEMPLATE
from .design   import DESIGN_TEMPLATE
from .sql_perf import SQL_PERF_TEMPLATE
from .refactor import REFACTOR_TEMPLATE
from .general  import GENERAL_TEMPLATE

TEMPLATES = {
    "debug":     DEBUG_TEMPLATE,
    "design":    DESIGN_TEMPLATE,
    "sql_perf":  SQL_PERF_TEMPLATE,
    "refactor":  REFACTOR_TEMPLATE,
    "general":   GENERAL_TEMPLATE,
}
