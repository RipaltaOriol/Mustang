# Outstanding Shares Cross-Section

Research into whether changes in a company's outstanding shares explain differences in returns across S&P 500 companies.

## Language

### Universe

**Constituent**:
A company in the S&P 500 on a given date, judged by what the index held on that date and not by what it holds today.
_Avoid_: Member, current constituent

**Ever-member**:
A company that was a Constituent on at least one date in the research window, whether or not it still exists.
_Avoid_: Survivor, universe

**Company**:
The issuer as a single economic unit, however many Share Classes it lists.
_Avoid_: Security, stock, ticker

**Share Class**:
One listed type of a Company's stock, such as GOOGL or GOOG.
_Avoid_: Security

**Primary Class**:
The one Share Class that carries a Company's filing data and represents the Company in the Panel.
_Avoid_: Main ticker

**Secondary Class**:
Any Share Class of a Company other than its Primary Class.

### Data

**Panel**:
The dataset with one row per Company per trading day, holding the inputs from which Signals are derived.
_Avoid_: Signal, dataset, data points

**Signal**:
A value derived from the Panel to rank Companies against each other. It is defined separately from the Panel.
_Avoid_: Factor, feature

**Share Count**:
The number of shares outstanding reported on a filing's cover page, adjusted for later stock splits.
_Avoid_: Float, weighted average shares

**Company Share Count**:
The Share Count times its share factor: the Company's shares across all Share Classes, in units of its Primary Class. Signals use it in place of the Share Count.
_Avoid_: Total shares, economic shares

**Filing Date**:
The date a Company's report reached the SEC.
_Avoid_: Report date, period end

**Effective Date**:
The first trading day after the Filing Date, from which a Share Count may be used.
_Avoid_: Available date

**Restatement**:
A later correction to a number in an earlier filing. The Panel uses numbers as first reported, without Restatements.

**Re-filing**:
A later `ARQ` filing for a quarter the Company has already filed, often an amendment. By default the Panel keeps the first filing's Share Count and drops the Re-filing.
_Avoid_: Amendment, restatement

**Exit**:
The end of a Company's listing, by acquisition, bankruptcy or another cause. It is recorded on the Company's last row only.
_Avoid_: Delisting return, removal

**Corporate Event**:
An acquisition, merger, spin-off or stock split that can change a Share Count or a price without routine issuance or buybacks.
_Avoid_: Action

### Signals

**Rebalance Date**:
A date on which Signals are measured and Companies are ranked.
_Avoid_: Formation date, observation date

**Lookback**:
The span between the two filings a change-based Signal compares, measured between their period ends.
_Avoid_: Window, horizon

**Net Shares Issued**:
The change in the Company Share Count over the Lookback, counted in shares. It cannot be compared across Companies, so it is never ranked.
_Avoid_: Net Issuance

**Percentage Shares Issued**:
The change in the Company Share Count over the Lookback as a fraction of the earlier Company Share Count. It is a Signal, and a negative value means a net buyback.
_Avoid_: Net Issuance, dilution, share change
