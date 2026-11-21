# A Constituent with no Share Count is not ranked

## Context

100 of the Panel's 1,237,437 Constituent rows have no Share Count, because no filing in the data precedes them. Each cause was confirmed against the Company's SEC filing index:

- **PEP, ADBE and ALXN** filed their last report ahead of the Panel start too early for the data, whose earliest Filing Date is 2016-09-30. PEP filed on 2016-09-29 and ADBE on 2016-09-27. ALXN's report for the quarter to 2016-06-30 was filed on 2016-07-29, and its next report came late, on 2017-01-04. Their gaps end by 2017-02-15.
- **EVRG and LIN** were newly formed Companies that became Constituents before their first filing as the merged Company. Evergy was added on 2018-06-05 and filed first on 2018-08-08. Linde plc was added on 2018-10-31, when its merger closed, and filed on 2018-11-09. Its earlier reports, from 2017-10-30, are those of the pre-merger holding company and are not in the data.

CRH, VST and EXE also have rows with no Share Count, as do EVRG's 28 rows before it was added, but none of those rows is a Constituent row.

## Decision

The Share Count stays empty on these rows. A Company is ranked on a Rebalance Date only when it has a Share Count on that date and the data holds the earlier filing one Lookback back. No Share Count is estimated: not from a predecessor's filings, not from the first filing carried backwards, and not from other sources for filings older than the data. In the backtest, a Company that is not ranked on a Rebalance Date holds no position until the next one.

## Considered Options

- **Carry a predecessor's Share Count** (Great Plains Energy or Westar for EVRG, Praxair for LIN). A merger changes the Share Count by construction, so the change across it would read as issuance.
- **Back-fill the first filing's Share Count.** That uses a number before its Effective Date, which is look-ahead.
- **Read the missing PEP, ADBE and ALXN filings from SEC.** A change-based Signal over a 12-month Lookback needs a filing a year earlier. The 10-year data cannot supply one for any Company before late 2017, so these gaps, which end by 2017-02-15, never reach a ranking.

## Consequences

- A newly formed Company is first ranked one Lookback after its first filing. With a 12-month Lookback, EVRG is first ranked in 2019 and LIN in late 2019, although both were Constituents from 2018.
- If the Panel start moves forward with the 10-year floor (issue #4), Companies whose last filing falls just before the new floor will have the same short gap at the start. This rule covers those gaps too.
