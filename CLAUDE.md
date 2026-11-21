This repository is a quantitative finance research factory. The aim is to develop and explore research trading ideas and hypotheses.

## Comments and docstrings

Names, types and tests carry the meaning. A comment or docstring you write passes all three tests:

1. Removing it would make the code materially harder to understand or maintain.
2. No name, structure, type or test could say it as clearly.
3. It records a real constraint or a deliberate decision.

Its shape (one-line comments, the docstring template) → [CODING_STANDARDS.md](CODING_STANDARDS.md).

A gap, workaround or unfinished case goes in your final report to the user, or in a GitHub issue.


## Research scripts

Building or exploring a Panel, a Signal, a table or a chart happens in a `# %%` script in `research/`. Reusable logic lives in `src/` with tests. Writing or changing either → [CODING_STANDARDS.md](CODING_STANDARDS.md#research-scripts).


## Agent skills

- **Issue tracker** — GitHub issues in `RipaltaOriol/Mustang` via `gh`: [docs/agents/issue-tracker.md](docs/agents/issue-tracker.md)
- **Triage labels** — the five canonical roles: [docs/agents/triage-labels.md](docs/agents/triage-labels.md)
- **Domain docs** — `GLOSSARY.md` + `docs/adr/`: [docs/agents/domain.md](docs/agents/domain.md)
