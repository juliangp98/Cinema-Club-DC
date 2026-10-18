import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import useHashScroll from "../useHashScroll";
import PageHeader from "../ui/PageHeader";
import { useShell } from "../shell/AppShell";

// The help guide (R11): one searchable page, a section per area of the site,
// each a few questions with short answers. Deep links: /help#kernels etc.
// Keep it in step with the site — if a feature changes, change its answer.

const SECTIONS = [
  { id: "start", title: "Getting started", items: [
    ["What is Cinema Club DC?", "Everything playing at the DC area's independent and repertory theatres — AFI, Suns, Alamo, the Smithsonian and more — in one place, plus a club to plan outings with: who's going, what to see, and what you thought."],
    ["Do I need an account?", "No — anyone can browse. The first time you RSVP, add to a watchlist or react, you get a private guest profile in this browser. Keep it by adding an email or signing in with Discord (account menu → Keep your profile); otherwise it stays on this device only."],
    ["How do I sign in?", "With an email link (no passwords — we send you a link that signs you in) or with Discord."],
    ["How do clubs work?", "A club picks the theatres it follows, and its members see each other's plans, comments and games. Find or start one on the Clubs page; asking to join sends a request a club admin approves. In more than one club? Switch from the top bar."],
    ["How do I leave a club?", "Club page → Members → Leave this club. You stop seeing its plans, feed and games; your own lists and history stay yours, and you can ask to join again later. A club's only admin has to make someone else an admin first."],
    ["What can each club role do?", "Read-only members see the club. Members RSVP, vote, comment and play. Organizers also run polls, the club's theatres and games (which are on, what they post in Discord, and okaying those posts) and answer join requests. Admins can do all that, plus the club's name and picture, invites, roles and removing members."],
  ] },
  { id: "finding", title: "Finding films", items: [
    ["Where do I start?", "Discover shows what's worth seeing over the next two weeks: rare screenings and film prints, spotlights, double features, what the club wants to see, and more. 'Surprise me' picks one for you."],
    ["How do I search or filter?", "Type in the search box for films, people, theatres or genres — or describe what you want (\"a 70mm epic this weekend\") and tap ✨. Browse has the full filters: theatre, region, on film, time of day, rarity, decade, genre, mood and more. Every Browse view is a link you can share."],
    ["Can I hide sold-out showings — or see what's coming?", "Use the ticket chips on the Calendar, Browse and each theatre's page (or Filters → Tickets): All, Available, Sold out, or Coming soon. All and Coming soon also show films a theatre has announced but isn't selling tickets for yet, on the day it expects them (“Tickets soon”) — watchlist one to hear the moment tickets go on sale. Discover's suggestions only ever pick showings you can still get into."],
    ["What's on a film or theatre page?", "A film page has every showing, ratings, cast and the trailer. A theatre page has what's on, a map, and — if your club uses screening notes — what members say about the screenings there."],
  ] },
  { id: "plans", title: "Making plans", items: [
    ["How do I RSVP?", "Tap a screening and choose Going or Maybe. Your club sees who's going; tap again to change or remove it. From the screening you can also discuss it with the club (and its Discord thread, if it has one)."],
    ["What's “Did you make it?”", "After a screening you said you were going to, you're asked whether you went. Checking in keeps your watch history right and earns kernels."],
    ["Can I see my plans in my own calendar?", "Yes — Me → In your calendar: subscribe once in Google Calendar or Apple / Outlook and your plans (or the club's) stay in sync. Anyone with the link can see it, so keep it to yourself; New link turns the old one off."],
  ] },
  { id: "lists", title: "Your lists", items: [
    ["What's the watchlist for?", "Films you want to see — even ones that aren't playing yet. When a theatre books (or announces) one, you can get an alert; your club can see what you want to see too."],
    ["Where are my plans and history?", "On the Me page: your watchlist, what you're going to, and your watch history. Tap anyone's picture or name to open their page — its Compare shows what you both want to see and are going to."],
  ] },
  { id: "taste", title: "Your taste", items: [
    ["What is Your taste?", "What you like, so the site can pick films for you: genres you love and ones you're not into, how you like to watch (on film, 70mm and IMAX, Q&As, classics, late shows…), favorite theatres, and favorite films, directors, actors and writers. Pick as much or as little as you like."],
    ["Where do I set it?", "Edit profile → Your taste (it's also offered at the end of the welcome tour). Changes save as you make them. Genres can also be picked in Discord with /profile."],
    ["Who can see my taste?", "Only you, unless you switch on “Show my taste on my profile” — then people in your clubs see it on your profile and with /profile in Discord."],
    ["What's “For you”?", "A row near the top of Discover (and “For you here” on each theatre's page) with films playing in the next two weeks that fit your taste — each says why: a favorite director, a genre you love, on 35mm, at a theatre you like. It also learns from what you watchlist, plan, see and rate well on Letterboxd. Films you've already seen are left out. Theatres shows how many are for you at each one."],
    ["A pick isn't for me — can I get rid of it?", "Tap “Not for me” under it: it's gone from For you. You'll find it under Not for me in Your taste if you change your mind."],
    ["What does “Not into” do?", "Films in a genre you're not into rank lower — they only show up when something else about them is a strong fit (say, a favorite director's)."],
    ["Will I hear when a favorite's film is booked?", "Yes — when a theatre books one of your favorite films, or a film by a director, actor or writer in Your taste, it lands in the 🔔 bell (by DM, email or push too only if you've turned those on). Switch it off under Notification settings → A favorite's film is booked."],
    ["What's taste match?", "If someone shows their taste, their profile (and Compare, and /compare in Discord) shows how alike your tastes are, and what you both love."],
    ["Can I see my picks in Discord?", "Yes — /foryou shows your For you picks privately, with why each one is there."],
    ["Which genres are there?", "The ones TMDB and IMDb use for films — action to western, plus film noir, musical, biography and sport — so what you pick matches how every film is labelled."],
  ] },
  { id: "club", title: "Your club", items: [
    ["What's in the feed?", "What the club's been up to: plans, check-ins, comments, watchlist adds, polls and games, newest first, with a marker for what's new since your last visit and a recap every Monday. Filter it by kind at the top. On wide screens a side panel shows what's waiting for you; on phones it's the row of chips."],
    ["What's on the Club page?", "An overview (this week, recent activity, the members, the month's numbers and your games), every member as a tile (tap one for their page), the leaderboard, and — for organizers and admins — the club's settings (admins also find the style guide there: every button, chip and panel the site uses)."],
    ["How does the leaderboard work?", "Switch between this month, this year and all time: kernels count in the period they were earned, shown as a bar by where they came from. Tap Stats on anyone for their screenings, film prints, theatres, late shows, crew nights, streaks, trivia and bingo. The period's titles — Night owl, Purist, Explorer, Early bird, Critic, Sharpshooter, Regular — go to whoever leads once they reach a minimum."],
    ["What are screening notes?", "If your club turns them on, people who checked in to a screening can tag the night — gorgeous print, sound trouble, packed house, great Q&A… They show on the screening, in the feed, and on theatre pages."],
  ] },
  { id: "games", title: "Play: polls, trivia, bingo and kernels", items: [
    ["Where are the games?", "On the Play page (Play in the menu), beside your kernels, this month's standings and this week's movers. Every poll is there — open ones to vote in, and past ones with their results; trivia and bingo appear once a club organizer or admin turns them on in Club settings."],
    ["How do polls work?", "Pick your answers before a poll closes. Some polls are scored once the results are in: single picks, confidence (stake 1–10 kernels on each pick) or ranked. Organizers and admins make polls (＋ New poll on Play)."],
    ["How does trivia work?", "A question of the day for the whole club (+2 kernels for a right answer), and — if your club allows it — anytime questions whenever you like (+1 each, up to 5 a day). One try each. Questions come from the films on the calendar and classic movie quotes."],
    ["How does repertory bingo work?", "One card a month for the club, filled in by itself from your check-ins: on film, before 1960, a late show, a theatre you'd never been to… The middle is free. A first line is +5 kernels, the full card +15 more."],
    ["Do the games post in the club's Discord?", "Only if a club organizer or admin says so, in Club settings → Discord: the question of the day and each month's bingo card can be Never, Ask first or Always, and bingo wins Never or Always. With Ask first, an organizer or admin sees the post exactly as it'll look (on the site, or by DM) and can post it, skip it, swap the question or reshuffle the card — if nobody does, it isn't posted. Skipped one by mistake? Post it after all (on Play, in Club settings or from the DM) until 10 PM for the question, or the month's end for the card. Posts never ping anyone."],
    ["Can organizers get join requests by email?", "Yes, if they want them: 🔔 → Notification settings → Someone asks to join your club. It's off until you turn it on (admins always get one). Requests also wait in Club settings → Members & roles."],
    ["Will a bingo win post name me?", "Only if your Edit profile → Sharing to Discord says Always for My game wins (it starts at Never) — otherwise the post just says someone got bingo."],
    ["Can I get reminders about the games?", "Yes, each one your own choice in Notification settings: the question of the day is up, yesterday's answer, a new bingo card, and your own bingo (that one's on in the bell to start with). By DM, email or push only if you've turned those on."],
    ["How do I earn kernels?", "Check in after a screening (+5, and +2 more if you'd said you were going); be the first to say you're going to a screening others join (+1 each, up to 5); crew nights where 3+ members went (+3 each); right picks in scored polls; trivia and bingo; and kernels other members give you."],
    ["Can I give kernels to people?", "Yes — tap 🍿 Kernels on a screening in the feed. Each week you have 10 to give and 3 to take (up to 3 to a person per screening, or take 1). Nobody loses more than 5 a week or goes below zero, and it always shows who gave or took."],
  ] },
  { id: "alerts", title: "Notifications and alerts", items: [
    ["Will you email or message me?", "Not unless you say so. Nothing is emailed, sent by Discord DM or pushed until you turn that on in the bell → Notification settings (or Edit profile). Alerts always land in the 🔔 bell on the site."],
    ["What can I get alerts about?", "A film on your watchlist being booked or announced, tickets going on sale, a newly booked film that fits a search you saved, a favorite's film being booked (from Your taste), the club's games (if you turn those on), and (Discord members) a “Did you make it?” DM after screenings."],
    ["How do I save a search?", "On Browse, pick some filters and tap 🔔 Alert me. You'll hear when a theatre books a new film that fits it. Manage saved searches in the bell → Notification settings."],
    ["Can I get notifications on my phone?", "Yes — in Notification settings, turn on push for this device. On iPhone, add the site to your Home Screen first."],
  ] },
  { id: "discord", title: "Discord", items: [
    ["How do I link Discord?", "Edit profile → Connect Discord (or sign in with Discord). Linking puts your site and Discord activity together."],
    ["What shows up in the club's Discord?", "Only what you choose. In Edit profile → Sharing to Discord, pick Ask, Always or Never for your RSVPs, the polls you create, your comments and the Monday digest naming you — and Always or Never for a bingo win naming you. Only members who've linked Discord and are in the club's server ever appear there."],
    ["What can the bot do?", "Type /help in Discord for the list. Favorites: /showtimes, /movie, /foryou, /find, /rsvp, /watch, /vote, /play, /trivia, /bingo and /kernels — replies to you are private unless they're meant for the channel."],
  ] },
  { id: "letterboxd", title: "Letterboxd", items: [
    ["How do I connect Letterboxd?", "Edit profile → Letterboxd → enter your username. We read your public diary feed every few hours — nothing else, and we never post to Letterboxd. One site account per Letterboxd account; a club admin can clear a wrong claim."],
    ["What does the diary sync do?", "When your diary has a film you said you were going to (that day or the next), you choose what happens: Ask (your “Did you make it?” prompt says so), Always (you're checked in automatically) or Never."],
    ["Will people see my ratings?", "Only if you turn on “Show my star ratings with my check-ins” — then your rating and a link to your review appear on that screening in the feed. Disconnecting forgets your username and everything we read."],
  ] },
  { id: "privacy", title: "Privacy", items: [
    ["What can other members see?", "Your name, picture, bio, your plans and check-ins in clubs you share, your Letterboxd link if you added one, and your taste only if you switch on showing it. Your email is only visible to admins of clubs you're in, and your settings are private."],
    ["Is anything public?", "What's playing is public. Your plans, comments and lists are only shown to members of your clubs (a guest profile's are private to you). Calendar subscription links work for anyone who has them — New link turns an old one off."],
  ] },
];

