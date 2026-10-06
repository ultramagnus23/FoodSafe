"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  Bars,
  Chips,
  Field,
  inputClass,
  LoadState,
  Page,
  PageHeader,
  Section,
  SnapshotNote,
  Table,
  Tag,
  Td,
  Th,
} from "@/components/ui/DataBlocks";
import { classify, MODEL_THRESHOLD, type Classification } from "@/lib/classifier";
import {
  capitalise,
  cleanHazard,
  grams,
  mgkg,
  num,
  useCountryNames,
  useSnapshot,
  type HealthProfile,
} from "@/lib/snapshot";

type Status = "built" | "partial" | "missing";
const STATUS: Record<Status, { label: string; tone: "clear" | "caution" | "risk" }> = {
  built: { label: "Built", tone: "clear" },
  partial: { label: "Partial", tone: "caution" },
  missing: { label: "Missing", tone: "risk" },
};

const EXAMPLES = [
  "Aflatoxin found in red chilli powder sold in a city market",
  "Ethylene oxide above limit in sesame seeds",
  "Turmeric powder adulterated with lead chromate",
  "Salmonella detected in chicken samples",
  "Chlorpyrifos residue above MRL in okra",
];

export default function EnginePage() {
  return (
    <Page>
      <PageHeader kicker="Disease risk engine" title="From a contamination finding to the diseases it can cause">
        <p>
          The engine takes a food-safety finding and works through the steps food-safety risk assessment uses (Codex
          Alimentarius: hazard identification, hazard characterisation, exposure, risk characterisation). It names the
          hazard, links it to the illnesses it is known to cause with a source for each, says who is most at risk, and
          works out how much of the food reaches a safe-intake limit at the measured concentration.
        </p>
        <p>
          It predicts <em>which</em> diseases a finding points to and <em>for whom</em>. It does not yet predict how many
          people fall ill: no public dataset measures contamination and illness in the same place. The{" "}
          <Link href="/brief" className="underline">
            research plan
          </Link>{" "}
          sets out how that step will be built and validated.
        </p>
        <SnapshotNote />
      </PageHeader>

      <Section id="chain" title="How the engine works, and which links are built">
        <Chain />
      </Section>

      <Section
        id="classify"
        title="Try it: classify a food-safety report"
        note={
          <>
            Paste a headline, complaint or notification. Rules from the hazard knowledge base run first; a model trained on
            EU notifications runs alongside and is used only when it is at least {Math.round(MODEL_THRESHOLD * 100)}% sure.
            It reads what the text says; it cannot test any food. Runs in your browser.
          </>
        }
      >
        <Classifier />
      </Section>

      <Section
        id="profiles"
        title="What the findings on a country's food point to"
        note="Every EU border or market finding on a food is classified by hazard, and each hazard linked to the outcomes it can cause. Counts are findings, not illnesses: these are risk-targeted checks of traded food, not a sample of anyone's diet."
      >
        <Profiles />
      </Section>

      <Section
        id="intake"
        title="How much of that food reaches a safe-intake limit"
        note="For recent findings on food from India with a measured concentration: the grams a 60 kg adult could eat every day for life within the acceptable daily intake, or in one day within the acute reference dose (EFSA, JMPR, JECFA values). Where no safe level exists (genotoxic carcinogens, or a withdrawn value) no number is given. One sample's value: an illustration, not anyone's diet."
      >
        <Intake />
      </Section>

      <Section id="limits" title="What this engine can and cannot tell you">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="rounded-lg border border-line bg-slab p-5 text-sm leading-relaxed">
            <div className="mb-2 font-semibold text-ink">It can</div>
            <ul className="list-disc space-y-1.5 pl-5 text-provenance">
              <li>Name the hazard in a report or notification, and say how it decided.</li>
              <li>List the illnesses that hazard is known to cause, with the source of each link.</li>
              <li>Say who is most vulnerable (children, pregnancy, people with liver disease, and so on).</li>
              <li>Turn a measured concentration into grams of food that reach a safe-intake limit.</li>
              <li>Profile which outcomes dominate the findings on each country&apos;s food.</li>
            </ul>
          </div>
          <div className="rounded-lg border border-line bg-slab p-5 text-sm leading-relaxed">
            <div className="mb-2 font-semibold text-ink">It cannot, yet</div>
            <ul className="list-disc space-y-1.5 pl-5 text-provenance">
              <li>Estimate how many people fall ill in a place: that needs measured exposure and observed illness together.</li>
              <li>Say how common contamination is: every source here is risk-targeted testing, not random sampling.</li>
              <li>Rank brands or producers, or certify any food as safe.</li>
              <li>Replace a laboratory: the classifier reads text, it detects nothing.</li>
            </ul>
          </div>
        </div>
      </Section>
    </Page>
  );
}

