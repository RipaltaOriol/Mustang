# Signals count shares in Primary Class units

## Context

The Panel has one row per Company and uses the Primary Class. Sharadar has no per-class Share Counts, so it was not known whether `share_count` covers one Share Class or all of them.

`research/share_class_check.py` screened every Ever-member. It compared every Share Count of each flagged Company with the per-class shares outstanding on the cover of the same SEC filing, after later splits. That covered 165 Companies, 72 of whose covers list several Share Classes.

- **The six Companies with a folded Secondary Class** (GOOGL, FOXA, NWSA, TFCF, UAA, and WBD as Discovery) report a total across all Share Classes on every filing whose cover lists several classes. FOXA's first filing, on 2019-03-18, lists a single pre-spin-off share, and Sharadar used the weighted average count there.
- **BF.B** is a total of Class A and non-voting Class B on all 41 filings.
- **BRK.B and V** report a raw total across classes on every filing, but their classes are not worth the same. One BRK Class A share is worth 1,500 Class B shares. Visa's Class B and C shares convert into Class A at their own rates. Their `share_factor` converts the raw total into Primary Class units:
  - For BRK, `share_count × share_factor` matches B + 1,500·A within 0.64% on all 40 filings.
  - For Visa, it matches the as-converted count of common stock Visa reports, to within the as-converted preferred stock. On the 2022-01-28 filing the figures are 2,098M and 2,098M. On the 2026-11-05 filing they are 1,863M and 1,867M, of which about 9M is preferred. These two filings were read by hand and are not in the script.
  - `share_factor` is set per filing, so it carries no look-ahead. Among the Ever-members' filings, it differs from 1.0 only for BRK.B and V (the build report's "Share factors other than 1" table).
- **Every other multi-class Company is also a total**, with these exceptions:
  - TAP leaves out its exchangeable shares (about 8%) on filings through 2020. The cover stops listing them in 2021, and the Share Count does not move then (+0.02%), so TAP's changes are comparable.
  - ARES, KKR and PCG change which classes their Share Count covers, at the filings in `SCOPE_BREAKS`:
    - ARES counts its voting-only Class C, paired with operating units, from 2020-05-08 (+109%) and stops on 2026-02-25 (−32%).
    - KKR does the same from 2018-11-02 (+59%) to 2020-08-07 (−34%).
    - PCG starts counting the shares its subsidiary ShareCo holds on 2026-07-23 (+22%).
- **Up-C Companies** (CVNA, TKO and others) report their voting-only Class B. It pairs one to one with the operating units, so the total counts every unit as if it had been exchanged, consistently over time. **Utilities that file together with a subsidiary** (AIV, CMS, EIX, PPL, PCG) report the parent's count.

## Decision

1. Signals use the Company Share Count, `share_count × share_factor`, through `src.share_classes.company_share_count`. They never use `share_count` alone. For every Company other than BRK.B and V the factor is 1.0, so nothing changes. For BRK.B and V the raw total moves whenever shares change class (BRK's conversions from A to B, Visa's 2024 Class B exchange offer). A Signal on the raw count would read those moves as issuance or buybacks.
2. A change-based Signal drops any change that `src.share_classes.crosses_scope_break` flags. Each break moves the Share Count by 22% to 109% with no issuance or buyback behind it, and no single per-Company correction would hold for every filing.

## Consequences

- `market_cap_usd` already equals `share_count × share_factor × close_split_adjusted`, so a market value built from the Company Share Count agrees with it.
- A Company that starts or stops counting a class after this check is not in `SCOPE_BREAKS`. Run `research/share_class_check.py` again after refreshing the snapshots, and whenever a Company is added to `SECONDARY_TO_PRIMARY`.
