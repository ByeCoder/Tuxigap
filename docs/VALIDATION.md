# What we actually checked

Release: **0.3.0**. Local runtime: Python 3.12.14, HTTPX 0.28.1.

| Check | Local result / boundary |
|---|---|
| Unit and integration tests | 83 independent tests passed before publication; CI runs the current suite |
| Ruff | Source, helper and test lint/format checks passed |
| JavaScript | Syntax checks included in validation |
| Native HTTP dashboard | Authentication, safe settings, training, static paths and period validation tested with a local server |
| Languages | English default, catalog placeholders, concurrent context isolation, group/private permission checks and localized welcome tested |
| Source ports | Entity offsets, scoped allowlists, lock families and bounded text output tested |
| Community additions | Anti-raid, quiet hours, trusted members, federation ownership, stale jobs, manual-ban protection and paid-gate interaction tested |
| AI additions | Context/public-note and image/quiz payload contracts tested with synthetic HTTP responses |
| Database upgrade | Schema 1 → 2 retains existing data in a regression test |
| Demo | Synthetic data population tested with network-client construction blocked |
| Real Telegram / Stars / AI provider | Not performed here: no real token, account or provider key supplied |
| Native Docker and browser | Current workflow builds the image and runs browser checks; see the recorded run below for outcomes |
| Studio companion | Pinned upstream source and Compose configuration reviewed; no live Studio deployment tested here |
| Independent security audit / load test | Not performed |

The earlier 0.2 code passed Python 3.12/3.13 and native Docker build in [this recorded run](https://github.com/ByeCoder/Tuxigap/actions/runs/43824057509). That historical result isn't a substitute for the current workflow or live integration testing.

A browser launch in the authoring workspace was blocked by its operating-system socket restrictions, so it isn't reported as a local visual pass. The browser smoke script is included for a normal runner and CI. Any screenshot it creates uses synthetic demo data only.

Please complete [LIVE_TEST.md](LIVE_TEST.md), especially membership payments and multi-group federation behavior, before using the toolkit with real communities.
