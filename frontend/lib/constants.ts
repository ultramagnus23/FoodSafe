// Static reference (ids/names only, matches schema.sql seed) so selectors
// don't need a network round-trip just to populate options. All risk
// numbers still always come from the API.
export const COMMODITIES = [
  { id: 1, name: "Rice" },
  { id: 2, name: "Wheat" },
  { id: 3, name: "Milk" },
  { id: 4, name: "Groundnut" },
  { id: 5, name: "Chilli" },
  { id: 6, name: "Turmeric" },
  { id: 7, name: "Mustard Oil" },
  { id: 8, name: "Onion" },
  { id: 9, name: "Potato" },
  { id: 10, name: "Paneer" },
];

export function fmt(n: number | null | undefined, decimals = 1): string {
  return n != null ? Number(n).toFixed(decimals) : "—";
}

export function cap(s: string | null | undefined): string {
  if (!s) return "—";
  return s.charAt(0).toUpperCase() + s.slice(1);
}
