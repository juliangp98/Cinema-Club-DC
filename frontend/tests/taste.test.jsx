import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import TasteEditor from "../src/components/TasteEditor";
import TasteChips, { TasteMatch } from "../src/ui/TasteChips";
import { mockApi, renderPage, reply } from "./support";

// Your taste (R13): genres you love or aren't into, ways to watch, favorite
// theatres, films and people — saved as you go; private unless you show it.

const VIEW = {
  options: {
    genres: [{ key: "horror", label: "Horror" }, { key: "romance", label: "Romance" }, { key: "science fiction", label: "Sci-fi" }],
    ways: [{ key: "film", label: "On film prints", emoji: "🎞️" }],
    theatres: [{ slug: "afi", name: "AFI Silver", short_name: "AFI", color: "#c33" }],
  },
  genres: ["horror"], avoid: [], ways: [], theatres: [], movies: [], people: [], hidden: [], public: false, set: true,
  summary: { genres: ["Horror"], ways: [], theatres: [], movies: [], people: [] },
};

function server(extra = {}) {
  let v = structuredClone(VIEW);
  const calls = mockApi({
    "GET /api/me/taste": () => v,
    "PUT /api/me/taste": body => (v = { ...v, ...body }),
    "POST /api/me/taste/items": body => (v = body.kind === "movie"
      ? { ...v, movies: [...v.movies, { key: String(body.movie_id || 99), label: body.movie_id ? "VERTIGO" : "Cléo from 5 to 7", year: "1958" }] }
      : { ...v, people: [...v.people, { kind: body.kind, key: body.name.toLowerCase(), label: body.name }] }),
    "DELETE /api/me/taste/items": body => (v = { ...v, movies: v.movies.filter(m => m.key !== body.key) }),
    ...extra,
  });
  return calls;
}
const section = name => screen.getByRole("region", { name });

test("genres you love and aren't into, saved as you tap", async () => {
  const calls = server();
  renderPage(<TasteEditor apiBase="" />);
  const love = await screen.findByRole("region", { name: "Genres you love" });
  expect(within(love).getByRole("button", { name: "Horror" })).toHaveAttribute("aria-pressed", "true");
  await userEvent.click(within(love).getByRole("button", { name: "Sci-fi" }));
  expect(calls.at(-1)).toEqual({ method: "PUT", path: "/api/me/taste", body: { genres: ["horror", "science fiction"] } });
  await userEvent.click(within(section("Not into")).getByRole("button", { name: "Horror" }));    // a favorite moves over
  expect(calls.at(-1).body).toEqual({ genres: ["science fiction"], avoid: ["horror"] });
  expect(within(section("Not into")).getByRole("button", { name: "Horror" })).toHaveAttribute("aria-pressed", "true");
});

test("ways to watch, theatres in their color, and showing it on your profile", async () => {
  const calls = server();
  renderPage(<TasteEditor apiBase="" />);
  await userEvent.click(await screen.findByRole("button", { name: /On film prints/ }));
  expect(calls.at(-1).body).toEqual({ ways: ["film"] });
  const afi = within(section("Favorite theatres")).getByRole("button", { name: "AFI" });
  expect(afi.style.getPropertyValue("--tcolor")).toBe("#c33");
  await userEvent.click(afi);
  expect(calls.at(-1).body).toEqual({ theatres: ["afi"] });
  const show = screen.getByRole("checkbox", { name: /Show my taste on my profile/ });
  expect(show).not.toBeChecked();
  await userEvent.click(show);
  expect(calls.at(-1).body).toEqual({ public: true });
});

test("favorite films: ours first, then any film on TMDB; remove with ×", async () => {
  const calls = server({
    "GET /api/search/suggest": { films: [{ id: 5, title: "VERTIGO", year: 1958 }] },
    "GET /api/films/tmdb-search": { results: [{ tmdb_id: 426, title: "Vertigo", year: 1958, movie_id: 5 },
                                               { tmdb_id: 499, title: "Cléo from 5 to 7", year: 1962, movie_id: null }] },
  });
  renderPage(<TasteEditor apiBase="" />);
  await userEvent.type(await screen.findByRole("searchbox", { name: "Add a favorite film" }), "ver");
  const results = await screen.findByRole("list", { name: "Add a favorite film: results" });
  expect(within(results).getAllByRole("button").map(b => b.textContent)).toEqual(["VERTIGO1958", "Cléo from 5 to 71962"]);   // one VERTIGO
  await userEvent.click(within(results).getByRole("button", { name: /Cléo/ }));
  expect(calls.at(-1)).toEqual({ method: "POST", path: "/api/me/taste/items", body: { kind: "movie", tmdb_id: 499 } });
  await userEvent.click(await screen.findByRole("button", { name: "Remove Cléo from 5 to 7" }));
  expect(calls.at(-1)).toEqual({ method: "DELETE", path: "/api/me/taste/items", body: { kind: "movie", key: "99" } });
});

test("favorite people: pick the kind, search, add", async () => {
  const calls = server({ "GET /api/taste/people": (_, path) => (path.includes("kind=actor")
    ? [{ name: "Faye Wong", kind: "actor" }] : [{ name: "Wong Kar-wai", kind: "director" }]) });
  renderPage(<TasteEditor apiBase="" />);
  await userEvent.click(await screen.findByRole("button", { name: "Actors" }));
  await userEvent.type(screen.getByRole("searchbox", { name: "Add a favorite actor" }), "wong");
  await userEvent.click(await screen.findByRole("button", { name: /Faye Wong/ }));
  expect(calls.at(-1).body).toEqual({ kind: "actor", name: "Faye Wong" });
  expect(await screen.findByText("Faye Wong · actor")).toBeInTheDocument();
});

test("the server's reason when something can't be saved", async () => {
  server({ "PUT /api/me/taste": reply(400, { error: "Pick theatres from the list." }) });
  renderPage(<TasteEditor apiBase="" />);
  await userEvent.click(await screen.findByRole("button", { name: "AFI" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Pick theatres from the list.");
});

test("someone's taste at a glance", () => {
  const { container } = renderPage(<TasteChips taste={{ genres: ["Horror"], ways: ["🎞️ On film prints"], theatres: ["AFI Silver"],
    movies: [{ key: "5", label: "VERTIGO" }], people: [{ kind: "director", label: "Agnès Varda" }] }} />);
  expect([...container.querySelectorAll(".chip")].map(c => c.textContent)).toEqual(
    ["Horror", "🎞️ On film prints", "📍 AFI Silver", "🎬 VERTIGO", "Agnès Varda · director"]);
  const { container: none } = renderPage(<TasteChips taste={{ genres: [] }} empty={<p>Nothing yet</p>} />);
  expect(none).toHaveTextContent("Nothing yet");
});

test("taste match: a score and what you share, only when there is one", () => {
  const { container } = renderPage(<TasteMatch match={{ score: 40, shared: ["Agnès Varda", "Drama"] }} />);
  expect(screen.getByText("🎨 Taste match 40%")).toHaveClass("chip", "gold");
  expect(screen.getByText("You both love Agnès Varda, Drama")).toHaveClass("ui-hint");
  const { container: hidden } = renderPage(<TasteMatch match={{ score: null, shared: [] }} />);
  expect(hidden).toBeEmptyDOMElement();
  expect(container).not.toBeEmptyDOMElement();
});
