const SECTIONS = [
  {
    title: "Data Sources",
    body: "We ingest enforcement records from FSSAI (weekly PDF scrapes and RTI responses), USFDA import refusal reports, and AGMARKNET commodity/district reference data. All raw files are archived with source URLs preserved for every record where available.",
  },
  {
    title: "Confidence Scoring",
    body: "Every record receives a confidence score: base 0.70, +0.15 if manually verified, +0.10 if from a Tier-1 lab (ICAR/NABL), +0.05 if the value is in typical range for that commodity, −0.10 if OCR confidence is below 80%. Only records scoring ≥ 0.75 are used in downstream models.",
  },
  {
    title: "FSSAI vs. International Benchmarks",
    body: "Every contaminant carries both an FSSAI limit and a Codex Alimentarius / EU limit. A sample can pass India's own test while failing the international one: we call this the Codex gap, and it is one of the platform's central findings, not an edge case.",
  },
  {
    title: "Disease Burden (PAF)",
    body: "Where dose-response data exists (IARC/JECFA monographs), we estimate a Population Attributable Fraction: the modelled share of a disease's incidence in a district attributable to dietary exposure to a contaminant. PAF is always reported with a 95% Monte Carlo confidence interval. It is a statistical estimate, not a diagnosis or a causal claim about any individual.",
  },
  {
    title: "Inference Types",
    body: "\"direct\" means the estimate is computed directly from enforcement records for that district/commodity/contaminant. \"propagated\" means it is inferred from a supply-chain model with no direct test. \"insufficient_data\" means there isn't enough data to estimate at all: we return null, not zero, because zero would imply safety we cannot claim.",
  },
  {
    title: "What We Will Never Do",
    body: "We will never name a specific brand, manufacturer, or batch in a risk or disease-burden output. We will never state a product is \"unsafe\" without a direct government enforcement source. All disclaimers are permanent and non-dismissible past 24 hours.",
  },
];

const MODEL_CARD_SECTIONS = [
  {
    title: "Risk score methodology",
    body: "District/commodity risk scores are computed by a statistical aggregation (fail rate over the trailing quarter, Wilson 95% confidence interval, saturating severity curve) over enforcement records with confidence ≥ 0.75. A Random Forest classifier is also trained (features: 12-month fail rate, test volume, water quality index, industrial proximity, seasonality, historical trend, population density, state-level prior) with geographic holdout cross-validation, but it is not yet what's served to users. The statistical aggregation is, because the model currently has too little independent data to outperform it.",
  },
  {
    title: "Data currently backing India scores",
    body: "FSSAI has no programmatically accessible enforcement dataset today (see the FSSAI ingestion findings below), so this deployment shows no district-level India risk scores: the map is empty on purpose rather than filled with invented numbers, and synthetic demonstration data is not loaded here. If demo data is ever loaded (for example in a local demo), every score, map marker, and search result carries a provenance badge, either \"Demo data\" or \"Verified source\", so it is never ambiguous. The real India data that exists today is limited to two grains: State/UT-level counts of food samples analysed and found non-conforming, and national commodity-level counts of samples with pesticide residues above the legal limit, both disclosed to Parliament (see the Directory). The aggregation logic itself is real and would compute identically over district-level data the moment it exists.",
  },
  {
    title: "Calibration",
    body: "Not yet done. The risk score is a model-internal probability, not a calibrated real-world frequency (e.g. Platt/isotonic scaling against held-out outcomes). Treat risk scores as a ranking signal, not a literal percentage chance of contamination.",
  },
  {
    title: "Backtest status",
    body: "A temporal-split backtest was run against every real (non-synthetic) enforcement record in the database: 66 openFDA records, 2020–2026. Result: not statistically meaningful, and we're publishing that null result rather than a misleading metric. Every one of those 66 records is a confirmed recall (openFDA's feed is a recall log, not a sampled pass/fail test set), so there is no negative class to score discrimination against, and the records are too sparse per commodity regardless. See the full report for the methodology and what would unblock a real backtest.",
  },
  {
    title: "Backtest on real state sampling outcomes",
    body: "A pre-specified temporal backtest was later run on real State/UT counts of food samples analysed and found non-conforming (Lok Sabha answers, 2013–14 to 2025–26; 173 one-year-ahead forecasts across six years). A state's rate in one year predicts its rate the next year far better than the national rate does (average error 4.8 vs 13.1 percentage points, and the ordering of states is highly stable); a control with shuffled state labels removes the effect. But no model beat simply reusing last year's rate, and that stability may reflect where and how inspectors sample rather than how contaminated food is. This is a statement about a testing rate, not a food-risk score.",
  },
];

export default function MethodologyPage() {
  return (
    <div className="mx-auto max-w-2xl px-6 py-12">
      <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-ink">Methodology &amp; Sources</div>
      <h1 className="mb-8 font-display text-4xl font-light leading-tight">
        How <em className="text-ink not-italic italic">FoodSafe India</em> works
      </h1>
      {SECTIONS.map((s) => (
        <div key={s.title} className="mb-8">
          <h2 className="mb-2 font-display text-xl font-normal text-ink">{s.title}</h2>
          <p className="leading-relaxed text-provenance">{s.body}</p>
        </div>
      ))}
      <div className="mb-8 rounded-lg border border-line bg-provenance-pale p-5">
        <p className="text-sm text-ink">
          See the full{" "}
          <a href="/methodology/standards" className="underline">
            FSSAI vs. Codex Alimentarius benchmark table
          </a>{" "}
          for every tracked contaminant.
        </p>
      </div>

      <div className="mb-3 mt-12 text-xs font-semibold uppercase tracking-wide text-ink">Model Card</div>
      <h2 className="mb-6 font-display text-2xl font-light leading-tight">Limitations, calibration, and backtest status</h2>
      {MODEL_CARD_SECTIONS.map((s) => (
        <div key={s.title} className="mb-8">
          <h3 className="mb-2 font-display text-xl font-normal text-ink">{s.title}</h3>
          <p className="leading-relaxed text-provenance">{s.body}</p>
        </div>
      ))}
      <div className="mb-8 rounded-lg border border-line bg-provenance-pale p-5">
        <p className="text-sm text-ink">
          Full backtest methodology and the raw finding:{" "}
          <a
            href="https://github.com/ultramagnus23/FoodSafe/blob/main/docs/BACKTEST_REPORT.md"
            target="_blank"
            rel="noreferrer"
            className="underline"
          >
            docs/BACKTEST_REPORT.md
          </a>{" "}
          and the state-level backtest in{" "}
          <a
            href="https://github.com/ultramagnus23/FoodSafe/blob/main/docs/BACKTEST_SAMPLING.md"
            target="_blank"
            rel="noreferrer"
            className="underline"
          >
            docs/BACKTEST_SAMPLING.md
          </a>
          . FSSAI/FoSCoS access findings: see{" "}
          <a
            href="https://github.com/ultramagnus23/FoodSafe/blob/main/docs/FSSAI_INGESTION.md"
            target="_blank"
            rel="noreferrer"
            className="underline"
          >
            docs/FSSAI_INGESTION.md
          </a>
          .
        </p>
      </div>

      <div className="disclaimer">
        <strong>Legal notice. </strong>
        This platform provides statistical risk estimates based on publicly available government enforcement data.
        It is not a laboratory testing service. All risk and disease-burden scores include confidence intervals.
        Inference-based scores are clearly distinguished from direct-test scores at all times.
      </div>
    </div>
  );
}
