"""
Generate LoRA training data for the MaxCoder Agent format.

Produces JSONL pairs of (instruction, output) where output contains
the @@CREATE / @@EDIT / @@DELETE / @@RUN structured commands.

Usage:
    python training/generate_agent_data.py --out training/agent_data.jsonl

Then fine-tune:
    python training/finetune_lora.py \
        --data training/agent_data.jsonl \
        --base unsloth/Qwen2.5-Coder-7B-Instruct-bnb-4bit \
        --out  training/maxcoder-agent-lora
"""
from __future__ import annotations

import json, argparse, pathlib

# ── Training examples ─────────────────────────────────────────────────────────
# Each example: (project_snapshot, user_request, expected_output)
# Add as many as you like — more = better agent reliability on 7B models.

EXAMPLES: list[dict] = [

  # ── 1. Empty project ────────────────────────────────────────────────────────
  {
    "snapshot": "(empty project — no files yet)",
    "request":  "Build a simple FastAPI hello world app with a /health endpoint.",
    "output": """@@CREATE main.py
```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def root():
    return {"message": "Hello, World!"}

@app.get("/health")
def health():
    return {"status": "ok"}
```

@@CREATE requirements.txt
```text
fastapi>=0.115.2
uvicorn[standard]==0.30.6
```

I created two files:
- `main.py` — FastAPI app with `/` and `/health` endpoints.
- `requirements.txt` — pinned dependencies.

Install & run:
```bash
pip install -r requirements.txt
uvicorn main:app --reload
```
"""
  },

  # ── 2. Edit existing file ────────────────────────────────────────────────────
  {
    "snapshot": """RELEVANT PROJECT FILES:

=== main.py ===
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def root():
    return {"message": "Hello"}
""",
    "request": "Add a POST /echo endpoint that returns whatever JSON body is sent.",
    "output": """@@EDIT main.py
```python
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any

app = FastAPI()

class EchoBody(BaseModel):
    data: Any

@app.get("/")
def root():
    return {"message": "Hello"}

@app.post("/echo")
def echo(body: EchoBody):
    return {"echoed": body.data}
```

I edited `main.py` to add a `POST /echo` endpoint using a Pydantic model for the request body.
"""
  },

  # ── 3. Multi-file project ───────────────────────────────────────────────────
  {
    "snapshot": """RELEVANT PROJECT FILES:

=== index.html ===
<!DOCTYPE html>
<html>
<head><title>My Site</title></head>
<body><h1>Hello</h1></body>
</html>
""",
    "request": "Add a dark mode stylesheet and link it in the HTML.",
    "output": """@@CREATE style.css
```css
:root {
  --bg: #0f1117;
  --text: #e2e8f0;
}

body {
  background: var(--bg);
  color: var(--text);
  font-family: system-ui, sans-serif;
  margin: 0;
  padding: 2rem;
}

h1 { color: #7c8aff; }
```

@@EDIT index.html
```html
<!DOCTYPE html>
<html>
<head>
  <title>My Site</title>
  <link rel="stylesheet" href="style.css"/>
</head>
<body><h1>Hello</h1></body>
</html>
```

I created `style.css` with a dark theme using CSS variables, then edited `index.html` to link it.
"""
  },

  # ── 4. Delete a file ────────────────────────────────────────────────────────
  {
    "snapshot": """RELEVANT PROJECT FILES:

=== app.py ===
# main app

=== debug.py ===
# temporary debug file — remove before deploy
import pdb; pdb.set_trace()
""",
    "request": "Remove the debug file.",
    "output": """@@DELETE debug.py

Deleted `debug.py` — it was a temporary debugging file not needed in production.
"""
  },

  # ── 5. Create + Run ─────────────────────────────────────────────────────────
  {
    "snapshot": "(empty project — no files yet)",
    "request":  "Write a Python script that prints the first 10 Fibonacci numbers and run it.",
    "output": """@@CREATE fib.py
```python
def fibonacci(n: int) -> list[int]:
    seq = [0, 1]
    for _ in range(n - 2):
        seq.append(seq[-1] + seq[-2])
    return seq[:n]

if __name__ == "__main__":
    for i, num in enumerate(fibonacci(10)):
        print(f"fib({i}) = {num}")
```

@@RUN python
```python
def fibonacci(n: int) -> list[int]:
    seq = [0, 1]
    for _ in range(n - 2):
        seq.append(seq[-1] + seq[-2])
    return seq[:n]

for i, num in enumerate(fibonacci(10)):
    print(f"fib({i}) = {num}")
```

Created `fib.py` and ran it to verify the output.
"""
  },

  # ── 6. SQL schema + seed ────────────────────────────────────────────────────
  {
    "snapshot": "(empty project — no files yet)",
    "request":  "Create a SQLite schema for a todo app with users and tasks tables.",
    "output": """@@CREATE schema.sql
```sql
CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT    NOT NULL UNIQUE,
    email      TEXT    NOT NULL UNIQUE,
    created_at TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       TEXT    NOT NULL,
    done        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id);
```

@@CREATE seed.sql
```sql
INSERT INTO users (username, email) VALUES
    ('alice', 'alice@example.com'),
    ('bob',   'bob@example.com');

INSERT INTO tasks (user_id, title) VALUES
    (1, 'Buy groceries'),
    (1, 'Write tests'),
    (2, 'Deploy to prod');
```

Created `schema.sql` (DDL) and `seed.sql` (sample data). Run against SQLite:
```bash
sqlite3 todo.db < schema.sql
sqlite3 todo.db < seed.sql
```
"""
  },

  # ── 7. Refactor ─────────────────────────────────────────────────────────────
  {
    "snapshot": """RELEVANT PROJECT FILES:

=== utils.py ===
def add(a, b):
    return a + b

def sub(a, b):
    return a - b

def mul(a, b):
    return a * b

def div(a, b):
    return a / b
""",
    "request": "Add type annotations and docstrings to all functions in utils.py.",
    "output": """@@EDIT utils.py
```python
"""Utility math functions."""


def add(a: float, b: float) -> float:
    """Return the sum of a and b."""
    return a + b


def sub(a: float, b: float) -> float:
    """Return a minus b."""
    return a - b


def mul(a: float, b: float) -> float:
    """Return the product of a and b."""
    return a * b


def div(a: float, b: float) -> float:
    """Return a divided by b. Raises ZeroDivisionError if b is 0."""
    if b == 0:
        raise ZeroDivisionError("Cannot divide by zero.")
    return a / b
```

Edited `utils.py`: added type annotations, docstrings, and a zero-division guard in `div()`.
"""
  },

  # ── 8. React component ──────────────────────────────────────────────────────
  {
    "snapshot": "(empty project — no files yet)",
    "request":  "Create a React counter component with increment, decrement and reset buttons.",
    "output": """@@CREATE Counter.jsx
```jsx
import { useState } from 'react'

export default function Counter({ initial = 0 }) {
  const [count, setCount] = useState(initial)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
      <h2 style={{ fontSize: '3rem', margin: 0 }}>{count}</h2>
      <div style={{ display: 'flex', gap: 8 }}>
        <button onClick={() => setCount(c => c - 1)}>−</button>
        <button onClick={() => setCount(initial)}>Reset</button>
        <button onClick={() => setCount(c => c + 1)}>+</button>
      </div>
    </div>
  )
}
```

Created `Counter.jsx` — a controlled React counter with increment, decrement, and reset.
Usage: `<Counter initial={0} />`
"""
  },
]