function Chain() {
  const std = useSnapshot("standards_summary");
  const rasff = useSnapshot("rasff_countries");
  const sources = useSnapshot("sources");
  const hz = useSnapshot("hazards");
  const states = useSnapshot("states");
  const measured = useSnapshot("rasff_india_measured");

  const limits = (std.data?.rows ?? []).reduce((a, r) => a + r.n, 0);
  // Distinct notifications (a notification can name several origins, so per-origin counts overlap).
  const notifs = sources.data?.find((x) => x.id === "rasff")?.rows ?? 0;
  const origins = rasff.data?.length;
  const effects = (hz.data ?? []).reduce((a, h) => a + h.effects.length, 0);
  const stateCount = states.data?.length;

  const stages: { n: string; title: string; codex: string; status: Status; body: string; data: string; href: string }[] = [
    {
      n: "1",
      title: "Rules",
      codex: "context",
      status: "built",
      body: "What each country's law allows in food: pesticide residue limits and contaminant maximum levels.",
      data: limits ? `${num(limits)} legal limits from FSSAI, the EU, Codex and the US` : "legal limits from four rule-books",
      href: "/standards",
    },
    {
      n: "2",
      title: "Findings",
      codex: "exposure evidence",
      status: "partial",
      body: "What is actually found in food. For India: yearly state totals from Parliament and EU border checks of exports. No district or market testing is public.",
      data: notifs ? `${num(notifs)} EU notifications from ${num(origins)} origins; ${num(stateCount)} Indian states and UTs` : "EU notifications; Indian state totals",
      href: "/findings",
    },
    {
      n: "3",
      title: "Hazard identification",
      codex: "hazard identification",
      status: "built",
      body: "Which hazard a finding or report is about: knowledge-base rules, then a text classifier tested on later notifications.",
      data: "Classifier accuracy 0.918 (macro-F1 0.777) on 6,934 later EU notifications",
      href: "#classify",
    },
    {
      n: "4",
      title: "Hazard to disease",
      codex: "hazard characterisation",
      status: "built",
      body: "What each hazard does to people, how fast, and to whom; reference doses where they exist.",
      data: hz.data ? `${num(hz.data.length)} curated hazards, ${num(effects)} cited outcome links, IARC groups for 1,128 agents` : "cited hazard knowledge base",
      href: "/hazards",
    },
    {
      n: "5",
      title: "Exposure and risk",
      codex: "exposure + risk characterisation",
      status: "partial",
      body: "How much of a food reaches a safe-intake limit at a measured concentration. The burden step (expected cases from published cancer potency) is coded and reproduces a published assessment; Indian contamination and consumption inputs are being assembled.",
      data: measured.data ? `${num(measured.data.length)} recent measured findings on Indian food assessed` : "safe-intake calculator",
      href: "#intake",
    },
    {
      n: "6",
      title: "Illness observed",
      codex: "validation",
      status: "missing",
      body: "Where contaminated food actually makes people ill. Nothing public links the two in the same place, which is what a trained predictor would need.",
      data: "Next: burden estimates from published dose-response, checked against independent estimates",
      href: "/brief",
    },
  ];

  return (
    <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {stages.map((s) => (
        <li key={s.n} className="flex flex-col rounded-lg border border-line bg-slab p-4">
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="register text-xs text-provenance">
              {s.n} · {s.codex}
            </span>
            <Tag tone={STATUS[s.status].tone}>{STATUS[s.status].label}</Tag>
          </div>
          <div className="mb-1 font-display text-lg text-ink">{s.title}</div>
          <p className="mb-3 flex-1 text-sm leading-relaxed text-provenance">{s.body}</p>
          {s.href.startsWith("#") ? (
            <a href={s.href} className="register text-xs text-ink underline">
              {s.data}
            </a>
          ) : (
            <Link href={s.href} className="register text-xs text-ink underline">
              {s.data}
            </Link>
          )}
        </li>
      ))}
    </ol>
  );
}

