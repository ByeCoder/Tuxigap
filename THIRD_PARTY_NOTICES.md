# Tuxigap credits and third-party notices

Thank you to the people whose work made this toolkit possible. Please keep these notices when sharing it.

## Tuxigap

Copyright © 2026 ByeCoder and Tuxigap contributors.

The combined v0.3.0 distribution is GPL-3.0-only. Earlier original Tuxigap v0.2 code was released under MIT; that notice is preserved at `third_party/tuxigap-v0.2/LICENSE`. This release doesn't revoke the rights granted for earlier revisions.

## Code adapted into the native core

| Upstream and original authors | Original path | Tuxigap path | Preserved license |
|---|---|---|---|
| Black-Bulls-Bots / Zero Two contributors; upstream credits also acknowledge SaitamaRobot | `zerotwobot/modules/fun_strings.py` | `tuxigap/ported/fun.py` | `third_party/zero/LICENSE` · GPL v3 |
| Astrako / AstrakoBot contributors; upstream credits PaulSonOfLars and AnimeKaizoku | `AstrakoBot/modules/shout.py` | `tuxigap/ported/fun.py` | `third_party/astrako/LICENSE` · GPL v3 |
| sametcn99 / tg-bot-studio contributors | `src/server/modules/locks/lock-evaluator.ts` | `tuxigap/ported/locks.py` | `third_party/studio/LICENSE` · GPL v3 |

Adaptations use bounded text output, a small safe selection of fun strings, Python message dictionaries, proper UTF-16 entity offsets and scoped strict-domain allowlists. We did not import the legacy remote-eval/shell/developer handlers or hard-coded privileged-user behavior. The modifications are identified in the adapted files.

Exact source revisions are recorded in `third_party/upstream-lock.json`. You can obtain their complete corresponding upstream source at the repository/commit URLs listed there.

## Optional service integrations

- **umputun/tg-spam**: real upstream Docker service, connected through its HTTP `/check` and sample APIs. Upstream MIT notice is preserved at `third_party/tgspam/LICENSE`. No Go detector code is relabeled as native Python implementation.
- **sametcn99/tg-bot-studio**: optional complete upstream application, built from a pinned public Git commit with its own Dockerfile, source and GPL license. It remains a companion, with independent tokens, credentials, data and application behavior.
- **redstone-md/shield**: an additional architectural reference for human-reviewed multimodal moderation. No Shield source is copied and no complete Shield deployment is bundled. The native opt-in vision adapter is Tuxigap code.

## Other dependencies

Python dependencies retain their own licenses. `httpx`, `python-dotenv`, `tzdata`, optional `ruff` and optional `playwright` are installed through package metadata; they aren't copied into this source tree. Studio and the spam-engine container retain their upstream dependency notices.


## Optional music dependencies (0.5)

The original Tuxigap adapter imports public interfaces from **PyTgCalls 3.0.1**, **NTgCalls 3.0.7** and **Telethon 1.45.0**. PyTgCalls and NTgCalls are LGPL-3.0-or-later; Telethon is MIT. Their preserved notices are in `third_party/pytgcalls`, `third_party/ntgcalls`, and `third_party/telethon`. Package wheels include dependency notices too. No historical music-bot handlers or shell/eval commands were copied into Tuxigap. FFmpeg is installed as a separate system package in the optional image, under its distribution's own build/license terms.

Verified PyTgCalls interface source: [commit 8a4310a658af6426a09eb6cd33ef489550ed0d67](https://github.com/pytgcalls/pytgcalls/tree/8a4310a658af6426a09eb6cd33ef489550ed0d67), declaring version 3.0.1. See [music setup](docs/MUSIC.md) and the offline dependency contract check.

The new multilingual joke packs are a small Tuxigap-maintained collection, with original relatable Persian lines and adaptations of common short everyday humor. They are not scraped from an external joke service.