const norm = s => s.toLowerCase();

export default function HelpPage() {
  const shell = useShell() || {};
  const [q, setQ] = useState("");
  const shown = useMemo(() => {
    const words = norm(q).split(/\s+/).filter(Boolean);
    if (!words.length) return SECTIONS;
    return SECTIONS.map(sec => ({
      ...sec,
      items: sec.items.filter(([question, answer]) => words.every(w => norm(`${sec.title} ${question} ${answer}`).includes(w))),
    })).filter(sec => sec.items.length);
  }, [q]);

  useHashScroll();

  return (
    <div className="page narrow help-page">
      <PageHeader title="Help" />
      <div className="help-tools">
        <input type="search" className="share-input help-search" placeholder="Search help (kernels, Discord, alerts…)"
               aria-label="Search help" value={q} onChange={e => setQ(e.target.value)} />
        {shell.user && !shell.user.is_guest && (
          <button type="button" className="btn btn-sm" onClick={() => shell.startTour?.()}>Take the tour</button>
        )}
      </div>
      {!q && (
        <nav className="help-toc" aria-label="Help topics">
          {SECTIONS.map(s => <a key={s.id} href={`#${s.id}`} className="chip">{s.title}</a>)}
        </nav>
      )}
      {shown.length === 0 && <p className="pv-empty">Nothing matches “{q}”. Try another word, or <Link to="/help" onClick={() => setQ("")}>see every topic</Link>.</p>}
      {shown.map(sec => (
        <section key={sec.id} id={sec.id} className="help-section">
          <h2 className="help-title">{sec.title}</h2>
          {sec.items.map(([question, answer]) => (
            <details key={question} className="help-item" open={!!q}>
              <summary>{question}</summary>
              <p>{answer}</p>
            </details>
          ))}
        </section>
      ))}
    </div>
  );
}
