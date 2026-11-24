import inspect
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from src.signals import (
    LOOKBACK_EVENT_ACTIONS,
    LOOKBACK_EVENT_PREFIX,
    MISSING_REASONS,
    SIGNAL_COLUMNS,
    pct_shares_issued,
    rebalance_dates,
)

DOC = Path(__file__).parents[1] / "docs" / "signals" / "pct-shares-issued.tex"
DRIFT = f"{DOC.relative_to(DOC.parents[2])} no longer matches the code: update it, or fix the code if this change was unintended."
EXAMPLE_YEARS = {"Y1": "2001", "Y2": "2002"}
EVENT_COLUMNS = ["date", "permaticker", "ticker", "action", "value", "contra_ticker", "contra_name"]


def macro_calls(name, arity):
    """
    Return the first `arity` arguments of each `\\name{...}` call in the document. Arguments nest
    braces at most one level deep, so a regex can read them.
    """
    argument = r"\{((?:[^{}]|\{[^{}]*\})*)\}"
    pattern = re.compile(re.escape(f"\\{name}") + argument * arity)
    return [
        tuple(match.group(i).replace("\\_", "_").strip() for i in range(1, arity + 1))
        for match in pattern.finditer(DOC.read_text())
    ]


def example_date(text):
    year, rest = text.split("-", 1)
    return pd.Timestamp(f"{EXAMPLE_YEARS[year]}-{rest}")


def example_value(text):
    return None if text == "---" else text


def example_parameter(text):
    return text == "true" if text in ("true", "false") else int(text)


def defaulted_parameters(function):
    return {name for name, parameter in inspect.signature(function).parameters.items() if parameter.default is not parameter.empty}


def test_the_parameter_table_lists_each_parameter_of_the_signal():
    documented = [argument for _, argument in macro_calls("param", 2)]

    assert sorted(documented) == sorted(defaulted_parameters(pct_shares_issued) | defaulted_parameters(rebalance_dates)), DRIFT


def test_the_missing_reasons_are_listed_in_priority_order():
    assert tuple(reason for (reason,) in macro_calls("missingreason", 1)) == MISSING_REASONS, DRIFT


def test_the_corporate_event_actions_are_listed():
    documented = {action for (action,) in macro_calls("eventaction", 1)}

    assert documented == set(LOOKBACK_EVENT_ACTIONS) | {f"{LOOKBACK_EVENT_PREFIX}*"}, DRIFT


def test_the_signal_columns_are_listed_in_order():
    assert tuple(column for (column,) in macro_calls("signalcolumn", 1)) == SIGNAL_COLUMNS, DRIFT


def test_the_illustrative_example_matches_the_code():
    (rebalance,) = [example_date(day) for (day,) in macro_calls("exrebalance", 1)]
    parameters: dict[str, Any] = {name: example_parameter(value) for name, value in macro_calls("exparam", 2)}
    filings = pd.DataFrame(
        [
            {
                "ticker": company,
                "period_end": example_date(period_end),
                "filed_date": example_date(filed),
                "effective_date": example_date(effective),
                "share_count": float(shares),
                "share_factor": float(factor),
            }
            for company, period_end, filed, effective, shares, factor in macro_calls("exfiling", 6)
        ]
    )
    events = pd.DataFrame(
        [
            {"date": example_date(day), "permaticker": 0, "ticker": company, "action": action, "value": 1.0,
             "contra_ticker": None, "contra_name": None}
            for company, day, action in macro_calls("exevent", 3)
        ],
        columns=EVENT_COLUMNS,
    )
    expected = macro_calls("exresult", 7)
    constituents = pd.DataFrame(
        {"date": rebalance, "permaticker": range(len(expected)), "ticker": [company for company, *_ in expected]}
    )

    table = pct_shares_issued(constituents, filings, events, scope_breaks={}, **parameters).set_index("ticker")

    for company, net, pct, rank, age, reason, event in expected:
        row = table.loc[company]
        for column, text in [("net_shares_issued", net), ("pct_shares_issued", pct), ("pct_shares_issued_rank", rank)]:
            value = example_value(text)
            assert (pd.isna(row[column]) if value is None else row[column] == pytest.approx(float(value))), (
                f"{company} {column}. {DRIFT}"
            )
        assert row["filing_age_days"] == int(age), f"{company} filing_age_days. {DRIFT}"
        actual_reason = None if pd.isna(row["missing_reason"]) else row["missing_reason"]
        assert actual_reason == example_value(reason), f"{company} missing_reason. {DRIFT}"
        assert bool(row["corporate_event_in_lookback"]) == (event == "yes"), f"{company} event flag. {DRIFT}"


@pytest.mark.skipif(shutil.which("latexmk") is None, reason="TeX is not installed")
def test_the_document_builds(tmp_path):
    result = subprocess.run(
        ["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", f"-outdir={tmp_path}", str(DOC)],
        capture_output=True,
        text=True,
        cwd=DOC.parent,
    )

    assert result.returncode == 0, result.stdout[-3000:]
