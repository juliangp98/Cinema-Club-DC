# Challenges and tournaments

Members of a club play the same set of its games against each other, with kernels on the line; members
who aren't playing can back a player. Off until an organizer turns it on (Club settings → Games).

## How one works

- **The games** — one game (a versus) or several (a **gauntlet**), each picked or random from the
  club's games that are on (the quiz games, trivia), none twice until each has had a turn; 1–10 questions
  each. Higher or lower is one run per game: a miss ends that game, not the challenge.
- **Everyone gets the identical set.** Each question is made the first time any player reaches it
  (`quizzes.RULES` / `trivia.make_question`) and kept in the challenge, so the others get the same one
  (a compare-and-swap on `challenge.state_json` makes two players arriving at once agree).
- **30 seconds a question.** The clock starts when the question is first shown; an answer after the
  time (plus a 3-second network allowance) is a miss, and a question left open counts as a miss when the
  player comes back.
- **Kernels scored** — like the solo game: 1 a right call, 3 / 2 / 1 by how much of a still or the
  reviews you needed, trivia 1–3 by difficulty. They decide the winner; they aren't added to anyone's
  total themselves.
- **Winner** — one game: the top score takes the pot (a tie splits it; an odd kernel goes to whoever
  finished first). A gauntlet: each game's top scorer wins that game (a tie shares it); most games won
  takes it, then kernels scored, then the least time.
- **Scores** — sealed (nobody sees one until everyone's played) or live (each as that player finishes):
  the creator's choice. You always see your own once you've finished.
- **Decided** when everyone in has played and nobody's left to answer an invite or take a seat; when the
  creator ends it after everyone in has played; or at the deadline (an hour, tonight, or 3 days) —
  anyone who accepted and didn't play scores 0 and loses their stake. Fewer than two players in: called
  off, nothing changes hands. The creator can call it off before anyone has seen a question.
- **Stakes** — 0 (bragging rights) up to the club's limit, the same for every player. You can only put in
  kernels you have that aren't already on the line in other open challenges.
- **Backing** (challenges the club can see, if the club allows it): 1–10 kernels on one player, until the
  first player finishes. Whoever backed a winner splits the backing pot by what they put in (rounding
  leftovers to the earliest backers); if nobody backed a winner, everyone gets theirs back.
- **Rematch / double or nothing** — the same games and players again (the others re-invited), at the same
  or twice the stake (capped by the club's limit).
- **Records and rivalries** — each member's won / lost / streak (the leaderboard's stats, Records on Play),
  and head to head against each other member (member pages).

## Who sees and hears what

- **Who sees it** — the creator picks: the club (Play, the Feed, backing) or just the players.
- **Bell** — invites (they wait for an answer, and Clear leaves them), results for players and backers,
  "X backed you". "New challenges to back" is off until you turn it on. Discord DM, email and push only if
  you chose them for alerts (Settings → Notifications); invite DMs carry Accept / Decline.
- **Discord** — a club-visible challenge is posted in the club's channel if its creator says so on the
  spot (the site's sheet, or `post:` in `/play versus:`); without a choice, their "Challenges I start or
  play" setting decides (Always posts). The post updates as people play and ends with the results; it
  names only members in the server who don't say Never — never a ping.

## Tournaments

Three or more members, a bracket of 1-v-1 challenges (`backend/tournaments.py`).

- **Formats** — the creator picks. **Double elimination** (3–16): seeded, filled to the next power of
  two with byes for the top seeds; a loss drops you to the losers' bracket (each winners' round's losers
  drop in crosswise, so nobody meets who just beat them), a second puts you out; the two brackets'
  champions meet in **one grand final** (no reset match). 3 players: 2 v 3 (1 has a bye), the winners'
  final, the losers' final, the grand final — 2n − 2 real matches in all. **Round robin + final** (3–6):
  everyone plays everyone once (all open at the start); standings by matches won, then kernels scored,
  then seed; the top two meet in the final.
- **Matches** — each is a challenge with `tournament_id`: both players in from the start, no stake or
  backing of its own, the tournament's game set (random games drawn fresh for each match), its scores
  sealed or live. A match opens as soon as both players are known and stays open `match_time` (an hour,
  till tonight, a day). One winner: someone who played beats someone who didn't, then the challenge's
  rank, then less time, then the higher seed; if neither played, the higher seed goes through. Matches
  count in challenge records, rivalries and head-to-head; the club sees them on the bracket, not as
  challenges of their own.
- **Entries** — invitees say yes (their entry is held) or no; open seats for anyone in the club. It
  starts when nobody's left to answer and the seats are filled, when the creator starts it (3+ in), or
  when entries close — short of three, it's called off and nothing changes hands. Seeds: random, or by
  challenge record (wins minus losses).
- **Prizes** — the pot (entry × entrants): winner takes all, or 60 / 30 / 10 (what rounding leaves goes
  to the champion; a place nobody holds, too). Third: the losers' final's loser, or the round robin's
  third. Members not playing back an entrant to win it all until the first real match is decided
  (parimutuel, as challenges). Titles show in Records.
- **Hearing about it** — the same settings as challenges: an invite (I'm in / Decline by DM if chosen),
  "your match is ready" (it waits in the bell until you play; ▶ Play by DM if chosen), the results;
  "new tournaments to join or back" with "new challenges to back". The channel post shows the bracket so
  far and updates as matches are decided.

## Scouting: who to challenge, and a roast

`backend/scout.py`, at the top of Play's Challenges (and `/play challenges: Who should I challenge?`):

- **Stats** — the club's (most wins, kernels won, the hottest streak, tournament titles, the biggest pot,
  the fiercest rivalry, the favorite game, how much has changed hands) and yours (record, win rate, your
  nemesis and favorite victim, your best game, your biggest win).
- **Picks** — every other member, best first: their kernels next to yours, their record and win rate,
  how you've done against them, their best and worst game; a tag (grudge match, fresh meat, streak
  breaker, top dog, big fish, easy pickings, dead even) with the reasons; a game (the one you win more
  often than they do, else their weakest) and a stake (both of you can afford it).
