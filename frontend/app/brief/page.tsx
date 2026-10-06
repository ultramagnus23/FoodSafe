"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { Page, Section, SnapshotNote, Table, Tag, Td, Th } from "@/components/ui/DataBlocks";
import { num, useSnapshot } from "@/lib/snapshot";

const REPO = "https://github.com/ultramagnus23/FoodSafe/blob/main/";
const PLAN = `${REPO}docs/RESEARCH_PLAN.md`;

function Ext({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} className="underline" target="_blank" rel="noreferrer">
      {children}
    </a>
  );
}

const RQS: { id: string; q: string; how: string; state: "done" | "partial" | "planned" }[] = [
  {
    id: "RQ1 · Rules",
    q: "How do India's legal limits compare with the EU, Codex and the US, and which gaps involve hazards with serious health outcomes?",
    how: "Descriptive analysis of every compared food–hazard pair, joined to the cited hazard-to-disease knowledge base.",
    state: "partial",
  },
  {
    id: "RQ2 · Hazard identification",
    q: "Can public contamination records be classified by hazard reliably enough to feed the engine?",
    how: "Classifier trained on 2020–24 EU notifications, tested on 2025–26: accuracy 0.918 vs 0.796 for keywords. Calibration and error analysis to add.",
    state: "partial",
  },
  {
    id: "RQ3 · Burden (core)",
    q: "What annual burden of liver cancer does dietary aflatoxin imply for India, by state, using only public data, and does it agree with independent estimates?",
    how: "Exposure from contamination × consumption ÷ body weight; JECFA cancer potency by hepatitis B status; Monte Carlo uncertainty; four validation checks fixed in advance.",
    state: "planned",
  },
  {
    id: "RQ4 · Limits",
    q: "How would the estimate change if India's aflatoxin limits were the EU's or Codex's?",
    how: "Truncate contamination at each limit (the method EFSA used for its own peanut limit) and compare expected cases.",
    state: "planned",
  },
  {
    id: "RQ5 · Data gaps",
    q: "Which missing data limit the estimate most, and what would district-level estimates need?",
    how: "Variance decomposition of the burden estimate, plus dated evidence of what India's regulator does and does not publish.",
    state: "partial",
  },
];

const STATE: Record<string, { label: string; tone: "clear" | "caution" | "neutral" }> = {
  done: { label: "done", tone: "clear" },
  partial: { label: "data in hand", tone: "caution" },
  planned: { label: "planned", tone: "neutral" },
};

const IN_SCOPE = [
  "India, national and state level",
  "Aflatoxins (B1, total, M1 in milk) and liver cancer, for the burden estimate",
  "Hazard quotient / margin of exposure screening of every measured hazard on Indian food",
  "All 1,711 India-vs-world limit pairs",
  "The hazard classifier's evaluation",
  "A quantified account of the data gap",
];

const OUT_SCOPE: [string, string][] = [
  ["An ML model trained to predict disease cases", "no dataset pairs contamination and illness; training one would mean inventing outcomes"],
  ["District, city or market estimates", "no public testing data at that grain"],
  ["Microbial hazards' burden", "needs incidence surveillance, which was unreachable"],
  ["Prevalence of contamination", "every source is targeted testing"],
  ["Ratings of brands or producers, health advice", "not what the data support"],
  ["Data obtained by getting around access controls", "the audit is read-only by design"],
];

const WEEKS: [string, string][] = [
  ["1", "Freeze the data snapshot; confirm access terms; pre-register on OSF; supervisor review"],
  ["2–4", "Systematic review of aflatoxin occurrence in Indian foods (PRISMA); double extraction on 20%"],
  ["3–4", "Consumption (HCES 2022-23), body weight, hepatitis B prevalence, population, GBD validation data"],
  ["5–6", "Burden runs, validation checks, limit scenarios, sensitivity analysis"],
  ["7–11", "Writing, internal and supervisor review"],
  ["12", "Preprint and journal submission; code and data released with a DOI"],
];

