// The page tours (7f): what each page can do, 3–6 spotlight steps on its real
// widgets, then a card to that page's part of Help (`help`: a Help section or
// topic id). Offered once per page (a card under its header), replayable from
// its ? button. Steps whose target isn't on screen (no club, a game that's
// off, phones) are skipped, as in the welcome tour.
// Which tour the page at `pathname` has (the ? in the top bar), or null.
const ROUTES = [[/^\/$/, "discover"], [/^\/calendar$/, "calendar"], [/^\/browse$/, "browse"], [/^\/theatres\/[^/]+$/, "theatre"],
                [/^\/films\/[^/]+$/, "film"], [/^\/feed$/, "feed"], [/^\/play$/, "play"], [/^\/play\/challenges$/, "play-challenges"], [/^\/club$/, "club"],
                [/^\/polls\/(?!new$)[^/]+$/, "poll"], [/^\/challenges\/[^/]+$/, "challenge"], [/^\/tournaments\/[^/]+$/, "tournament"],
                [/^\/me$/, "me"]];
export const tourFor = pathname => ROUTES.find(([re]) => re.test(pathname))?.[1] || null;

export const PAGE_TOURS = {
  discover: { title: "Discover", help: "finding", steps: [
    { target: "#site-search", title: "Search, or just ask",
      body: "Type a film, person, theatre or genre — or describe what you're in the mood for (\"a 70mm epic this weekend\") and tap ✨." },
    { target: "#shelf-for-you", title: "For you",
      body: "Films in the next two weeks that fit Your taste, each with why. Tap “Not for me” on any that miss." },
    { target: "#surprise", title: "Surprise me",
      body: "One pick for tonight, tomorrow or the weekend — spin again for another." },
    { target: ".club-week", title: "This week in the club",
      body: "What your club's going to, wants to see and is voting on." },
    { target: ".discover .shelf:not(#shelf-for-you)", title: "Shelves",
      body: "Rare screenings, film prints, last chances, spotlights and double features. “See all” opens each in Browse." },
  ] },
  calendar: { title: "the Calendar", help: "plans", steps: [
    { target: ".cal-bar", title: "Your view",
      body: "Agenda, week or month; step through time, or open Filters for theatres, formats and times of day." },
    { target: "#calendar-filters", title: "Quick filters",
      body: "One tap for tonight's late shows, film prints, what the club's going to, and more." },
    { target: "#calendar-tickets", title: "Tickets",
      body: "Hide sold-out showings, or see what's announced but not on sale yet (Coming soon)." },
    { target: ".cal-tile, .cal-time", title: "Make a plan",
      body: "Tap any showing to RSVP Going or Maybe, see who's going, and discuss it with the club." },
  ] },
  browse: { title: "Browse", help: "search", steps: [
    { target: ".browse-when", title: "When", body: "Tonight, this weekend, the next two weeks or the month." },
    { target: "#browse-tickets", title: "Tickets", body: "All, available, sold out, or coming soon." },
    { target: "#browse-filters", title: "Filters, sort and alerts",
      body: "Theatre, region, on film, decade, genre, mood and more. 🔔 Alert me saves the search: you'll hear when a theatre books a film that fits." },
    { target: ".browse .poster-grid", title: "The films", body: "Each with its next showing. Every view is a link you can share." },
  ] },
  theatre: { title: "this theatre's page", help: "film-theatre-pages", steps: [
    { target: ".theatre-where", title: "Getting there", body: "The address, maps and the theatre's own site." },
    { target: ".theatre-notes", title: "What members say",
      body: "Notes from your club's check-ins here — gorgeous prints, sound trouble, great Q&As." },
    { target: "#shelf-for-you", title: "For you here", body: "What's playing here that fits Your taste." },
    { target: ".theatre-page .browse-tickets", title: "Everything in the next month",
      body: "Filter by tickets, or open the whole month in Browse." },
  ] },
  film: { title: "a film's page", help: "film-theatre-pages", steps: [
    { target: ".film-actions", title: "Keep track",
      body: "＋ Watchlist it, even before it's booked, and you can hear when a theatre books it or tickets go on sale." },
    { target: ".film-club", title: "Your club", body: "Who's going, who wants to see it, and who's seen it." },
    { target: ".film-venues", title: "Where it's playing", body: "Pick a theatre to see just its showings." },
    { target: ".film-days", title: "Pick a showing", body: "Tap a time to RSVP, see who's going and discuss it." },
  ] },
  feed: { title: "the feed", help: "feed", steps: [
    { target: "#feed-filters", title: "What to show", body: "Everything, or just plans, check-ins, comments, polls, games or the Monday digests." },
    { target: ".feed-card", title: "The club's activity",
      body: "Plans, check-ins and comments, newest first, with a marker for what's new since you were last here." },
    { target: ".feed-kernels-btn", title: "Give kernels",
      body: "Reward what someone did on a screening — 10 to give and 3 to take each week." },
    { target: ".games-rail, .feed-strip", title: "Waiting for you", body: "Today's trivia, polls to vote in, and your kernels." },
  ] },
  play: { title: "Play", help: "games", steps: [
    { target: ".play-turn", title: "Your turn", body: "Everything waiting on you, with one button each: today's trivia question, polls to vote in, challenge invites, your matches." },
    { target: ".play-tiles", title: "Every game", body: "A tile for each part of Play, with what's new in it. Tap one for its page." },
    { target: ".route-tabs", title: "Play's pages", body: "Challenges, trivia, bingo, polls, the quiz games, records and your kernels, each on its own page." },
    { target: ".play-side, .play-strip", title: "Your kernels", body: "Your kernels as you earn them, what's left to earn today, this month's board and this week's movers." },
  ] },
  "play-challenges": { title: "Challenges", help: "challenges", steps: [
    { target: ".ch-head", title: "Start one", body: "Challenge members to a game or a gauntlet for a pot of kernels, or start a tournament for three or more." },
    { target: ".ch-arena", title: "Your record", body: "Your wins and losses, your nemesis and your best game, and the club's best." },
    { target: ".ch-scout", title: "Who to challenge", body: "Picked by your record, theirs and the kernels, with a game to try. Compare habits, or ask for a roast 🔥." },
  ] },
  club: { title: "the Club page", help: "club", steps: [
    { target: ".club-hero", title: "Your club", body: "Its theatres, how many members, and your role." },
    { target: ".club-page [role=tablist]", title: "Tabs",
      body: "The overview, every member, the leaderboard — and for organizers and admins, the club's settings." },
    { target: ".club-panel", title: "The overview", body: "This week's plans, recent activity, the month's numbers and your games." },
    { target: "#settings-theatres", title: "Theatres and the digest",
      body: "The Monday digest (the week's picks at 10, in the Feed, the bell and Discord), the theatres the club follows — and, once the site covers more than one city, its home city." },
    { target: "#settings-discord", title: "Discord",
      body: "The club's Discord server: admins connect it here (Add to Discord, then /setup with a code), and the bot posts what the club chooses." },
  ] },
  poll: { title: "a poll", help: "polls", steps: [
    { target: ".pv-tabs", title: "Vote or see results", body: "Switch between your ballot, how everyone voted (with the answers once they're in — all at once, or live as they come) and the standings." },
    { target: ".pv-progress", title: "Your progress", body: "Picks save as you go — finish any time before voting closes. In a live poll, a category locks once its answer is in." },
    { target: ".pv-jump", title: "Categories", body: "Jump to any category; the filled dots are ones you've picked." },
    { target: ".pv-manage", title: "Running the poll", body: "Organizers close voting, set the answers, finalize them (kernels to everyone's totals) and edit the poll here." },
  ] },
  challenge: { title: "a challenge", help: "challenges", steps: [
    { target: ".ch-actions", title: "Your move", body: "Accept, take a seat, or play — 30 seconds a question, the same questions as everyone else." },
    { target: ".ch-players", title: "Who's in", body: "Everyone's status, and the scores — as each finishes, or only at the end, as the challenge says." },
    { target: ".ch-backing", title: "Back a player", body: "Not playing? Put kernels on who'll win, until the first player finishes." },
  ] },
  tournament: { title: "a tournament", help: "tournaments", steps: [
    { target: ".ch-actions", title: "Your move", body: "Join, take a seat — or, once it's under way, play your match: a 1-v-1 challenge, 30 seconds a question." },
    { target: ".ch-players", title: "Who's in", body: "Seeds, who's still alive and, at the end, the medals and the prizes." },
    { target: ".ch-backing", title: "Back a winner", body: "Not playing? Put kernels on who'll win it all, until the first match is decided." },
    { target: ".tour-bracket", title: "The bracket", body: "Every match: winners' and losers' brackets and the grand final — or the round robin's standings and its final. Tap a match to watch or play it." },
  ] },
  me: { title: "the Me page", help: "lists", steps: [
    { target: ".me-card", title: "You", body: "Your picture, name and a line about you, as your clubs see them." },
    { target: "#me-lists", title: "Your lists", body: "Your watchlist (📓 marks films from Letterboxd), what you're going to and your watch history." },
    { target: '[data-tab="settings"]', title: "Settings", body: "Your profile and taste, notifications, Discord, Letterboxd (your diary, and your watchlist brought in) and calendar links, privacy — all in one place." },
    { target: ".me-links", title: "Your club, and more", body: "The Club page, theatres, other clubs, the tour and Help." },
  ] },
};