function Classifier() {
  const [text, setText] = useState("");
  const [asked, setAsked] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [result, setResult] = useState<Classification | null>(null);
  const [error, setError] = useState<string | null>(null);
  const model = useSnapshot("hazard_model", asked);
  const rules = useSnapshot("hazard_rules", asked);
  const hazards = useSnapshot("hazards");

  const ready = model.data && rules.data && hazards.data;
  const loading = pending != null && !ready && !model.error && !rules.error;

  function run(input: string) {
    setText(input);
    setAsked(true);
    if (input.trim().length < 3) {
      setError("Type at least a few words describing the problem.");
      setResult(null);
      return;
    }
    setError(null);
    setPending(input);
  }

  // The model (1.4 MB) loads on first use; the waiting text is classified once it arrives.
  useEffect(() => {
    if (pending == null || !model.data || !rules.data || !hazards.data) return;
    setResult(classify(pending, model.data, rules.data, hazards.data));
    setPending(null);
  }, [pending, model.data, rules.data, hazards.data]);

  return (
    <div>
      <label className="sr-only" htmlFor="cl-text">
        Report text
      </label>
      <textarea
        id="cl-text"
        maxLength={500}
        rows={3}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) run(text);
        }}
        placeholder="e.g. Aflatoxin found in red chilli powder sold in Mumbai market"
        className={`${inputClass} w-full`}
      />
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button type="button" onClick={() => run(text)} className="rounded bg-ink px-4 py-2 text-sm font-medium text-on-ink">
          Classify
        </button>
        {EXAMPLES.map((ex) => (
          <button key={ex} type="button" onClick={() => run(ex)} className="rounded border border-line px-2.5 py-1.5 text-xs text-provenance hover:bg-provenance-pale">
            {ex.split(" ").slice(0, 4).join(" ")}…
          </button>
        ))}
      </div>
      <div className="mt-5" aria-live="polite">
        {error ? <p className="text-sm text-risk">{error}</p> : null}
        <LoadState error={model.error || rules.error} loading={loading} what="the classifier (1.4 MB, once)" />
        {result ? <ClassificationCard r={result} /> : null}
      </div>
    </div>
  );
}

