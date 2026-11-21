# Signals count shares in Primary Class units

Status: accepted, 2026-11-21. Resolves issue #2.

## Context

The Panel has one row per Company and uses the Primary Class. Sharadar has no per-class Share Counts, so it was not known whether `share_count` covers one Share Class or all of them.

`research/share_class_check.py` compared each Share Count with the per-class counts on the cover page of the same SEC filing, after later splits:

- **The six Companies with a folded Secondary Class** (GOOGL, FOXA, NWSA, TFCF, UAA, and WBD as Discovery) report a total across all Share Classes on every filing checked. The one exception, FOXA's first filing on 2019-03-18, has a cover that lists a single pre-spin-off share. Sharadar fell back to the weighted average count there.
- **BF.B** is also a total across all classes, Class A plus non-voting Class B, on every filing.
- **Every other Company whose cover lists several Share Classes is also a total, with three exceptions:**
  - ARES leaves out its non-voting common stock, about 1.5% of the total.
  - TAP leaves out its exchangeable shares, about 8% of the total, on filings through 2020.
  - PCG leaves out the shares held by its subsidiary ShareCo.

  Up-C Companies (CVNA, TKO and others) report their voting-only Class B, which pairs one to one with the operating units. Adding those shares in gives a count that assumes every unit has been exchanged for a share. Utilities that file together with a subsidiary (CMS, EIX, PPL, PCG, AIV) report the parent's count.
- **BRK.B and V** report a raw total across classes, but their classes are not worth the same. One BRK Class A share is worth 1,500 Class B shares. Visa's Class B and C shares convert into Class A at their own rates. Their `share_factor` converts the raw total into Primary Class units:
  - For BRK, `share_count × share_factor` matches B + 1,500·A within 0.6% on all 40 filings checked.
  - For Visa, it matches the as-converted count of common stock that Visa reports (2,098M on the 2022-01-28 filing).
  - `share_factor` is set per filing, so it carries no look-ahead.

## Decision

Signals use the Company Share Count, `share_count × share_factor`, through `src.share_classes.company_share_count`. They never use `share_count` alone.

For every Company other than BRK.B and V the factor is 1.0 and nothing changes. For BRK.B and V the raw total shifts whenever shares move between classes, such as BRK's A-to-B conversions or Visa's 2024 Class B exchange offer. A Signal on the raw count would read those shifts as issuance or buybacks.

## Consequences

- `market_cap_usd` already equals `share_count × share_factor × close_split_adjusted`, so a market value built from the Company Share Count agrees with it.
- The ARES, TAP and PCG gaps are small, or stable over time, and stay unadjusted. A per-Company correction would need data that Sharadar does not have.
- Any Company added to `SECONDARY_TO_PRIMARY` should be checked again with `research/share_class_check.py`.
