// The page tours (7f): what each page can do, 3–6 spotlight steps on its real
// widgets, then a card to that page's part of Help (`help`: a Help section or
// topic id). Offered once per page (a card under its header), replayable from
// its ? button. Steps whose target isn't on screen (no club, a game that's
// off, phones) are skipped, as in the welcome tour.
// Which tour the page at `pathname` has (the ? in the top bar), or null.
const ROUTES = [[/^\/$/, "discover"], [/^\/calendar$/, "calendar"], [/^\/browse$/, "browse"], [/^\/theatres\/[^/]+$/, "theatre"],
                [/^\/films\/[^/]+$/, "film"], [/^\/feed$/, "feed"], [/^\/play$/, "play"], [/^\/club$/, "club"],
                [/^\/polls\/(?!new$)[^/]+$/, "poll"], [/^\/me$/, "me"]];
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
      body: "＋ Watchlist it — even before it's booked — and you can hear when a theatre books it or tickets go on sale." },
    { target: ".film-club", title: "Your club", body: "Who's going, who wants to see it, and who's seen it." },
    { target: ".film-venues", title: "Where it's playing", body: "Pick a theatre to see just its showings." },
    { target: ".film-days", title: "Pick a showing", body: "Tap a time to RSVP, see who's going and discuss it." },
  ] },
  feed: { title: "the feed", help: "feed", steps: [
    { target: "#feed-filters", title: "What to show", body: "Everything, or just plans, check-ins, comments, polls or games." },
    { target: ".feed-card", title: "The club's activity",
      body: "Plans, check-ins and comments, newest first, with a marker for what's new since you were last here." },
    { target: ".feed-kernels-btn", title: "Give kernels",
      body: "Reward what someone did on a screening — 10 to give and 3 to take each week." },
    { target: ".games-rail, .feed-strip", title: "Waiting for you", body: "Today's trivia, polls to vote in, and your kernels." },
  ] },
  play: { title: "Play", help: "games", steps: [
    { target: "#trivia", title: "Trivia", body: "The question of the day — one try, 1 to 3 kernels by how hard it is — and anytime questions if your club allows them." },
    { target: "#bingo", title: "Repertory bingo", body: "This month's card fills in by itself from your check-ins — and under it, everyone's. Tap one to see their squares." },
    { target: "#polls", title: "Polls", body: "Vote in the open ones; past ones show their results and who called it." },
    { target: "#games", title: "More games", body: "Higher or lower, Who said it, Guess the still and more — the ones your club has on." },
    { target: '[data-tab="records"]', title: "Records", body: "Your game records, everyone's (sort by any game), and the club's — this month, this year or all time." },
  ] },
  club: { title: "the Club page", help: "club", steps: [
    { target: ".club-hero", title: "Your club", body: "Its theatres, how many members, and your role." },
    { target: ".club-page [role=tablist]", title: "Tabs",
      body: "The overview, every member, the leaderboard — and for organizers and admins, the club's settings." },
    { target: ".club-panel", title: "The overview", body: "This week's plans, recent activity, the month's numbers and your games." },
  ] },
  poll: { title: "a poll", help: "polls", steps: [
    { target: ".pv-tabs", title: "Vote or see results", body: "Switch between your ballot and how everyone voted." },
    { target: ".pv-progress", title: "Your progress", body: "Picks save as you go — finish any time before voting closes." },
    { target: ".pv-jump", title: "Categories", body: "Jump to any category; the filled dots are ones you've picked." },
    { target: ".pv-manage", title: "Running the poll", body: "Organizers close voting, mark the winners and award the kernels here." },
  ] },
  me: { title: "the Me page", help: "lists", steps: [
    { target: ".me-card", title: "You", body: "Your picture, name and a line about you, as your clubs see them." },
    { target: "#me-lists", title: "Your lists", body: "Your watchlist (📓 marks films from Letterboxd), what you're going to and your watch history." },
    { target: '[data-tab="settings"]', title: "Settings", body: "Your profile and taste, notifications, Discord, Letterboxd (your diary, and your watchlist brought in) and calendar links, privacy — all in one place." },
    { target: ".me-links", title: "Your club, and more", body: "The Club page, theatres, other clubs, the tour and Help." },
  ] },
};
