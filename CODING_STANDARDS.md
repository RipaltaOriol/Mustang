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
