"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { num, ordinal, snapshotStamp, useSnapshot } from "@/lib/snapshot";

interface Finding {
  fig: string;
  say: string;
  small: string;
  href: string;
}

function useFindings(): { items: Finding[]; loading: boolean } {
  const std = useSnapshot("standards_summary");
  const co = useSnapshot("rasff_countries");
  const prof = useSnapshot("health_profiles");
  const bu = useSnapshot("burden");
  const nu = useSnapshot("nutrition");
  const items: Finding[] = [];
  const f = std.data?.flags;
  if (f?.comparisons) {
    items.push({
      fig: num(f.india_higher_than_eu),
      say: `food–hazard pairs where India's legal limit is above the EU's, of ${num(f.comparisons)} India regulates.`,
      small: `In ${num(f.gap_not_approved + f.gap_no_use_on_food + f.gap_never_assessed + f.gap_at_loq)} of the ${num(
        f.higher_eu_pesticides,
      )} pesticide cases the EU permits no use on that food, so its limit is the detection floor.`,
      href: "/standards",
    });
  }
  if (f?.not_approved_in_eu) {
    items.push({
      fig: num(f.not_approved_in_eu),
      say: `of the ${num(f.india_pesticides)} pesticides India sets food limits for are not approved in the EU.`,
      small: "Approval status of the specific substance, from the EU Pesticides Database.",
      href: "/standards",
    });
  }
  const IN = co.data?.find((c) => c.origin === "IN");
  if (IN && co.data) {
    const rank = co.data.findIndex((c) => c.origin === "IN") + 1;
    items.push({
      fig: num(IN.notifications),
      say: `EU border and market notifications on food from India, the ${ordinal(rank)} most of ${num(co.data.length)} origins.`,
      small: `${num(IN.serious)} classed serious. Risk-targeted checks of exports, not a sample of food eaten in India.`,
      href: "/findings",
    });
  }
  const cancer = prof.data?.find((p) => p.origin === "IN" && p.outcome_key === "cancer");
  if (cancer) {
    items.push({
      fig: num(cancer.notifications),
      say: "of those findings involve a hazard classified as a carcinogen, most often ethylene oxide in sesame and spices.",
      small: "Linked through the cited hazard knowledge base; each link carries its WHO, IARC or EFSA source.",
      href: "/engine#profiles",
    });
  }
  const deaths = bu.data?.find((b) => b.measure === "deaths" && b.age_group === "all ages" && b.hazard === "All hazards");
  if (deaths) {
    items.push({
      fig: `${num(deaths.value / 1e6, 2)} M`,
      say: "deaths a year worldwide from foodborne disease, per WHO's 2021 estimates.",
      small: "Global estimates only: WHO publishes no country breakdown.",
      href: "/places#burden",
    });
  }
  const ns = nu.data?.nutriscore ?? [];
  const graded = ns.reduce((a, b) => a + b.n, 0);
  if (graded) {
    const de = ns.filter((x) => x.g === "d" || x.g === "e").reduce((a, b) => a + b.n, 0);
    items.push({
      fig: `${Math.round((100 * de) / graded)}%`,
      say: `of ${num(graded)} graded packaged foods sold in India score D or E on Nutri-Score.`,
      small: "Open Food Facts label data; not a sample of the Indian diet.",
      href: "/nutrition",
    });
  }
  return { items, loading: std.isLoading || co.isLoading };
}

const QUESTIONS: { q: string; a: string; href: string; cta: string }[] = [
  {
    q: "What do the rules allow?",
    a: "India's legal limits for pesticides, metals and toxins beside the EU, Codex and the US, with the reason each gap exists.",
    href: "/standards",
    cta: "Standards",
  },
  {
    q: "What is actually found in food?",
    a: "EU border findings for every origin country, India's state sampling outcomes, and pesticide-residue monitoring.",
    href: "/findings",
    cta: "Findings",
  },
  {
    q: "What does it mean for health?",
    a: "Each finding's hazard linked to the illnesses it causes, who is most at risk, and how much food reaches a safe-intake limit.",
    href: "/engine",
    cta: "Disease engine",
  },
  {
    q: "How do places compare?",
    a: "Indian states, 217 countries' food-safety capacity and nutrition, and the global burden of foodborne disease.",
    href: "/places",
    cta: "Places",
  },
];

const CHAIN: { title: string; status: "Built" | "Partial" | "Missing"; tone: string }[] = [
  { title: "Rules", status: "Built", tone: "text-clear" },
  { title: "Findings", status: "Partial", tone: "text-caution" },
  { title: "Hazard identification", status: "Built", tone: "text-clear" },
  { title: "Hazard to disease", status: "Built", tone: "text-clear" },
  { title: "Exposure and risk", status: "Partial", tone: "text-caution" },
  { title: "Illness observed", status: "Missing", tone: "text-risk" },
];

