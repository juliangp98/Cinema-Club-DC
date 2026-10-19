import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import TheatrePicker from "../src/ui/TheatrePicker";
import CityTag from "../src/ui/CityTag";
import CityMenu from "../src/shell/CityMenu";
import FilmPage from "../src/pages/FilmPage";
import { byCity, guessCity } from "../src/places";
import { setRequestCity, withCity } from "../src/api";
import { mockApi, renderPage } from "./support";

// Cities: theatres chosen the same way everywhere (your city's by area, then
// other cities, each under its name), a theatre outside your city says which
// it's in, the city menu, the city every API call names, and a film playing
// in two cities shown a city at a time, yours first.

const CITIES = [
  { slug: "dc", name: "Washington, DC", short: "DC", tz: "America/New_York", phrase: "DC-area",
    areas: [{ key: "dc", label: "DC" }, { key: "maryland", label: "Maryland" }] },
  { slug: "testville", name: "Testville", short: "TV", tz: "America/Chicago", phrase: "Testville-area",
    areas: [{ key: "downtown", label: "Downtown" }] },
];
const THEATRES = [
  { slug: "afi", name: "AFI Silver Theatre", short_name: "AFI", city: "dc", area_label: "Maryland", color: "#c45c3a" },
  { slug: "suns", name: "Suns Cinema", short_name: "SUNS", city: "dc", area_label: "DC", color: "#e8a838" },
  { slug: "tv-house", name: "Testville House", short_name: "TV HOUSE", city: "testville", area_label: "Downtown", color: "#123456" },
];

test("the picker: your city by area (in its own order), then other cities, each under its name", async () => {
  const toggled = [];
  const { rerender } = renderPage(<TheatrePicker theatres={THEATRES} home="dc" cities={CITIES} label="Theatres"
                                                 isOn={() => false} onToggle={s => toggled.push(s)} />);
  const group = screen.getByRole("group", { name: "Theatres" });
  const labels = [...group.querySelectorAll(".ui-group-label")].map(e => e.textContent);
  expect(labels).toEqual(["DC", "Maryland", "Testville"]);                           // areas, then the other city
  expect(group.querySelector("details").open).toBe(false);                           // tucked away until it matters
  await userEvent.click(screen.getByRole("button", { name: "AFI" }));
  expect(toggled).toEqual(["afi"]);
  rerender(<TheatrePicker theatres={THEATRES} home="dc" cities={CITIES} label="Theatres"
                          isOn={s => s === "tv-house"} onToggle={() => {}} />);
  expect(screen.getByRole("group", { name: "Theatres" }).querySelector("details").open).toBe(true);   // one's chosen
});

test("with one city's theatres, no 'Other cities'", () => {
  renderPage(<TheatrePicker theatres={THEATRES.slice(0, 2)} home="dc" cities={CITIES.slice(0, 1)} label="Theatres"
                            isOn={() => true} onToggle={() => {}} />);
  expect(screen.queryByText("Other cities")).toBeNull();
});

test("a theatre outside your city says which it's in — only with more than one city", () => {
  const { unmount } = renderPage(<CityTag city="testville" />, { shell: { multiCity: false, city: "dc", cities: CITIES } });
  expect(document.querySelector(".city-tag")).toBeNull();
  unmount();
  renderPage(<><CityTag city="testville" /><CityTag city="dc" /></>, { shell: { multiCity: true, city: "dc", cities: CITIES } });
  expect([...document.querySelectorAll(".city-tag")].map(e => e.textContent)).toEqual(["TV"]);
});

test("the city menu", async () => {
  const picked = [];
  renderPage(<CityMenu cities={CITIES} city="dc" onPick={c => picked.push(c)} />);
  await userEvent.click(screen.getByRole("button", { name: "City: Washington, DC. Change it" }));
  await userEvent.click(screen.getByRole("menuitem", { name: "Testville" }));
  expect(picked).toEqual(["testville"]);
});

test("a first visit's city: the one in your time zone, else the closest", () => {
  const tz = vi.spyOn(Intl.DateTimeFormat.prototype, "resolvedOptions").mockReturnValue({ timeZone: "America/Chicago" });
  expect(guessCity(CITIES)).toBe("testville");
  tz.mockReturnValue({ timeZone: "America/New_York" });
  expect(guessCity(CITIES)).toBe("dc");
  tz.mockRestore();
  expect(byCity(THEATRES, "testville", CITIES).others.map(([c]) => c.slug)).toEqual(["dc"]);
});

test("every call names the city (not the bot's, and not twice)", () => {
  setRequestCity("testville");
  expect(withCity("/api/discover")).toBe("/api/discover?city=testville");
  expect(withCity("/api/discover/browse?when=week")).toBe("/api/discover/browse?when=week&city=testville");
  expect(withCity("/api/discover?city=dc")).toBe("/api/discover?city=dc");
  expect(withCity("/api/internal/servers")).toBe("/api/internal/servers");
  setRequestCity(null);
  expect(withCity("/api/discover")).toBe("/api/discover");
});

test("a film in two cities: yours first, a city at a time", async () => {
  const show = (id, t, start) => ({ id, start_time: start, starts_at: `${start}-05:00`, theatre: THEATRES.find(x => x.slug === t) });
  mockApi({ "GET /api/films/12": { movie: { id: 12, title: "PRAIRIE NOIR" }, announced: [], viewer_wants: false,
                                   showtimes: [show(1, "afi", "2026-10-24T19:30:00"), show(2, "tv-house", "2026-10-24T18:00:00"),
                                               show(3, "tv-house", "2026-10-25T18:00:00")] } });
  renderPage(<Routes><Route path="/films/:id" element={<FilmPage apiBase="" groupId={null} />} /></Routes>,
             { route: "/films/12", shell: { city: "testville", cities: CITIES, multiCity: true } });
  const cities = await screen.findByRole("group", { name: "City" });
  expect(within(cities).getAllByRole("button").map(b => b.textContent)).toEqual(["Testville2", "Washington, DC1"]);
  expect(screen.getByText(/About/)).toHaveTextContent("Testville House");               // Testville's showings first
  await userEvent.click(within(cities).getByRole("button", { name: /Washington, DC/ }));
  expect(screen.getByText(/About/)).toHaveTextContent("AFI Silver Theatre");
});
