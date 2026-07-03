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
    body: "Every contaminant carries both an FSSAI limit and a Codex Alimentarius / EU limit. A sample can pass India's own test while failing the international one — we call this the Codex gap, and it is one of the platform's central findings, not an edge case.",
  },
  {
    title: "Disease Burden (PAF)",
    body: "Where dose-response data exists (IARC/JECFA monographs), we estimate a Population Attributable Fraction — the modelled share of a disease's incidence in a district attributable to dietary exposure to a contaminant. PAF is always reported with a 95% Monte Carlo confidence interval. It is a statistical estimate, not a diagnosis or a causal claim about any individual.",
  },
  {
    title: "Inference Types",
    body: "\"direct\" means the estimate is computed directly from enforcement records for that district/commodity/contaminant. \"propagated\" means it is inferred from a supply-chain model with no direct test. \"insufficient_data\" means there isn't enough data to estimate at all — we return null, not zero, because zero would imply safety we cannot claim.",
  },
  {
    title: "What We Will Never Do",
    body: "We will never name a specific brand, manufacturer, or batch in a risk or disease-burden output. We will never state a product is \"unsafe\" without a direct government enforcement source. All disclaimers are permanent and non-dismissible past 24 hours.",
  },
];

export default function MethodologyPage() {
  return (
    <div className="mx-auto max-w-2xl px-6 py-12">
      <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-forest">Methodology &amp; Sources</div>
      <h1 className="mb-8 font-serif text-4xl font-light leading-tight">
        How <em className="text-forest not-italic italic">FoodSafe India</em> works
      </h1>
      {SECTIONS.map((s) => (
        <div key={s.title} className="mb-8">
          <h2 className="mb-2 font-serif text-xl font-normal text-forest">{s.title}</h2>
          <p className="leading-relaxed text-[#44403C]">{s.body}</p>
        </div>
      ))}
      <div className="mb-8 rounded-lg border border-border bg-forest-pale p-5">
        <p className="text-sm text-forest">
          See the full{" "}
          <a href="/methodology/standards" className="underline">
            FSSAI vs. Codex Alimentarius benchmark table
          </a>{" "}
          for every tracked contaminant.
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