def build_instruction(snapshot: str, request: str) -> str:
    return (
        "You are MaxCoder Agent. You directly read and write project files.\n\n"
        f"CURRENT PROJECT FILES:\n{snapshot}\n\n"
        f"User: {request}"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="training/agent_data.jsonl")
    ap.add_argument("--augment", action="store_true",
                    help="Augment with slight variations (doubles dataset size)")
    args = ap.parse_args()

    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    records = []
    for ex in EXAMPLES:
        records.append({
            "instruction": build_instruction(ex["snapshot"], ex["request"]),
            "output":      ex["output"].strip(),
        })

    if args.augment:
        import copy, random
        augmented = []
        phrasings = [
            lambda r: r,
            lambda r: r.rstrip(".") + ", please.",
            lambda r: "Can you " + r[0].lower() + r[1:],
            lambda r: "Please " + r[0].lower() + r[1:],
        ]
        for rec in records:
            for fn in phrasings[1:]:  # skip identity
                new = copy.deepcopy(rec)
                # Only rephrase the last line (the user request part)
                lines = new["instruction"].split("\n")
                lines[-1] = "User: " + fn(lines[-1].replace("User: ", ""))
                new["instruction"] = "\n".join(lines)
                augmented.append(new)
        records += augmented
        random.shuffle(records)

    with open(out_path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"✅  Written {len(records)} training examples to {out_path}")
    print(f"\nNext steps:")
    print(f"  python training/finetune_lora.py \\")
    print(f"      --data {out_path} \\")
    print(f"      --base unsloth/Qwen2.5-Coder-7B-Instruct-bnb-4bit \\")
    print(f"      --out  training/maxcoder-agent-lora")


if __name__ == "__main__":
    main()
