# What is available in 0.5.0?

| Capability | Where it lives | Integration status |
|---|---|---|
| Moderation, warnings, member buttons and permission checks | Native core | Implemented and behavior-tested |
| 40+ Studio content locks and scoped allowlists | Credited Python port | Implemented and behavior-tested |
| Selected Zero Two/Astrako fun helpers | Credited native adapters | Implemented and behavior-tested |
| Flood, blocked phrases, quiet hours, trusted members and join raids | Native core | Implemented and behavior-tested |
| Federations and queued shared decisions | Native core | Implemented; live multi-group verification still needed |
| Four calendar-period reports and CSV | Native core/dashboard | Implemented and behavior-tested |
| English-default interface and 15 language choices | Native catalogs/dashboard | Core menus localized; advanced strings may use English fallback |
| AI questions, public notes, optional context and summaries | Native provider adapter | Implemented; HTTP contract mocked in tests |
| AI-generated quizzes and opt-in photo review | Native provider adapter | Implemented; real provider/model validation still needed |
| Human labels and sample learning | Native core + optional real engine | Implemented; no autonomous fine-tuning claim |
| XP, daily streaks, badges, referrals and giveaways | Native core | Implemented and behavior-tested |
| Notes, auto-replies, AFK and content scheduling | Native core | Implemented |
| Stars memberships, refunds and recovery | Native core | Implemented; official live/test-environment payment verification still needed |
| Full tg-spam detection and engine UI | Optional upstream service | API adapter and deployment provided; configure/test the actual service |
| CAS and Lua | Configured inside the upstream engine | Not native reimplementations; engine credentials/settings required |
| CRM, support desk, flow builder, Mini Apps and commerce | Full pinned Studio companion | Deployment provided; separate bot/token/ledger and upstream configuration |
| Native owner dashboard and offline demo | Native core | HTTP behavior tested; browser checks tracked in CI |
| Gregorian calendar periods | Native core | Implemented |
| Solar Hijri report periods | Native core | Not implemented |
| Full legacy anime/weather/downloader handler trees | Not imported | Not claimed as native features |
| Call music with queue controls | Optional helper-account MTProto worker | Implemented, fake-engine and real dependency/media contracts tested; live account/call test still required |
| 240 multilingual jokes, favorites and suggestions | Native offline packs + scoped community content | 15 languages, including 80 Persian jokes; review/permission/deck tests |
| A single shared ledger/login/token for all companion services | Not included | Deliberately not claimed |

No row marked as implemented means “independently security-audited” or “tested with your real bot token.” Please follow the live test guide before launch.


Version 0.4 additions: [staff/ranks/tags/membership/channel/call tools](COMMUNITY.md), [keyboard styles and custom emoji](APPEARANCE.md), [shared games](GAMES.md). Call start/end, participant muting and music streaming are not native Bot API features. All reference catalog keys are present in English and Persian; other languages retain English fallback.