- **Habits** — only what the club already sees: club screenings (when, where), the watchlist and how much
  of it they've seen, "going" and then missing it, trivia; their taste only if they show it; their
  Letterboxd diary only if they connected one (star ratings only if they share them).
- **Roasts** — the AI writes one from those habits, never told a name (it writes about THEM and YOU,
  filled in after); kept for the day, three a day per pair; without the AI, a line from the facts.
  Members can switch roasts off ("Fair game for challenge scouting", Settings → Privacy) — then only
  their numbers show.

## Code

| Where | What |
|---|---|
| `backend/challenges.py` | The rules: games and rounds, questions, the clock, deciding and paying out, kernels, records, what each viewer sees, notifications, the Discord post; `open_match` for a tournament's match |
| `backend/tournaments.py` | Brackets (`double_bracket`, `league`), entries and seeds, advancing (byes, opening matches, one winner each), prizes and backing, records' titles, notifications, the Discord post |
| `backend/scout.py` | The stats, the picks, the habits and the roast |
| `backend/routes/challenges.py` | The site's API: `/api/challenges` (list, create), `/api/challenges/<id>` and its actions (respond, join, back, cancel, end, games, rematch), `/play`, the still images, `/rivals`, `/scout` and `/scout/<user>/roast` |
| `backend/routes/tournaments.py` | `/api/tournaments` (options, list, create), `/api/tournaments/<id>` and its actions (respond, join, back, start, cancel) |
| `backend/routes/internal/challenges.py`, `tournaments.py` | The bot's API — the same functions |
| `frontend/src/components/Challenges.jsx` | Play's Challenges arena, the card (also the Feed's), the new-challenge sheet; the shared game set, people picker, Discord choice and backing panel |
| `frontend/src/components/ChallengeScout.jsx` | The stats and "Who should you challenge?" — roasts, habits, a challenge pre-filled |
| `frontend/src/components/Tournaments.jsx` | The tournament card, the new-tournament sheet, the bracket |
| `frontend/src/pages/ChallengePage.jsx` | A challenge's page: actions, the ballot and clock (the quiz games' round components), backing, results |
| `frontend/src/pages/TournamentPage.jsx` | A tournament's page: entries, your match, backing, the bracket |
| `bot/features/challenges.py` | `/play versus:` and `challenges:` (incl. scouting and roasts), the buttons, the gauntlet's game picker, the channel post, invite and match DMs |
| `bot/features/tournaments.py` | `/play tournament:`, a tournament's buttons and channel post, invite DMs |

Tables: `challenge` (its games and questions in `state_json`; `tournament_id` for a match),
`challenge_player` (each player's status, progress, score, time, `net` once decided), `challenge_bet`;
`tournament`, `tournament_player` (seed, place, `net`), `tournament_match` (where each side comes from,
who's in it, its challenge, the winner), `tournament_bet`; `user.roastable`. Deadlines and entries are
swept with the polls' (`app.close_due_polls`). Tests: `tests/backend/test_challenges.py`,
`test_tournaments.py`, `test_scout.py`, `tests/bot/test_bot_challenges.py`, `test_bot_tournaments.py`,
`frontend/tests/challenges.test.jsx`, `tournaments.test.jsx`.
