// A Letterboxd rating as stars: 4.5 → "★★★★½" (R10f).
export const stars = r => (r ? "★".repeat(Math.floor(r)) + (r % 1 ? "½" : "") : "");
