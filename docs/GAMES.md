# Bring the group into the game

`/play` still offers quizzes, dice, rock-paper-scissors, truth/dare, playful fortunes, daily rewards, profiles, referrals and the original jokes. The **Group games** button or `/party` adds five shared rounds:

| Command | How everyone plays |
|---|---|
| `/party number` | Guess a secret number from 1–100; each player gets five tries and higher/lower hints |
| `/party scramble` | Find an English word from shuffled letters; five tries each |
| `/party riddle` | Race to solve a short English riddle; five tries each |
| `/party math` | Be first to solve a multiplication challenge; five tries each |
| `/party wordchain` | Alternate English words, starting each with the previous word's final letter; no repeats |

Use `/guess ANSWER` or `/answer ANSWER`. One round runs per group for five minutes. A creator or authorized event staff can stop it with `/stopgame`. Existing content moderation also applies to game messages. Switching community activities off blocks play.

The first correct puzzle answer wins **20 XP and 10 game coins**. An accepted word-chain turn earns **3 XP and 1 game coin**. Word chain stops at 30 words, including its opening word, or at the five-minute deadline. It checks letters, turn order and repeats, but **does not use a dictionary**; it is a social game, not a language exam.

`/scores` shows the 15 highest group-game point totals. `/top` is the broader community XP leaderboard; `/rank` shows progress through the owner's title ladder. Game state, attempts and scores survive a normal restart. Puzzle resolution and rewards are committed in one database transaction, so two answers cannot win the same round.

## A few jokes for the road

Try `/jokes tech`, `/jokes animals`, or `/jokes everyday`. `/jokes` without a category picks one for you. These bonus packs contain 15 light English jokes; the original `/joke` remains localized where its catalog is translated. Word/riddle content in the new shared rounds is also English so players see the same puzzle; the controls and feedback follow the group's catalog.

There are no entry fees, cash bets, cash-outs or conversions to Stars. Giveaway prizes remain free-entry community activities fulfilled by their admins.
