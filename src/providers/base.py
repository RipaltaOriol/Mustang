"""
Provider-neutral market data interface that cross-section research code depends on.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import date
from typing import Literal

import pandas as pd

DateLike = date | str
Dataset = Literal["shares_outstanding", "market_caps", "prices"]

SECURITY_COLUMNS = (
    "security_id",
    "ticker",
    "name",
    "exchange",
    "is_delisted",
    "category",
    "sector",
    "industry",
    "currency",
    "first_price_date",
    "last_price_date",
)
SHARES_OUTSTANDING_COLUMNS = (
    "ticker",
    "filed_date",
    "period_end",
    "shares_outstanding",
    "share_factor",
)
MARKET_CAP_COLUMNS = ("ticker", "date", "market_cap_usd")
PRICE_COLUMNS = (
    "ticker",
    "date",
    "open",
    "high",
    "low",
    "close",
    "close_unadjusted",
    "close_with_dividends",
    "volume",
)


class DataProviderError(Exception):
    """
    A provider request failed in a way retrying did not resolve.
    """


class NotEntitledError(DataProviderError):
    """
    The subscription behind the credentials does not include the requested data.
    """


class InsufficientHistoryError(DataProviderError):
    """
    The requested start date is earlier than the subscription's history reaches.
    """


class DataProvider(ABC):
    """
    A source of survivorship-free US equity data, returned as long DataFrames.

    Raises:
        NotEntitledError: the subscription does not include the data.
        InsufficientHistoryError: an explicit start precedes the subscription's history.
        DataProviderError: the request failed after retries.
    """

    @abstractmethod
    def earliest_date(self, dataset: Dataset) -> date:
        """
        Return the first date the subscription can serve for a dataset.
        """

    @abstractmethod
    def securities(self) -> pd.DataFrame:
        """
        Return active and delisted securities that have share counts, as SECURITY_COLUMNS.
        """

    @abstractmethod
    def shares_outstanding(
        self,
        start: DateLike | None = None,
        end: DateLike | None = None,
        tickers: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        """
        Return as-reported share counts bounded by filing date, as SHARES_OUTSTANDING_COLUMNS.
        Counts carry adjustments for splits after filing; a start of None means all available.
        """

    @abstractmethod
    def market_caps(
        self,
        start: DateLike | None = None,
        end: DateLike | None = None,
        tickers: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        """
        Return daily market capitalisation in USD, as MARKET_CAP_COLUMNS.
        """

    @abstractmethod
    def prices(
        self,
        start: DateLike | None = None,
        end: DateLike | None = None,
        tickers: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        """
        Return daily prices, as PRICE_COLUMNS: `close` is split-adjusted and
        `close_with_dividends` is also dividend-adjusted, for total returns.
        """
