# A smile in your own language

Tuxigap now includes **240 offline jokes in 15 languages**:

- **80 Persian jokes**, written around everyday life, technology, student life, work and animals.
- **30 English jokes** across the same five categories.
- **10 each** in Chinese, Russian, Hebrew, Spanish, French, Arabic, German, Portuguese, Turkish, Hindi, Japanese, Korean and Italian.

These are small friendly packs, not a promise that every line will land in every community. Several international lines adapt the same everyday themes into their own language. No joke service receives your members' messages, and no scraping or runtime translation is needed.

## Find your kind of joke

```text
/joke
/jokes fa
/jokes fa student
/jokes en tech
/jokes any
/jokelanguages
/jokedefault fa
```

Without a language, jokes follow the group’s selected language or your personal interface initially. A current group admin can use `/jokedefault fa` to make jokes Persian while keeping the interface English; private users can set their own default. Use `any` for mixed languages or `auto` to return to following the interface. An explicit language changes only the joke; it does not change the interface. `any` chooses a language at random. Category names are stable command tokens: `everyday`, `tech`, `student`, `work`, `animals`.

A deck tracks what that chat has already seen. It avoids repeating a joke until the selected language/category has been used, and avoids an immediate repeat when it has another choice. Each community/private chat has its own deck. Some smaller translated categories contain only one joke; community submissions can expand them.

Use **Another one** and **Joke languages** below a joke. The like/save buttons count each member's action once. `/joketop` shows the most-liked jokes in that chat, and `/jokefavorites` shows your own saved jokes there. Neither awards cash or game currency. The existing activity switch disables joke commands and old joke buttons too.

## Let members contribute

```text
/jokesuggest fa | everyday | متن جوک پیشنهادی شما
/jokereview
```

Suggestions need a supported language/category and 10–700 characters. One member may submit once every two minutes, with up to 100 pending suggestions per community. A current Telegram moderator with delete rights, or an owner-appointed bot moderator/manager, reviews the newest pending items through private approve/reject buttons. They must have started the bot privately to receive that review inbox.

Only approved suggestions join **that community's** deck. Another community cannot use its review buttons or access its local joke through a copied ID. Personal favorites and submitted jokes are removed by confirmed `/forget`; pending/rejected suggestions follow the normal retention period. Approved suggestions remain until removed by their author's erasure request or operator review; preserve your database backup as appropriate.

All joke text is escaped before sending. A suggestion cannot add raw HTML, buttons, code execution or admin privileges. Please keep contributions kind and suitable for your community.
