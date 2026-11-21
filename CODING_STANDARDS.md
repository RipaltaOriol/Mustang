# Coding standards

## Comments and docstrings

Names, types and tests carry the meaning. A comment or docstring first passes the three tests in [CLAUDE.md](CLAUDE.md#comments-and-docstrings); this section is the shape it then takes.

### Comments

A comment is one line, and one of two kinds:

- a **pointer** to where the reason lives: `# See docs/adr/0063-a-bar-is-judged-by-how-much-of-its-window-it-missed.md`
- a **constraint** no name or test can carry: `# A 100%-off code is how free Paid access is given.`

Pragmas (`# noqa`, `# type: ignore`, `# pragma: no cover`, `# fmt: off`, a shebang, a coding line) are tooling, not comments, and sit outside this rule. So does a comment at the end of a line of code, which stays one line by construction.

### Docstrings

A docstring opens with `"""` on its own line, and is built from these parts only, in this order:

```python
"""
Return the Stripe event a webhook body carries, once its signature checks out.

Raises:
    WebhookSignatureError: the signature is missing, stale or does not match.

See: docs/adr/0057-stripe-managed-payments-is-the-source-of-truth.md
"""
```

- **Summary**, required: up to two lines naming what the module, class or function is or does, in [GLOSSARY](GLOSSARY.md) words.
- **`Raises:`**, optional: one line per exception the caller should handle, `Name: reason`.
- **`See:`**, optional: one doc or ADR path, nothing else on the line.

### Existing code

Comments and docstrings already committed keep their shape. When you reword one, bring that one to this shape. Leave the rest as they are.

## Research scripts

A research script is a `# %%` Python file in `research/`, run cell by cell in an Interactive Window. Scripts save no outputs, which keeps licensed vendor data out of this public repo, so `.ipynb` files stay out too.

**What goes where:**

- A script holds the sequence of steps and the tables and charts that show their results.
- `src/` holds, with tests, any rule that would silently corrupt a result if wrong. A cell calls it.
- New research logic starts in a script. Promote it to `src/` with tests once a second script needs it or a result depends on it.

**Shape:**

- Name the file `research/<topic>.py`, using GLOSSARY words where they fit. A new script adds no GLOSSARY entry.
- Give each step its own cell, ending on the frame it made so the cell displays it.
- Put parameters in the first code cell after the imports, including `SAVE = False`.
- Write outputs only in the last cell, behind `if SAVE:`. Outputs go to the git-ignored `data/processed/`.
- Call a dataset's check function before saving it. Tests cover the functions in `src/` and not the order of the cells, so the check is what guards the sequence.
- Import with `from src...` and run on the `.venv` kernel. `uv sync` installs the project there, so this works from any folder; another kernel fails with `No module named 'src'`.

**Markdown cells:** `# %% [markdown]` (optional) cells that run up to two lines, as the exception to the comment rules above. Use them to record what a cell shows and what it concludes, in GLOSSARY words. Comments in code cells follow the rules above.