export default function BriefPage() {
  const std = useSnapshot("standards_summary");
  const src = useSnapshot("sources");
  const hz = useSnapshot("hazards");
  const rows = (id: string) => src.data?.find((s) => s.id === id)?.rows;
  const limits = (std.data?.rows ?? []).reduce((a, r) => a + r.n, 0);
  const f = std.data?.flags;

  return (
    <Page>
      <header className="mb-10">
        <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-ink">Research briefing</div>
        <h1 className="mb-4 font-display text-3xl font-light leading-tight sm:text-4xl">
          Estimating the disease burden of food contamination in India from open data
        </h1>
        <p className="register mb-4 text-sm text-provenance">
          Chaitanya Tripathi · suhsuhbros@gmail.com · plan version 1, October 2026 ·{" "}
          <Ext href={PLAN}>full research plan</Ext> · <Ext href="https://github.com/ultramagnus23/FoodSafe">code</Ext>
        </p>
        <div className="max-w-prose space-y-3 leading-relaxed text-provenance">
          <p>
            Food contamination causes disease, but in India nobody can say how much, where, or from what. The regulator
            publishes no machine-readable test results, and no public dataset records where contaminated food makes people
            ill. So a disease predictor trained on contamination and illness cannot be built honestly: there is nothing to
            train it on.
          </p>
          <p>
            There is a defensible alternative, and it is the one WHO and JECFA use: <strong className="text-ink">quantitative
            risk assessment</strong>. The dose–response comes from toxicology and epidemiology that already exist; exposure
            comes from how contaminated foods are and how much people eat; expected cases follow. This platform already holds
            most of the pieces. The paper builds the missing step for the hazard where the science is strongest, aflatoxin and
            liver cancer, and checks it against independent estimates.
          </p>
        </div>
      </header>

      <Section title="What is already built and live">
        <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Fig value={limits ? num(limits) : null} label="legal limits from FSSAI, EU, Codex, US" href="/standards" />
          <Fig value={f ? `${num(f.india_higher_than_eu)} / ${num(f.comparisons)}` : null} label="pairs where India permits more than the EU" href="/standards" />
          <Fig value={rows("rasff") != null ? num(rows("rasff")) : null} label="EU contamination findings, 164 origin countries" href="/findings" />
          <Fig value={hz.data ? `${num(hz.data.length)} hazards` : null} label="linked to the diseases they cause, each cited" href="/hazards" />
          <Fig value="0.918" label="hazard classifier accuracy on later, unseen notifications" href="/engine#classify" />
          <Fig value={rows("research_evidence") != null ? num(rows("research_evidence")) : null} label="papers in the literature layer" href="/research" />
        </div>
        <p className="max-w-prose text-sm leading-relaxed text-provenance">
          Every figure is live from the production database and keeps its source, a document hash and a confidence level;
          nothing is synthetic. The burden step&apos;s code is written and already reproduces a published risk assessment
          for India exactly (Liu &amp; Wu 2010: 0.04–1.00 liver cancers per 100,000 a year without hepatitis B, 1.2–30 with
          it). What it still needs is Indian input data.
        </p>
        <div className="mt-3">
          <SnapshotNote />
        </div>
      </Section>

      <Section title="The engine, link by link">
        <Table minWidth={640}>
          <thead>
            <tr>
              <Th>Risk-assessment step</Th>
              <Th>On this platform</Th>
              <Th>State</Th>
            </tr>
          </thead>
          <tbody>
            {[
              ["Rules", "India's limits beside the EU, Codex and the US, with the reason for each gap", "clear", "built"],
              ["Hazard identification", "Knowledge-base rules, then a text classifier validated on later data", "clear", "built"],
              ["Hazard characterisation", "Cited outcomes, vulnerable groups, IARC groups, reference doses, JECFA cancer potency", "clear", "built"],
              ["Exposure", "Occurrence × consumption ÷ body weight; code built, Indian inputs to assemble", "caution", "partial"],
              ["Risk characterisation", "Expected cases with uncertainty, margin of exposure, hazard quotient", "caution", "code built"],
              ["Validation", "Replication done; agreement with independent estimates planned", "caution", "partial"],
              ["Illness observed in the same place", "Not public anywhere in India", "risk", "missing"],
            ].map(([step, what, tone, label]) => (
              <tr key={step}>
                <Td className="text-ink">{step}</Td>
                <Td className="text-provenance">{what}</Td>
                <Td>
                  <Tag tone={tone as "clear" | "caution" | "risk"}>{label}</Tag>
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Section>

      <Section title="The paper: five questions">
        <ol className="space-y-4">
          {RQS.map((r) => (
            <li key={r.id} className="rounded-lg border border-line bg-slab p-4">
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <span className="register text-xs text-provenance">{r.id}</span>
                <Tag tone={STATE[r.state].tone}>{STATE[r.state].label}</Tag>
              </div>
              <p className="mb-1 text-ink">{r.q}</p>
              <p className="text-sm text-provenance">{r.how}</p>
            </li>
          ))}
        </ol>
      </Section>

      <Section title="Scope">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="rounded-lg border border-line bg-slab p-5">
            <div className="mb-2 font-semibold text-ink">Included</div>
            <ul className="list-disc space-y-1.5 pl-5 text-sm text-provenance">
              {IN_SCOPE.map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
          </div>
          <div className="rounded-lg border border-line bg-slab p-5">
            <div className="mb-2 font-semibold text-ink">Not included, and why</div>
            <ul className="list-disc space-y-1.5 pl-5 text-sm text-provenance">
              {OUT_SCOPE.map(([x, why]) => (
                <li key={x}>
                  <span className="text-ink">{x}</span>: {why}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </Section>

      <Section title="How the estimate will be checked">
        <ol className="max-w-prose list-decimal space-y-2 pl-5 text-sm leading-relaxed text-provenance">
          <li>
            <span className="text-ink">Replication (done).</span> From Liu &amp; Wu&apos;s published inputs, the engine returns
            their published incidences for India exactly.
          </li>
          <li>
            <span className="text-ink">External consistency.</span> The national estimate against Liu &amp; Wu&apos;s range for
            India and WHO&apos;s 2021 global total (13,996 aflatoxin liver cancers a year).
          </li>
          <li>
            <span className="text-ink">Plausibility bound.</span> In every state, aflatoxin-attributable cases must stay below
            total liver-cancer incidence (GBD, India State-Level Disease Burden Initiative). A violation is reported as a
            failure, never tuned away.
          </li>
          <li>
            <span className="text-ink">Sensitivity.</span> Which input drives the uncertainty, and how much better data would
            narrow it.
          </li>
        </ol>
        <p className="mt-4 max-w-prose text-sm text-provenance">
          Hypotheses, decision rules and analyses are pre-registered before the model runs on Indian data.
        </p>
      </Section>

      <Section title="Timeline: twelve weeks from supervisor agreement">
        <Table minWidth={560}>
          <thead>
            <tr>
              <Th>Week</Th>
              <Th>Work</Th>
            </tr>
          </thead>
          <tbody>
            {WEEKS.map(([w, what]) => (
              <tr key={w}>
                <Td className="register whitespace-nowrap">{w}</Td>
                <Td className="text-provenance">{what}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Section>

      <Section title="What I am asking for">
        <ol className="max-w-prose list-decimal space-y-2 pl-5 text-sm leading-relaxed text-provenance">
          <li>Is risk assessment (expected burden from published dose–response) the right way to build a disease engine without paired outcome data? What would make it convincing to you?</li>
          <li>A review of the occurrence-review protocol and the validation checks before the model runs.</li>
          <li>Advice on the journal, and on whether the data-access audit belongs inside the paper or beside it.</li>
          <li>Introductions to epidemiologists or toxicologists working on aflatoxin, liver cancer or dietary exposure in India.</li>
          <li>If it fits: supervision of the paper.</li>
        </ol>
        <p className="mt-5 text-sm text-provenance">
          Chaitanya Tripathi · suhsuhbros@gmail.com · <Ext href={PLAN}>full plan with methods, data sources and references</Ext>
        </p>
      </Section>

      <Section title="Read further">
        <ul className="grid gap-2 text-sm sm:grid-cols-2">
          <li>
            <Link href="/engine" className="underline">
              Disease engine
            </Link>{" "}
            <span className="text-provenance">· classify a report, outcome profiles, safe intake</span>
          </li>
          <li>
            <Link href="/standards" className="underline">
              India vs EU, Codex, US limits
            </Link>
          </li>
          <li>
            <Link href="/findings" className="underline">
              Contamination findings
            </Link>
          </li>
          <li>
            <Link href="/sources" className="underline">
              Sources and confidence
            </Link>
          </li>
          <li>
            <Ext href={`${REPO}docs/PLATFORM.md`}>How the platform is built</Ext>
          </li>
          <li>
            <Ext href={`${REPO}docs/PAPER_SCOPING.md`}>Data-access audit</Ext>
          </li>
          <li>
            <Ext href={`${REPO}docs/BACKTEST_SAMPLING.md`}>State sampling backtest</Ext>
          </li>
          <li>
            <Ext href={`${REPO}models/burden_engine.py`}>Burden engine code</Ext>
          </li>
        </ul>
        <p className="mt-6 max-w-prose text-xs leading-relaxed text-provenance">
          Legal limits are regulatory lines, not safety verdicts. EU notifications and Indian state samples are risk-targeted,
          so nothing here is a prevalence estimate.
        </p>
      </Section>
    </Page>
  );
}

function Fig({ value, label, href }: { value: string | null; label: string; href: string }) {
  return (
    <Link href={href} className="block rounded-lg border border-line bg-slab p-4 transition-colors hover:border-line-strong">
      <div className="register mb-1 text-xl font-medium text-ink">{value ?? "—"}</div>
      <div className="text-xs leading-snug text-provenance">{label}</div>
    </Link>
  );
}
