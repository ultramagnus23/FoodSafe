// One list of the site's pages, shared by the desktop nav and the mobile tab bar.

export interface NavLink {
  href: string;
  label: string;
  note?: string;
}

export const PRIMARY: NavLink[] = [
  { href: "/engine", label: "Disease engine" },
  { href: "/standards", label: "Standards" },
  { href: "/findings", label: "Findings" },
  { href: "/hazards", label: "Hazards" },
  { href: "/places", label: "Places" },
  { href: "/research", label: "Research" },
  { href: "/brief", label: "Briefing" },
];

export const MORE: NavLink[] = [
  { href: "/nutrition", label: "Nutrition", note: "Packaged food sold in India" },
  { href: "/sources", label: "Sources", note: "Every dataset and how far to trust it" },
  { href: "/directory", label: "Directory", note: "Labs, commissioners, state and pesticide data" },
  { href: "/methodology", label: "Methodology", note: "Scoring, backtests, limits" },
  { href: "/map", label: "Risk map", note: "District scores (sign-in; empty until district data exists)" },
  { href: "/compare", label: "Compare districts", note: "Sign-in" },
  { href: "/alerts", label: "Alerts", note: "Sign-in" },
  { href: "/search", label: "Search" },
  { href: "/report", label: "Report an issue" },
];

export const MOBILE_TABS: NavLink[] = [
  { href: "/", label: "Home" },
  { href: "/engine", label: "Engine" },
  { href: "/standards", label: "Standards" },
  { href: "/findings", label: "Findings" },
];
