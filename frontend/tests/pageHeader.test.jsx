import { screen, within } from "@testing-library/react";
import PageHeader, { PageMeta } from "../src/ui/PageHeader";
import { Coverage } from "../src/pages/DiscoverPage";
import { mockApi, renderPage } from "./support";

// The chips under a page title (R12) — these replaced plain subtitle lines.

test("a page's facts show as chips, links where there's somewhere to go", () => {
  renderPage(<PageHeader title="Theatres" meta={[
    { icon: "🎭", label: "13 DC-area theatres" },
    false,                                                     // skipped
    { icon: "🌙", label: "5 showings tonight", gold: true, to: "/calendar" },
    { label: "Browse everything on →", to: "/browse", more: true },
  ]} />);
  const row = screen.getByRole("list", { name: "About this page" });
  const items = within(row).getAllByRole("listitem");
  expect(items).toHaveLength(3);
  expect(items[0]).toHaveTextContent("13 DC-area theatres");
  expect(within(items[1]).getByRole("link")).toHaveAttribute("href", "/calendar");
  expect(within(items[1]).getByRole("link")).toHaveClass("chip", "gold");
  expect(within(items[2]).getByRole("link")).toHaveClass("ui-page-meta-more");
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Theatres");
});

test("no facts, no row — and no subtitle sentence", () => {
  const { container } = renderPage(<PageHeader title="Help" />);
  expect(container.querySelector(".ui-page-meta")).toBeNull();
  expect(container.querySelector("p")).toBeNull();
  renderPage(<PageMeta items={[null, false]} />);
  expect(screen.queryAllByRole("list")).toHaveLength(0);
});

const THEATRES = ["afi", "suns", "alamo-dc", "alamo-crystal", "regal-gallery", "miracle", "avalon"].map((slug, i) => (
  { slug, name: `${slug.toUpperCase()} Theatre`, short_name: slug.toUpperCase(), color: `#${i}${i}${i}` }));

test("Discover: the club's theatres, one tap each, then the rest and every theatre", async () => {
  mockApi({ "GET /api/theatres": THEATRES });
  renderPage(<Coverage apiBase="" group={{ theatres: ["afi", "suns", "alamo-dc", "alamo-crystal", "regal-gallery", "miracle"] }} />);
  const row = await screen.findByRole("list", { name: "What Discover covers" });
  const links = within(row).getAllByRole("link");
  expect(links[0]).toHaveTextContent("The club's 6 theatres");
  expect(links[0]).toHaveAttribute("href", "/theatres");                      // phones needn't swipe for it
  expect(links.slice(1, 5).map(a => a.getAttribute("href"))).toEqual(
    ["/theatres/afi", "/theatres/suns", "/theatres/alamo-dc", "/theatres/alamo-crystal"]);
  expect(within(row).getByRole("link", { name: "+2 more" })).toHaveAttribute("title", "REGAL-GALLERY Theatre, MIRACLE Theatre");
  expect(within(row).getByText("Next 2 weeks")).toBeInTheDocument();
  expect(within(row).getByRole("link", { name: "All theatres →" })).toHaveAttribute("href", "/theatres");
});

test("Discover: a club on every theatre, and visitors", async () => {
  mockApi({ "GET /api/theatres": THEATRES });
  const shell = { city: "dc", cities: [{ slug: "dc", name: "Washington, DC", short: "DC", phrase: "DC-area", areas: [] }] };
  const { unmount } = renderPage(<Coverage apiBase="" group={{ theatres: [] }} />, { shell });
  expect(await screen.findByRole("link", { name: /All 7 DC-area theatres/ })).toHaveAttribute("href", "/theatres");
  unmount();
  renderPage(<Coverage apiBase="" group={null} />, { shell });
  expect(await screen.findByRole("link", { name: /^7 DC-area theatres/ })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "All theatres →" })).toBeInTheDocument();
});

test("a section's link is the same gold link everywhere — a link or a button", async () => {
  const { SectionTitle } = await import("../src/ui/PageHeader");
  const onClick = vi.fn();
  renderPage(<>
    <SectionTitle link={{ to: "/play", label: "Play →" }}>Games</SectionTitle>
    <SectionTitle link={{ to: "/feed", label: "See the full feed →" }}>Recent activity</SectionTitle>
    <SectionTitle link={{ onClick, label: "All activity →" }}>This week</SectionTitle>
  </>);
  const play = screen.getByRole("link", { name: "Play →" });
  const feed = screen.getByRole("link", { name: "See the full feed →" });
  expect(play).toHaveClass("ui-section-link");
  expect(feed).toHaveClass("ui-section-link");
  expect(play.closest(".ui-section-title")).toHaveTextContent("Games");               // in the heading, not below it
  screen.getByRole("button", { name: "All activity →" }).click();
  expect(onClick).toHaveBeenCalled();
});
