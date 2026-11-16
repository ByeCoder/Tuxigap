# What we actually checked

Release: **0.5.0**. Local runtime: Python 3.12.14, HTTPX 0.28.1.

**Current 0.5 CI: [all five jobs passed](https://github.com/ByeCoder/Tuxigap/actions/runs/43891342751)** for code commit `0a00596d8cb1a89e2c626506c20871830faa78b8`: 133 tests on Python 3.12/3.13, Ruff/catalog checks, core Docker, Chromium dashboard, and the dedicated music job. That music job passed the real offline dependency/media contract script, built the optional music Docker image, and ran its offline dependency check. No helper account or live call was connected.


**Previous 0.4 CI: [all four jobs passed](https://github.com/ByeCoder/Tuxigap/actions/runs/43878906180)** for code commit `9c3f7f60ac34b8774ca068a3cf1ed651a4d93738`: 109 tests on Python 3.12 and 3.13, Ruff/translation checks, native Docker build/offline check, and Chromium dashboard checks. The release wheel also built locally with all 15 catalogs.


**Prior 0.3 recorded CI: [all four jobs passed](https://github.com/ByeCoder/Tuxigap/actions/runs/43833871701)** for code commit `0c7606c37a0eed4a3f696c07656bef1b24db8962`: Python 3.12, Python 3.13, native Docker, and Chromium browser checks. The browser job captured the [desktop](images/dashboard-en.png) and [mobile](images/dashboard-mobile.png) previews using synthetic data.

| Check | Local result / boundary |
|---|---|
| Unit and integration tests | 133 independent tests passed before publication; CI runs the current suite |
| Ruff | Source, helper and test lint/format checks passed |
| JavaScript | Syntax checks included in validation |
| Native HTTP dashboard | Authentication, safe settings, training, static paths and period validation tested with a local server |
| Languages | English default, catalog placeholders, concurrent context isolation, group/private permission checks and localized welcome tested |
| Source ports | Entity offsets, scoped allowlists, lock families and bounded text output tested |
| Community additions | Anti-raid, quiet hours, trusted members, federation ownership, stale jobs, manual-ban protection and paid-gate interaction tested |
| AI additions | Context/public-note and image/quiz payload contracts tested with synthetic HTTP responses |
| Database upgrade | Schema 1/2 → 3 retains existing data in a regression test |
| Demo | Synthetic data population tested with network-client construction blocked |
| Real Telegram / Stars / AI provider | Not performed here: no real token, account or provider key supplied |
| Native Docker | Image build and offline configuration/database check passed in recorded CI |
| Browser | Chromium sign-in/out, analytics, language/RTL switching and mobile-width checks passed in recorded CI; desktop/mobile screenshots reviewed |
| Studio companion | Pinned upstream source and Compose configuration reviewed; no live Studio deployment tested here |
| Independent security audit / load test | Not performed |

The earlier 0.2 code passed Python 3.12/3.13 and native Docker build in [this recorded run](https://github.com/ByeCoder/Tuxigap/actions/runs/43824057509). That historical result isn't a substitute for the current workflow or live integration testing.

A browser launch in the authoring workspace was blocked by its operating-system socket restrictions, so it isn't reported as a local visual pass. The browser smoke script is included for a normal runner and CI. Any screenshot it creates uses synthetic demo data only.

Please complete [LIVE_TEST.md](LIVE_TEST.md), especially membership payments and multi-group federation behavior, before using the toolkit with real communities.


For 0.4, 26 additional tests cover safe emoji payloads and fallback, context isolation, staff assignment/scope, delegated moderation, peer protection, promotion subsets, join-policy/payment/federation interactions, retry and stale-button behavior, member-event deduplication, tags, ranks, channel controls, call events, confirmed erasure and persistent group-game rewards. The current 0.4 workflow above passed all jobs. No live Telegram, custom-emoji entitlement, call, channel or Stars test has been performed here.


For 0.5, 24 further tests cover 15 joke packs/80 Persian jokes, deck rotation, favorites, scoped review/erasure, music request deduplication, worker authorization/revocation, pause/resume/skip/stop/volume/repeat, restart states, queue ID stability, input limits and schema 3 → 4. The real music contract script also passed locally against py-tgcalls 3.0.1, NTgCalls 3.0.7 and Telethon 1.45.0, with actual FFmpeg download/transcode/probe and stream configuration checks. No account or call connection was made. The current 0.5 workflow above passed all five jobs.


The repository’s English About description was updated through GitHub and verified after saving. A [screenshot of the repository About panel](images/repository-about.jpg) records that result.
