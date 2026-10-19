import { screen } from "@testing-library/react";
import FilmPage from "../src/pages/FilmPage";
import { routeMeta, setPageMeta } from "../src/seo";
import { mockApi, renderPage } from "./support";
import { Route, Routes } from "react-router-dom";

// What search engines see (SEO): each public page's title and description,
// private pages noindex, Browse's filtered views pointing at /browse, and a
// film page's structured data — public schedule facts only, never people.

const head = () => ({
  title: document.title,
  robots: document.head.querySelector('meta[name="robots"]')?.content,
  canonical: document.head.querySelector('link[rel="canonical"]')?.href,
  description: document.head.querySelector('meta[name="description"]')?.content,
  ld: document.head.querySelector("#page-ld")?.textContent,
});

test("screenings carry their city's offset (the server's starts_at)", async () => {
  const { filmLd } = await import("../src/seo");
  const ld = filmLd({ title: "X" }, [{ start_time: "2026-12-24T19:00:00", starts_at: "2026-12-24T19:00:00-06:00",
                                       theatre: { name: "Testville House" } }]);
  expect(ld["@graph"][1].startDate).toBe("2026-12-24T19:00:00-06:00");
});

test("the words follow the viewer's city", async () => {
  const { setSeoCity } = await import("../src/seo");
  setSeoCity({ short: "Testville", phrase: "Testville-area", known_for: "" });
  setPageMeta(routeMeta("/calendar"));
  expect(head().description).toMatch(/^Every showtime at Testville-area repertory/);
  setPageMeta(routeMeta("/"));
  expect(head().title).toBe("Cinema Club DC — repertory and independent film in Testville");
  setSeoCity({ short: "DC", phrase: "DC-area", known_for: "AFI, Suns, Alamo, the Smithsonian and more" });
});

test("each address: its title, and noindex for private pages and filtered Browse", () => {
  setPageMeta(routeMeta("/calendar"));
  expect(head()).toMatchObject({ title: "Calendar · Cinema Club DC", robots: "index, follow" });
  expect(head().canonical).toMatch(/\/calendar$/);
  for (const p of ["/me", "/club", "/feed", "/play", "/people/4", "/polls/3", "/groups"]) {
    setPageMeta(routeMeta(p));
    expect(head().robots).toBe("noindex, follow");
  }
  setPageMeta(routeMeta("/browse", "?genres=horror"));
  expect(head().robots).toBe("noindex, follow");
  expect(head().canonical).toMatch(/\/browse$/);
  setPageMeta(routeMeta("/"));
  expect(head().title).toBe("Cinema Club DC — repertory and independent film in DC");
});

test("a film page: its title, description and screenings as structured data — no one's name", async () => {
  const showing = { id: 7, start_time: "2026-10-24T19:30:00", starts_at: "2026-10-24T19:30:00-04:00", format_label: "35mm", is_sold_out: false, purchase_link: "https://afi.test/t/7",
                    theatre: { slug: "afi", name: "AFI Silver Theatre", short_name: "AFI", address: "8633 Colesville Rd" },
                    attendees: [{ id: 3, name: "Secret Sam" }] };
  mockApi({ "GET /api/films/12": { movie: { id: 12, title: "VERTIGO", release_year: "1958", director: "Alfred Hitchcock",
                                            description: "A detective with a fear of heights.", poster_url: "https://img.test/v.jpg" },
                                   showtimes: [showing], announced: [], viewer_wants: false } });
  renderPage(<Routes><Route path="/films/:id" element={<FilmPage apiBase="" groupId={null} />} /></Routes>, { route: "/films/12" });
  await screen.findByRole("heading", { name: "VERTIGO" });
  const h = head();
  expect(h.title).toBe("VERTIGO (1958) · Cinema Club DC");
  expect(h.description).toContain("showtimes at AFI");
  const ld = JSON.parse(h.ld);
  const event = ld["@graph"].find(x => x["@type"] === "ScreeningEvent");
  expect(event).toMatchObject({ startDate: "2026-10-24T19:30:00-04:00", videoFormat: "35mm",           // its city's offset (the server's starts_at)
                                location: { "@type": "MovieTheater", name: "AFI Silver Theatre" } });
  expect(event.offers.url).toBe("https://afi.test/t/7");
  expect(h.ld).not.toContain("Secret Sam");
});
