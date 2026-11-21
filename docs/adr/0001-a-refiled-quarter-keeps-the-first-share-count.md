# A re-filed quarter keeps the first Share Count

Sharadar's `ARQ` dimension excludes Restatements, but 109 filings still re-file a quarter the Company had already filed. They cover 4,008 Panel rows, and eight change the Share Count: BBBYQ's quarter ending 2022-11-26 goes from 117M to 559M. Applied from its Effective Date, a Re-filing causes no look-ahead, but it can look like large issuance and produce a false Signal.

`share_counts` therefore drops Re-filings by default, so the first filing for a quarter stays in force until the Company files a later quarter. The whole filing row is dropped, so `revenue`, `netinc`, `equity` and the other filing fields also stay as first reported, in line with the Panel's use of numbers as first reported. `keep_refilings=True` keeps them instead, each from its own Effective Date, for research that wants the information that was public on that date.

## Considered options

- **Keep the Re-filing and flag it.** Keeps the public information, but every Signal would have to handle the flag to avoid the false jump.
- **Keep the Re-filing with no flag.** Simplest, but false Signals stay hidden.

Source: [RipaltaOriol/Mustang#1](https://github.com/RipaltaOriol/Mustang/issues/1).