function ClassificationCard({ r }: { r: Classification }) {
  const vulnerable = Array.from(new Set(r.effects.flatMap((e) => e.vulnerable ?? [])));
  return (
    <div className="rounded-lg border border-line bg-slab p-5">
      <div className="mb-1 font-display text-xl text-ink">{r.label}</div>
      <p className="mb-4 text-sm text-provenance">
        Decided because {r.decidedBy}.{r.hazardClass ? ` Hazard class: ${r.hazardClass}.` : ""}
      </p>
      {r.effects.length ? (
        <>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink">
            What this {r.pesticideClass ? "class of pesticide" : "hazard"} can cause
          </div>
          <ul className="mb-4 space-y-2 text-sm">
            {r.effects.map((e, i) => (
              <li key={i} className="leading-relaxed">
                <span className="text-ink">{e.outcome}</span>{" "}
                <span className="text-provenance">
                  ({e.organ}, {e.exposure}
                  {e.onset ? `, onset ${e.onset}` : ""})
                </span>{" "}
                <a href={e.url} className="text-provenance underline" target="_blank" rel="noreferrer">
                  {e.source}
                </a>
              </li>
            ))}
          </ul>
          {vulnerable.length ? (
            <p className="mb-4 text-sm text-provenance">
              <span className="font-semibold text-ink">Most at risk: </span>
              {vulnerable.join(", ")}
            </p>
          ) : null}
        </>
      ) : r.matchedHazard ? (
        <p className="mb-4 text-sm text-provenance">No single health outcome is asserted for this hazard (it depends on substance and dose).</p>
      ) : null}
      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink">Model</div>
      <div className="space-y-1.5">
        {r.model.probs.slice(0, 3).map((p) => (
          <div key={p.category} className="grid grid-cols-[minmax(0,2fr)_minmax(80px,3fr)_auto] items-center gap-3 text-sm">
            <span className="truncate">{capitalise(p.category)}</span>
            <div className="h-2 overflow-hidden rounded-sm bg-provenance-pale" aria-hidden="true">
              <div className="h-full origin-left bg-ink" style={{ transform: `scaleX(${p.p})` }} />
            </div>
            <span className="register w-10 text-right text-xs">{Math.round(100 * p.p)}%</span>
          </div>
        ))}
      </div>
      {r.model.why.length ? <p className="mt-2 text-xs text-provenance">Driven by: {r.model.why.join(", ")}</p> : null}
      <p className="mt-3 text-xs text-provenance">Classifies what the text says, not whether any food is contaminated.</p>
    </div>
  );
}

const DEFAULT_COMPARE = ["IN", "CN", "TR", "TH", "VN", "US"];

