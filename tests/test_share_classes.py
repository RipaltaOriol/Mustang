import pandas as pd
import pytest

from src.share_classes import (
    ALL_CLASSES,
    UNMATCHED,
    company_share_count,
    share_count_scope,
    split_multiplier,
)


def test_company_share_count_converts_to_primary_class_units():
    counts = pd.DataFrame({"share_count": [1_000.0, 500.0], "share_factor": [1.5, 1.0]})

    assert company_share_count(counts).tolist() == [1_500.0, 500.0]


def test_company_share_count_is_unchanged_by_a_conversion_between_classes():
    # 1 Class A share is worth 1,500 Class B shares; converting it adds 1,499 to the raw count.
    before = {"a": 10.0, "b": 1_000.0}
    after = {"a": 9.0, "b": 2_500.0}

    def row(classes):
        raw = classes["a"] + classes["b"]
        return {"share_count": raw, "share_factor": (classes["b"] + 1_500 * classes["a"]) / raw}

    counts = pd.DataFrame([row(before), row(after)])

    assert counts["share_count"].iloc[1] != counts["share_count"].iloc[0]
    assert company_share_count(counts).iloc[1] == pytest.approx(company_share_count(counts).iloc[0])


def test_scope_is_all_classes_when_the_count_is_their_total():
    covers = {"ClassA": 600.0, "ClassB": 400.0}

    assert share_count_scope(1_000.0, covers) == ALL_CLASSES


def test_scope_names_the_one_class_a_count_covers():
    covers = {"ClassA": 600.0, "ClassB": 400.0}

    assert share_count_scope(601.0, covers) == "ClassA"


def test_scope_prefers_all_classes_when_one_class_holds_nearly_every_share():
    covers = {"ClassA": 1_000.0, "ClassB": 1.0}

    assert share_count_scope(1_000.0, covers) == ALL_CLASSES


def test_scope_is_unmatched_when_no_class_or_total_fits():
    covers = {"ClassA": 600.0, "ClassB": 400.0}

    assert share_count_scope(800.0, covers) == UNMATCHED


def test_scope_is_unmatched_without_cover_counts():
    assert share_count_scope(800.0, {}) == UNMATCHED
    assert share_count_scope(800.0, {"ClassA": 0.0}) == UNMATCHED


def test_split_multiplier_compounds_only_splits_after_the_filing():
    splits = pd.DataFrame(
        {
            "ticker": ["X", "X", "X", "Y"],
            "date": pd.to_datetime(["2019-01-01", "2021-01-01", "2022-01-01", "2021-01-01"]),
            "value": [3.0, 2.0, 20.0, 7.0],
        }
    )

    assert split_multiplier(splits, "X", pd.Timestamp("2020-06-30")) == 40.0
    assert split_multiplier(splits, "X", pd.Timestamp("2022-01-01")) == 1.0
    assert split_multiplier(splits, "Z", pd.Timestamp("2020-06-30")) == 1.0