function Cta({ href, children, primary = false }: { href: string; children: ReactNode; primary?: boolean }) {
  return (
    <Link
      href={href}
      className={`rounded px-5 py-2.5 text-sm font-medium ${primary ? "bg-ink text-on-ink hover:opacity-90" : "border border-line text-ink hover:bg-provenance-pale"}`}
    >
      {children}
    </Link>
  );
}

export default function HomePage() {
  const meta = useSnapshot("meta");
  const sources = useSnapshot("sources");
  const { items, loading } = useFindings();
  const rows = (sources.data ?? []).reduce((a, s) => a + (s.rows ?? 0), 0);

  return (
    <div>
      <div className="border-b border-line">
        <div className="mx-auto max-w-3xl px-6 py-20 text-center sm:py-24">
          <div className="mb-4 text-xs font-semibold uppercase tracking-wide text-ink">FoodSafe India</div>
          <h1 className="mb-5 font-display text-4xl font-light leading-tight sm:text-5xl">
            From food contamination to disease, on public records alone.
          </h1>
          <p className="mx-auto mb-8 max-w-xl leading-relaxed text-provenance">
            What India&apos;s food law allows, what is actually found in food, which illnesses each finding points to and for
            whom, and how places compare. Every number keeps its source; nothing is synthetic.
          </p>
          <div className="flex flex-wrap justify-center gap-3">
            <Cta href="/engine" primary>
              Open the disease engine
            </Cta>
            <Cta href="/brief">Read the research briefing</Cta>
          </div>
        </div>
      </div>

      <div className="border-b border-line bg-slab px-6 py-3">
        <p className="register mx-auto max-w-5xl text-center text-xs text-provenance">
          {sources.data ? `${sources.data.length} sources · ${num(rows)} records` : "Loading…"}
          {meta.data ? ` · snapshot ${snapshotStamp(meta.data)}` : ""}
        </p>
      </div>

      <div className="mx-auto max-w-5xl px-6 py-16">
        <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink">What the records show</div>
        <h2 className="mb-8 font-display text-3xl font-light">Findings from the latest snapshot</h2>
        {loading && !items.length ? <p className="text-sm text-provenance">Loading findings…</p> : null}
        <ol className="divide-y divide-line border-y border-line">
          {items.map((it) => (
            <li key={it.say} className="grid gap-2 py-5 sm:grid-cols-[9rem_minmax(0,1fr)_auto] sm:items-baseline sm:gap-6">
              <span className="register text-3xl font-medium text-ink">{it.fig}</span>
              <span className="leading-relaxed text-ink">
                {it.say}
                <small className="mt-1 block text-sm text-provenance">{it.small}</small>
              </span>
              <Link href={it.href} className="whitespace-nowrap text-sm text-ink underline">
                See the evidence →
              </Link>
            </li>
          ))}
        </ol>
      </div>

      <div className="border-t border-line bg-slab">
        <div className="mx-auto grid max-w-5xl gap-4 px-6 py-16 sm:grid-cols-2">
          {QUESTIONS.map((x) => (
            <Link key={x.href} href={x.href} className="rounded-lg border border-line bg-porcelain p-6 transition-colors hover:border-line-strong">
              <div className="mb-2 font-display text-xl text-ink">{x.q}</div>
              <p className="mb-4 text-sm leading-relaxed text-provenance">{x.a}</p>
              <span className="text-sm font-medium text-ink underline">{x.cta} →</span>
            </Link>
          ))}
        </div>
      </div>

      <div className="mx-auto max-w-5xl px-6 py-16">
        <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink">The engine, link by link</div>
        <h2 className="mb-3 font-display text-3xl font-light">A disease predictor needs every link</h2>
        <p className="mb-8 max-w-prose leading-relaxed text-provenance">
          Three links are built on real data and two only in part: India publishes no district or market testing. One is
          missing: no public dataset records where contaminated food makes people ill. So the engine says which diseases a
          finding points to and for whom; the{" "}
          <Link href="/brief" className="underline">
            research plan
          </Link>{" "}
          sets out how the burden estimate will be built and validated without inventing data.
        </p>
        <ol className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
          {CHAIN.map((c, i) => (
            <li key={c.title} className="rounded-lg border border-line p-3">
              <div className="register mb-1 text-xs text-provenance">{i + 1}</div>
              <div className="mb-1 text-sm font-medium text-ink">{c.title}</div>
              <div className={`register text-xs ${c.tone}`}>{c.status}</div>
            </li>
          ))}
        </ol>
        <div className="mt-6">
          <Link href="/engine#chain" className="text-sm font-medium text-ink underline">
            How each link works →
          </Link>
        </div>
      </div>

      <div className="border-t border-line bg-slab">
        <div className="mx-auto max-w-3xl px-6 py-10 text-center text-sm leading-relaxed text-provenance">
          Legal limits are regulatory lines, not safety verdicts. EU notifications and Indian state samples are risk-targeted,
          so nothing here is a prevalence estimate, and nothing here rates a brand or producer.{" "}
          <Link href="/sources" className="underline">
            How far to trust each source →
          </Link>
        </div>
      </div>
    </div>
  );
}
