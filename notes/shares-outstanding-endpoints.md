# Shares Outstanding Endpoints — Sharadar (inferred match for "Shape Radar")

Retrieval date for all sources: **2026-09-16**.

---

## 1. Summary / answer up front

There is no financial-data product called "Shape Radar." The near-certain intended product is **Sharadar** (`sharadar.com`), a US equity fundamentals vendor whose API is at `https://api.sharadar.com/v1.0/`. In Sharadar, shares outstanding lives in **exactly one table: `fundamentals`** (the table historically known as `SHARADAR/SF1`), in the field **`sharesbas`** — "the number of shares or other units outstanding of the entity's capital or common stock or other ownership interests; as stated on the cover of related periodic report (10-K/10-Q); after adjustment for stock splits" ([indicators endpoint](https://api.sharadar.com/v1.0/data/indicators?api_key=test-api-key&format=csv)). Two weighted-average variants (`shareswa`, `shareswadil`) and an ADR/multi-class adjustment multiplier (`sharefactor`) sit in the same table. **There is no public-float field anywhere in Sharadar** — a grep of the full first-party indicator dictionary (383 indicators across 17 tables) returns zero matches for "float". A second, *derived* route exists: `daily.marketcap` divided by `stocks.close` (times `sharefactor`) reproduces `sharesbas` exactly, because Sharadar defines `marketcap` as "the product of [SharesBas]; [Price] and [ShareFactor]" ([indicators](https://api.sharadar.com/v1.0/data/indicators?api_key=test-api-key&format=csv)) — I verified this numerically for AAPL on 2026-09-16 (4,851,251.4 USDm ÷ 332.41 = 14,594,180,000 = the exact `sharesbas`). For your cross-section, pull `fundamentals` with `dimension=ARQ` and a `from`/`to` window on the filing-date key.

---

## 2. Product identification & confidence

**Confidence that "Shape Radar" = Sharadar: high (~90%), but inferred, not confirmed.**

Evidence for the inference:

- No first-party financial-data API named "Shape Radar" exists. Web search for the term surfaces only unrelated shares-outstanding vendors (sec-api.io, EODHD, Intrinio) plus — notably — Sharadar itself.
- "Sharadar" is phonetically near-identical to "Shape Radar" (SHA-ra-dar / shape-radar).
- Sharadar is a paid-subscription product ([pricing](https://sharadar.com/pricing): $9–$69/month across Fundamentals, Prices, Investors and Bundle tiers), matching your description of a paid subscription.
- Sharadar is squarely a **cross-sectional US equity fundamentals** product: "Active and delisted coverage extends back to the 90s, is point-in-time ready, and nearly completely free of survivorship bias" ([sharadar.com](https://sharadar.com/)).

**What to confirm with the user:** Sharadar data is also resold through **Nasdaq Data Link / Quandl** (publisher page: [data.nasdaq.com/publishers/SHARADAR](https://data.nasdaq.com/publishers/SHARADAR)) under legacy table codes `SHARADAR/SF1`, `SHARADAR/DAILY`, `SHARADAR/SEP`, `SHARADAR/TICKERS`. The **field names are identical** on both, but the **request syntax is completely different**. Everything below documents the **direct sharadar.com API**. If the subscription is actually via Nasdaq Data Link, the field guidance carries over unchanged but the URLs/params do not. *(I could not retrieve the Nasdaq Data Link SF1 documentation page — it returned a content-free shell — so the Nasdaq-side request syntax is **unverified** here.)*

All endpoint behavior below was verified by live calls against the documented public sample key `test-api-key`, which returns real AAPL rows ([auth docs](https://sharadar.com/docs/auth)). Row counts and multi-ticker cross-sections could **not** be tested, since the sample key restricts results to AAPL — those claims are flagged.

---

## 3. Endpoint candidates

### Candidate A — `GET /v1.0/data/fundamentals` (the only direct source)

**Path:** `https://api.sharadar.com/v1.0/data/fundamentals` ([docs](https://sharadar.com/docs/fundamentals))
**Legacy identifier:** `SHARADAR/SF1` — "The primary US fundamentals table that contains income statement; balance sheet; cash flow statement; and derived and price-based metrics… The data are originally curated from SEC filings via forms 10; 20; 40; S-1; S-4; F-1; F-40; and 6-K." ([indicators, TABLE-DESCRIPTIONS/SF1](https://api.sharadar.com/v1.0/data/indicators?api_key=test-api-key&format=csv))

**Share fields** (all definitions verbatim from the [indicators endpoint](https://api.sharadar.com/v1.0/data/indicators?api_key=test-api-key&format=csv)):

| Field | Title | Definition | Unit |
|---|---|---|---|
| `sharesbas` | Shares (Basic) | "The number of shares or other units outstanding of the entity's capital or common stock or other ownership interests; as stated on the cover of related periodic report (10-K/10-Q); after adjustment for stock splits." | units |
| `shareswa` | Weighted Average Shares | "The weighted average number of shares or units issued and outstanding that are used by the company to calculate [EPS]; determined based on the timing of issuance of shares or units in the period." | units |
| `shareswadil` | Weighted Average Shares Diluted | "…used by the company to calculate [EPSDil]…" | units |
| `sharefactor` | Share Factor | "a multiplicand in the calculation of [MarketCap] and is used to adjust for: American Depository Receipts (ADRs) that represent more or less than 1 underlying share; and; companies which have different earnings share for different share classes (eg Berkshire Hathaway - BRK.B)." | ratio |

**`sharesbas` is the cover-page count — the one you want for a shares-outstanding cross-section.** It is a *balance-sheet-date-style* snapshot from the filing cover, not a period average; `shareswa`/`shareswadil` are period averages for EPS and are the wrong instrument for a point-in-time cross-section. No float/free-float field exists.

**Point-in-time semantics — the `dimension` parameter.** Verbatim: "ARQ: Quarterly; excluding restatements; MRQ: Quarterly; including restatements; ARY: annual; excluding restatements; MRY: annual; including restatements; ART: trailing-twelve-months; excluding restatements; MRT: trailing-twelve-months; including restatements." The `date` field (Date Key) "represents the SEC filing date for AR dimensions (ARQ;ART;ARY); and the [REPORTPERIOD] for MR dimensions (MRQ;MRT;MRY)." ([indicators](https://api.sharadar.com/v1.0/data/indicators?api_key=test-api-key&format=csv))

→ **Use an `AR*` dimension for any historical cross-section.** `ARQ` gives you what was actually knowable on the filing date. `MRQ` gives restated values and will leak future information into a backtest.

**Date columns:** `date` (Date Key = filing date under AR), `reportperiod` ("the end date of the fiscal period"), `calendardate` ("the normalized [ReportPeriod]… necessary due to irregularity in report periods across companies" — e.g. a 2015-09-26 period maps to 2015-09-30 for Q dimensions, 2015-12-31 for annual). ([indicators](https://api.sharadar.com/v1.0/data/indicators?api_key=test-api-key&format=csv))

**Update frequency / lag / coverage / history** ([docs](https://sharadar.com/docs/fundamentals)):
- Update: "Daily at 17h30 and 23h30 US Eastern (ET)"
- Lag: "< 1 day"
- Coverage: "Common stock securities (primary class) that are active or delisted from Nasdaq, NYSE or NYSEMKT"
- History: "January 1998"

**Query parameters** ([docs](https://sharadar.com/docs/getting-started)): `ticker` (comma-separated), `from` / `to` (YYYY-MM-DD), `fields`, `format` (`csv` default, or `json`), `limit` (default 10,000), `skip`, `sort` (`<col>.asc` / `<col>.desc`, defaults to date descending), and comparators `.gt` `.gte` `.lt` `.lte` (e.g. `calendardate.gte=2021-09-16`).

**Verified behavioral details** (live calls, 2026-09-16, not stated in the docs):
- Only `dimension`, `ticker`, `calendardate` and `lastupdated` are flagged `isfilter=Y` for the fundamentals table; **`date` and `reportperiod` are NOT directly filterable** ([indicators](https://api.sharadar.com/v1.0/data/indicators?api_key=test-api-key&format=csv)). Passing `date=2024-08-01` is silently ignored and returns the default window — a real footgun.
- **But `from`/`to` do filter on `date`** (the filing-date key under AR dimensions). Verified: `ticker=AAPL&dimension=ARQ&from=2023-05-01&to=2023-05-31` returned exactly one row, `date=2023-05-05, reportperiod=2023-04-01`. This is the mechanism for a true point-in-time pull.
- Default date range when `from`/`to` are omitted is "one year ago to present" ([docs](https://sharadar.com/docs/getting-started)) — omitting them silently truncates history.

**Two ways to pull a cross-section:**

*A1 — fiscal-period aligned (recommended for most cross-sections):*
```
GET /v1.0/data/fundamentals?api_key=KEY&dimension=ARQ&calendardate=2024-06-30
    &fields=ticker,date,reportperiod,calendardate,sharesbas,sharefactor&limit=10000&format=csv
```
One row per company for the normalized quarter. Clean alignment, but the rows were *filed* over a ~3-month spread, so this is not knowable-as-of-one-date.

*A2 — filing-date aligned (true point-in-time):*
```
GET /v1.0/data/fundamentals?api_key=KEY&dimension=ARQ&from=2024-04-01&to=2024-06-30
    &fields=ticker,date,reportperiod,sharesbas,sharefactor&limit=10000&sort=date.asc
```
Then per ticker take the last row with `date <= as_of`. Requires a trailing window of ~6–12 months to be sure every company has filed at least once.

*Pagination:* page with `skip` in steps of `limit`. The docs state limit "defaults to 10,000"; whether 10,000 is also a hard ceiling is **unverified** (a `limit=20000` request returned HTTP 200 but the sample key's AAPL-only restriction makes the row count uninformative). Pair `skip` with an explicit deterministic `sort` (e.g. `sort=ticker.asc`) — paginating against the default date-descending sort with ties is not safe.

**Tier gating:** included in the **Fundamentals** product and the **Bundle** ([pricing](https://sharadar.com/pricing)). History depth is gated by tier: 5-year / 10-year / full-history variants at $19–$39/mo (Fundamentals) or $29–$69/mo (Bundle). A 5-year tier cannot serve a pre-2021 cross-section.

---

### Candidate B — `GET /v1.0/bulk` (whole-table download of the same data)

**Path:** `https://api.sharadar.com/v1.0/bulk?api_key=KEY` returns a JSON manifest of pre-built zips; documented at [sharadar.com/docs/bulk](https://sharadar.com/docs/bulk) and confirmed by a live call. The manifest lists 38 objects with keys, sizes and `canDownload` flags. Fundamentals entries as of 2026-09-17 (manifest `modified` timestamps):

| key | history | size |
|---|---|---|
| `bulk-sharadar/fundamentals-5Y.csv.zip` | 5 Years | 114.5 MB |
| `bulk-sharadar/fundamentals-10Y.csv.zip` | 10 Years | 225.1 MB |
| `bulk-sharadar/fundamentals.csv.zip` | Full History | 629.9 MB |

Same table, same fields, same semantics as Candidate A — this is a delivery mechanism, not a different dataset. "Bulk downloads (years=5, years=10, years=full) match the purchased history tier." ([pricing](https://sharadar.com/pricing)). The manifest reports `canDownload: false` for an unauthenticated caller, so it is subscription-gated.

**Use it when** you need many cross-sections, or want to do the as-of join locally. **Avoid it** for a single one-date cross-section — you would download 115–630 MB to use one quarter of it.

---

### Candidate C — derive from `daily.marketcap` ÷ `stocks.close` (daily-resolution workaround)

**Paths:** `https://api.sharadar.com/v1.0/data/daily` ([docs](https://sharadar.com/docs/daily), legacy `SHARADAR/DAILY`) and `https://api.sharadar.com/v1.0/data/stocks` (legacy `SHARADAR/SEP`).

**`daily` does not contain a shares field.** Its complete field list is `ticker, date, lastupdated, ev, evebit, evebitda, marketcap, pb, pe, ps` ([indicators](https://api.sharadar.com/v1.0/data/indicators?api_key=test-api-key&format=csv)) — verified by a live call. But:

> `marketcap` (Market Capitalization - Daily): "Represents the product of [SharesBas]; [Price] and [ShareFactor]. [SharesBas] is sourced from the most recent SEC form 10 filing."
> — [indicators](https://api.sharadar.com/v1.0/data/indicators?api_key=test-api-key&format=csv)

So `sharesbas = marketcap × 1e6 ÷ (close × sharefactor)` (note `daily.marketcap` is in **USD millions**; `fundamentals.marketcap` is in **USD** — do not mix them).

**Verified numerically**, AAPL, 2026-09-16: `daily.marketcap` = 4,851,251.4 (USDm); `stocks.close` = `stocks.closeunadj` = 332.41; `sharefactor` = 1. 4,851,251.4e6 ÷ 332.41 = 14,594,180,000 — an exact match to `sharesbas` from the ARQ row filed 2026-07-31.

**Coverage / history / update** ([daily docs](https://sharadar.com/docs/daily)): coverage "All tickers in the fundamentals table"; history from **December 1998**; update "Daily at 19h00 US Eastern (ET)"; lag "< 1 day".

**Why this is sometimes the better route:** `daily` is a *daily-resolution* table keyed on calendar date, and both `date` and `ticker` are `isfilter=Y`. So `?date=2024-06-28` gives you a genuine one-calendar-date cross-section with no filing-date-spread problem — Sharadar has already done the "most recent filing as of this date" join for you.

**Why it is risky:**
- `sharesbas` is split-adjusted; `stocks.close` is also split-adjusted ("adjusted for stock splits and stock dividends"), while `closeunadj` is not ([indicators](https://api.sharadar.com/v1.0/data/indicators?api_key=test-api-key&format=csv)). For AAPL on the test date the two were identical, so **which divisor is correct for a ticker that split after the filing date is UNVERIFIED.** `close` is the self-consistent choice given both sides are split-adjusted, but test this on a known post-filing splitter before trusting it.
- Division by a price loses precision and blows up for penny stocks.
- `sharefactor` is not in `daily`; you must join it from `fundamentals` anyway, which partly defeats the point.
- `daily` also re-bases on price, so any daily marketcap error propagates straight into the implied share count.
- The `daily` table is **not point-in-time in the AR sense**: the doc for its sibling `ev` says the inputs are "sourced from the most recent SEC form 10 filings", but whether historical `daily` rows were frozen at the time or are recomputed from restated fundamentals is **unverified**.

---

### Non-candidates (checked and ruled out)

- **`metrics`** (`/v1.0/data/metrics`, legacy `SHARADAR/METRICS`): beta, dividend yield, moving averages, 52w high/low, price, volume. No share count. Also appears to be a *current-snapshot* table — its full-history bulk file is only 1.41 MB vs 630 MB for fundamentals.
- **`stocks`** (`SEP`): prices only — `close`, `closeadj`, `closeunadj`, `open`, `high`, `low`, `volume`.
- **`insiders`** (`SF2`): has `sharesownedbeforetransaction` / `sharesownedfollowingtransaction` — insider positions, not company shares outstanding.
- **`holdings`** (`SF3`): 13F institutional positions, not shares outstanding.
- **Public float:** does not exist in Sharadar. Zero hits for "float" across all 383 indicators. If you need float, you need a different vendor.

---

## 4. Recommendation (ranked)

1. **`GET /v1.0/data/fundamentals`, `dimension=ARQ`, `sharesbas`** — the only authoritative source, as-reported, restatement-free. **This is the recommendation.** For a one-date cross-section use the `calendardate=` form (A1) if you want fiscal-period alignment, or `from`/`to` on the filing date (A2) if you need strict point-in-time. Cheapest and fastest for a *single* cross-section: one paginated request, a handful of columns via `fields=`, CSV.
2. **`GET /v1.0/data/daily` + `stocks` derivation** — use only when you specifically need a share count on a *calendar* date with no filing-spread, and only after validating the split-adjustment edge case. Second because it is derived, lossy, and its historical point-in-time behavior is unverified.
3. **`GET /v1.0/bulk`** — best when you need many dates or want local control of the as-of join; worst for one date (115–630 MB for one quarter's worth of use).

---

## 5. Cross-sectional data-quality caveats

**Survivorship bias — largely solved, but you must opt in.** Coverage is "active or delisted from Nasdaq, NYSE or NYSEMKT" ([fundamentals docs](https://sharadar.com/docs/fundamentals)) and the vendor claims "nearly completely free of survivorship bias" ([sharadar.com](https://sharadar.com/)) — note the hedge "nearly." The trap is downstream: if you build your universe from a *current* ticker list you reintroduce the bias yourself. Build it from `/v1.0/data/tickers`, which covers the "full universe including delisted" and carries an `isdelisted` flag ([tickers docs](https://sharadar.com/docs/tickers)). Also note the exchange restriction: **OTC and other venues are out of scope** — that is a real coverage hole in any "all US public companies" cross-section.

**Ticker recycling — use `permaticker`, not `ticker`.** Verbatim: "Where a company is delisted and the ticker subsequently recycled for use by a different company; we utilise that ticker for the currently active company and append a number to the ticker of the delisted company." ([indicators](https://api.sharadar.com/v1.0/data/indicators?api_key=test-api-key&format=csv)). `permaticker` is "a unique and unchanging identifier for a security (share class)" ([tickers docs](https://sharadar.com/docs/tickers)). Keying a historical cross-section on `ticker` will silently mis-join recycled symbols.

**As-of correctness vs restatement.** `ARQ` excludes restatements and keys on filing date; `MRQ` includes them and keys on report period. For a historical cross-section, `MRQ` is look-ahead bias. Note the asymmetry: **under `MR*` dimensions, `date` is the report period, not a filing date** — so `from`/`to` mean something entirely different depending on `dimension`. Verified for `ARQ` only; the `MR*` `from`/`to` behavior is **unverified**.

**Split adjustment.** `sharesbas` is "after adjustment for stock splits" — i.e. it is **restated backwards** for splits that occurred after the filing. A 2015 `sharesbas` reflects splits through today, not the raw cover-page number filed in 2015. For a cross-section of *levels at a point in time* this is usually what you want (it is consistent with `close`), but it means `sharesbas` is **not** the number that appeared on the original 10-Q cover, and the same historical row can change value after a future split. That also means a cross-section pulled today and the same cross-section pulled next year may not be identical.

**Multiple share classes.** The fundamentals table is **"primary class" only** ([fundamentals docs](https://sharadar.com/docs/fundamentals)), and `permaticker` is per *share class*. So for a dual-class company (BRK.A/BRK.B, GOOG/GOOGL), `sharesbas` is the primary class's count — **not** the company's total shares across classes. `sharefactor` exists to patch the market-cap calculation for "companies which have different earnings share for different share classes (eg Berkshire Hathaway - BRK.B)" ([indicators](https://api.sharadar.com/v1.0/data/indicators?api_key=test-api-key&format=csv)). **If your cross-section is company-level rather than security-level, you must multiply by `sharefactor` and/or roll up secondary classes yourself** via the `relatedtickers` field in the tickers table. Exactly how `sharefactor` is constructed per issuer is **not documented beyond that one sentence — treat any total-shares roll-up as requiring your own validation.**

**ADRs.** `sharefactor` also adjusts "American Depository Receipts (ADRs) that represent more or less than 1 underlying share." So for ADRs, `sharesbas` counts *ADRs*, not underlying ordinary shares — a raw cross-section will mix two different units unless you apply `sharefactor`.

**Aligning on a single as-of date.** Filings land over roughly a three-month spread, so there is no single date on which every company's latest figure is equally fresh. Three options, in order of rigor:
1. *(Most rigorous)* Pull `ARQ` over a trailing 12-month `from`/`to` window on filing date, then per `permaticker` take the row with the greatest `date <= as_of`. Also carry `date` through to your output so you can control for staleness (a company that last filed 11 months ago is a different observation than one that filed last week).
2. *(Simplest)* Pull one `calendardate` with `ARQ`. Accepts the filing-date spread but gives clean fiscal alignment.
3. *(Calendar-exact but derived)* Candidate C's `daily` route, which bakes in the as-of join — subject to its own caveats above.

**Currency.** `fundamentals.marketcap` is in USD; `daily.marketcap` is in **USD millions**. Share counts are in raw units in both. Mixing units here is the single easiest way to produce a silently-wrong cross-section.

---

## 6. Open questions for the user

1. **Is the product actually Sharadar, and are you on the direct `api.sharadar.com` API or on Nasdaq Data Link?** Field names are the same; request syntax is not. Everything above is verified against the direct API only.
2. **Which history tier do you hold** (5Y / 10Y / full)? A 5-year subscription cannot serve a pre-2021 as-of date ([pricing](https://sharadar.com/pricing)).
3. **Security-level or company-level cross-section?** This decides whether you need the `sharefactor` / `relatedtickers` multi-class roll-up.
4. **Do you actually need free float?** Sharadar has none. If float is the requirement, this is the wrong vendor.
5. **Is OTC coverage required?** Sharadar is Nasdaq / NYSE / NYSEMKT only.
6. **Backtest or current snapshot?** If backtest, `ARQ` is mandatory and the split-adjustment restatement of `sharesbas` needs an explicit decision.

## 7. Explicitly unverified

- Whether 10,000 is a hard row ceiling on `limit`, and the exact pagination contract beyond `skip`.
- API rate limits / quotas — **not documented anywhere** in [auth](https://sharadar.com/docs/auth) or [getting-started](https://sharadar.com/docs/getting-started).
- Row counts for a real multi-ticker cross-section (the public `test-api-key` returns AAPL only).
- The Nasdaq Data Link request syntax for `SHARADAR/SF1` — the documentation page returned no retrievable content.
- Whether `close` or `closeunadj` is the correct divisor in Candidate C for a ticker that split after its last filing.
- `from`/`to` semantics under the `MR*` dimensions.
- Whether historical `daily` rows are frozen point-in-time or recomputed from restated fundamentals.
- Total company count and indicator count (the homepage makes no quantified claim; the figures "16,000 companies / 28 years / 150 indicators" appear only in third-party search summaries and are **not sourced to a first-party page**).

---

## 8. Sources

All retrieved **2026-09-16**.

- https://sharadar.com/ — product overview, survivorship-bias and point-in-time claims
- https://sharadar.com/pricing — products, tiers, prices, history gating, bulk gating
- https://sharadar.com/docs/intro — documentation index
- https://sharadar.com/docs/auth — API key authentication, `test-api-key`
- https://sharadar.com/docs/getting-started — base URL, query params, comparators, pagination, defaults
- https://sharadar.com/docs/fundamentals — fundamentals endpoint, coverage, history, update frequency, lag
- https://sharadar.com/docs/daily — daily endpoint, coverage, history, update frequency, field list
- https://sharadar.com/docs/tickers — tickers endpoint, full universe incl. delisted, `permaticker`, `isdelisted`
- https://sharadar.com/docs/bulk — bulk downloads
- https://api.sharadar.com/v1.0/data/indicators?api_key=test-api-key&format=csv — **the authoritative machine-readable data dictionary**; all verbatim field definitions above
- https://api.sharadar.com/v1.0/data/fundamentals?api_key=test-api-key&ticker=AAPL&dimension=ARQ — live verification of share fields and dimension behavior
- https://api.sharadar.com/v1.0/data/daily?api_key=test-api-key&ticker=AAPL — live verification of the daily field list
- https://api.sharadar.com/v1.0/data/stocks?api_key=test-api-key&ticker=AAPL — live verification of `close` / `closeunadj`
- https://api.sharadar.com/v1.0/bulk?api_key=test-api-key — live bulk manifest (file names, history tiers, sizes)
- https://data.nasdaq.com/publishers/SHARADAR — Nasdaq Data Link publisher page (resale channel; SF1 documentation itself was not retrievable)