function Profiles() {
  const prof = useSnapshot("health_profiles");
  const co = useSnapshot("rasff_countries");
  const names = useCountryNames();
  const [origin, setOrigin] = useState("IN");
  const [exposure, setExposure] = useState<"" | "acute" | "chronic">("");
  const [picked, setPicked] = useState<string[]>(DEFAULT_COMPARE);

  const origins = useMemo(() => {
    const have = new Set((prof.data ?? []).map((p) => p.origin));
    const list = (co.data ?? []).filter((c) => c.notifications >= 100 && have.has(c.origin)).map((c) => c.origin);
    return ["IN", ...list.filter((o) => o !== "IN")];
  }, [prof.data, co.data]);

  if (prof.error || prof.isLoading) return <LoadState error={prof.error} loading what="health profiles" />;
  const rows = (prof.data ?? [])
    .filter((p) => p.origin === origin && (!exposure || p.exposure === exposure || p.exposure === "both"))
    .slice(0, 14);

  const compareOrigins = picked.filter((o) => (prof.data ?? []).some((p) => p.origin === o));
  const byOutcome: Record<string, { outcome: string } & Record<string, HealthProfile | string>> = {};
  for (const p of prof.data ?? []) {
    if (!compareOrigins.includes(p.origin)) continue;
    (byOutcome[p.outcome_key] ||= { outcome: p.outcome })[p.origin] = p;
  }
  const keys = Object.keys(byOutcome).sort((a, b) => {
    const m = (k: string) => Math.max(...compareOrigins.map((o) => ((byOutcome[k][o] as HealthProfile | undefined)?.notifications ?? 0)));
    return m(b) - m(a);
  });

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end gap-4">
        <Field label="Food from">
          <select value={origin} onChange={(e) => setOrigin(e.target.value)} className={inputClass}>
            {origins.map((o) => (
              <option key={o} value={o}>
                {names[o] || o}
              </option>
            ))}
          </select>
        </Field>
        <div className="text-xs text-provenance">
          <span className="mb-1 block font-semibold uppercase tracking-wide">Exposure</span>
          <Chips
            label="Exposure"
            value={exposure}
            onChange={setExposure}
            options={[
              ["", "Acute and chronic"],
              ["acute", "Acute"],
              ["chronic", "Chronic"],
            ]}
          />
        </div>
      </div>
      <Bars
        rows={rows.map((r) => ({
          key: r.outcome_key,
          label: r.outcome,
          sub: `${r.organ_system} · ${r.exposure} · ${Array.from(new Set((r.top_hazards ?? []).map((h) => cleanHazard(h[0])))).slice(0, 2).join(", ")}`,
          value: r.notifications,
          display: num(r.notifications),
        }))}
      />
      <h3 className="mb-2 mt-8 font-display text-lg">Side by side</h3>
      <p className="mb-3 text-sm text-provenance">Share of each origin&apos;s classified findings whose hazard can cause the outcome. Choose up to eight origins.</p>
      <div className="mb-4 flex flex-wrap gap-1.5" role="group" aria-label="Origins to compare">
        {origins.slice(0, 18).map((o) => {
          const on = picked.includes(o);
          return (
            <button
              key={o}
              type="button"
              aria-pressed={on}
              onClick={() =>
                setPicked((cur) => (on ? (cur.length > 1 ? cur.filter((x) => x !== o) : cur) : cur.length < 8 ? [...cur, o] : cur))
              }
              className={`rounded border px-2.5 py-1 text-xs ${on ? "border-ink bg-ink text-on-ink" : "border-line text-provenance hover:bg-provenance-pale"}`}
            >
              {names[o] || o}
            </button>
          );
        })}
      </div>
      <Table minWidth={560} caption="Share of classified findings by outcome and origin">
        <thead>
          <tr>
            <Th>Outcome</Th>
            {compareOrigins.map((o) => (
              <Th key={o} right>
                {names[o] || o}
              </Th>
            ))}
          </tr>
        </thead>
        <tbody>
          {keys.slice(0, 16).map((k) => (
            <tr key={k}>
              <Td>{byOutcome[k].outcome}</Td>
              {compareOrigins.map((o) => {
                const p = byOutcome[k][o] as HealthProfile | undefined;
                return (
                  <Td key={o} right>
                    {p && p.share_of_classified != null ? `${Math.round(100 * p.share_of_classified)}%` : <span className="text-provenance">—</span>}
                  </Td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </Table>
    </div>
  );
}

function Intake() {
  const m = useSnapshot("rasff_india_measured");
  if (m.error || m.isLoading) return <LoadState error={m.error} loading what="measured findings" />;
  const rows = (m.data ?? []).slice(0, 40);
  if (!rows.length) return <p className="text-sm text-provenance">No measured findings in this snapshot.</p>;
  const cell = (g: number | null) => {
    const t = grams(g);
    if (t == null) return <span className="text-provenance">—</span>;
    return g != null && g < 300 ? <Tag tone="risk">{t}</Tag> : t;
  };
  return (
    <Table minWidth={820} caption="Grams of food reaching a safe-intake limit at the measured concentration">
      <thead>
        <tr>
          <Th>Date</Th>
          <Th>Hazard</Th>
          <Th>Food</Th>
          <Th right>Measured mg/kg</Th>
          <Th right>Daily, for life</Th>
          <Th right>In one day</Th>
          <Th>Basis</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={`${r.id}-${r.hazard}`}>
            <Td className="register whitespace-nowrap text-xs">{r.date}</Td>
            <Td>{cleanHazard(r.hazard)}</Td>
            <Td className="text-provenance">{r.product}</Td>
            <Td right>{mgkg(r.mg_kg)}</Td>
            <Td right>{r.reason ? null : cell(r.chronic_g)}</Td>
            <Td right>{r.reason ? null : cell(r.acute_g)}</Td>
            <Td className="text-xs text-provenance">
              {r.reason ? (
                <>
                  <Tag tone="risk" title={r.reason}>
                    no safe amount
                  </Tag>{" "}
                  {r.reason.split(/[:(;]/)[0]}
                </>
              ) : (
                r.guidance
              )}{" "}
              <a href={r.url} className="underline" target="_blank" rel="noreferrer">
                notice
              </a>
            </Td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}
