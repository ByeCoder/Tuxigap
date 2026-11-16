# Make Tuxigap feel at home

English is the default and reference catalog. The bot and dashboard offer 15 language choices: English, Persian, Chinese, Russian, Hebrew, Spanish, French, Arabic, German, Turkish, Portuguese, Hindi, Japanese, Korean and Italian.

## Choose your language

- Private chat: `/language` or `/language CODE` changes your own private interface.
- Group chat: the same command changes that group's interface and requires a current admin.
- Dashboard: the header selector changes this browser page; the group-language control changes the selected Telegram community.
- `he` means Hebrew. The legacy `iw` alias normalizes to Hebrew internally.
- Persian, Arabic and Hebrew switch the dashboard to right-to-left layout.

English is selected until you explicitly choose another language. Telegram's account language isn't silently imposed on a group.

## What is translated

The English catalog covers the extracted bot UI and messages. Persian now covers every key in the English reference catalog, including new staff/help/dashboard messages. The other catalogs localize core menus, analytics labels, common actions, language choices and selected member/payment messages. **In the other 13 catalogs, some advanced prompts, error explanations, games and newer features still fall back to English.** Choosing a language doesn't disable features, but it isn't a claim of complete professional translation.

Custom rules, welcome text, posts, note content, user names, historical audit reasons and source code tokens aren't automatically translated. Built-in defaults follow the active language. AI answers and generated quizzes are instructed to use the group's selected language, subject to the provider's response.

Studio is a separately maintained upstream companion; its languages and translation coverage are independent of Tuxigap's catalogs.

## Help us improve a catalog

1. Open `tuxigap/locales/en.json` as the reference.
2. Copy a missing key into the desired locale file and translate its value in a warm, clear voice.
3. Keep names, URLs, HTML structure and interpolation fields such as `{p0}`, `{name}` and `{p1:,}` intact.
4. Don't translate command tokens, database keys, API names or identifiers.
5. Run `python tools/check_translations.py` and the tests.

Catalogs are loaded offline. No runtime translation service receives your members' messages. Missing keys use English; invalid interpolation uses the safe English template.

Language state uses Python ContextVar so concurrent groups and payment processing don't overwrite each other's language. Private payment delivery reads the purchaser's chosen private-chat language.
