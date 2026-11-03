# Challenges

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

## Code

| Where | What |
|---|---|
| `backend/challenges.py` | The rules: games and rounds, questions, the clock, deciding and paying out, kernels, records, what each viewer sees, notifications, the Discord post |
| `backend/routes/challenges.py` | The site's API: `/api/challenges` (list, create), `/api/challenges/<id>` and its actions (respond, join, back, cancel, end, games, rematch), `/play`, the still images, `/rivals` |
| `backend/routes/internal/challenges.py` | The bot's API — the same functions |
| `frontend/src/components/Challenges.jsx` | Play's section, the card (also the Feed's), the new-challenge sheet |
| `frontend/src/pages/ChallengePage.jsx` | A challenge's page: actions, the ballot and clock (the quiz games' round components), backing, results |
| `bot/features/challenges.py` | `/play versus:` and `challenges:`, the buttons, the gauntlet's game picker, the channel post, invite DMs |

Tables: `challenge` (its games and questions in `state_json`), `challenge_player` (each player's status,
progress, score, time, `net` once decided), `challenge_bet`. Deadlines are swept with the polls'
(`app.close_due_polls`). Tests: `tests/backend/test_challenges.py`, `tests/bot/test_bot_challenges.py`,
`frontend/tests/challenges.test.jsx`.

## Next: tournaments (Phase 2)

Planned: brackets of 1-v-1 challenges for 3+ players — double elimination (byes for the top seeds, a
losers' bracket, one grand final) or round robin plus a final — with per-round deadlines and a payout of
winner-takes-all or 60 / 30 / 10.
