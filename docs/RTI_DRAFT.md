# Draft RTI request — NOT FILED

Drafted 2026-07-04 for review. Do not submit until you've filled in the
bracketed placeholders and decided on scope (see notes at the bottom).
Two things this is useful for even if you decide not to submit: (1) a
concrete data-need spec that doubles as the record-definition/schema work
from the original Phase 0 plan, (2) a documented "we tried the formal
channel" data point for the paper's Findings/Recommendations sections,
whether it succeeds, is refused, or goes unanswered.

RTI responses are legally bound to a 30-day clock from the date the PIO
receives the request (Section 7(1), RTI Act 2005) — that clock does not
start until this is actually filed. If you want the response in hand
before the paper's writing weeks, file as early as possible.

---

## Filing options

1. **Online (fastest, recommended):** https://rtionline.gov.in — covers
   central government bodies including FSSAI. Fee (₹10) payable by
   card/net-banking/UPI through the portal itself.
2. **By post:** address below, with a ₹10 Indian Postal Order (IPO) or
   demand draft in favour of "Accounts Officer, FSSAI", payable at New
   Delhi. Physical filing is the fallback if the online portal rejects the
   application for any reason (e.g. address-verification quirks).

Recipient (Central Public Information Officer, FSSAI):

```
The Central Public Information Officer
Food Safety and Standards Authority of India (FSSAI)
FDA Bhawan, Kotla Road
New Delhi – 110002
```

(Confirm this is still the current CPIO address/designation on
fssai.gov.in before filing — government contact details drift.)

---

## Draft letter

> To,
> The Central Public Information Officer
> Food Safety and Standards Authority of India (FSSAI)
> FDA Bhawan, Kotla Road
> New Delhi – 110002
>
> **Subject: Application under Section 6(1) of the Right to Information
> Act, 2005**
>
> Sir/Madam,
>
> I, **[YOUR FULL NAME]**, a citizen of India, residing at
> **[YOUR FULL POSTAL ADDRESS]**, request the following information under
> Section 6(1) of the Right to Information Act, 2005:
>
> 1. District-wise and state-wise data on food safety enforcement actions
>    taken by FSSAI and/or by State/UT Food Safety Departments under the
>    Food Safety and Standards Act, 2006, for the period **[START
>    MONTH/YEAR]** to **[END MONTH/YEAR]**, including but not limited to:
>    - date of inspection/sample collection and date of enforcement
>      action,
>    - state and district of the food business operator/establishment
>      inspected,
>    - product category tested (not requiring brand or firm name, if this
>      is more readily disclosable in aggregate/anonymized form),
>    - contaminant(s) or violation(s) identified, and, where recorded, the
>      quantitative test result and the applicable legal limit,
>    - the section(s) of the Food Safety and Standards Act, 2006 / rules
>      cited,
>    - the action taken (e.g. improvement notice, fine, license
>      suspension/cancellation, prosecution) and the fine amount where
>      applicable,
>    - the laboratory or testing authority that conducted the test.
> 2. Whether this data is maintained in any electronic/digital database
>    (e.g. FoSCoS or a predecessor system), and if so, whether it can be
>    provided in a machine-readable electronic format (CSV, Excel, or
>    equivalent) rather than as scanned documents, per the electronic
>    disclosure preference under Section 4(1)(a) and Section 7(9) of the
>    RTI Act (cost/practicability permitting).
> 3. If the requested time range or granularity is not available in full,
>    please provide whatever subset (narrower date range, state-level
>    rather than district-level, or a specific state/UT) is available,
>    along with a description of what is not available and why.
> 4. The name, designation, and official address of the CPIO/APIO of each
>    State/UT Food Safety Department, if this office is not itself able to
>    provide district-level data collected by state authorities, so that
>    parallel RTI requests can be filed at the state level.
>
> I am enclosing the statutory fee of ₹10/- by [Indian Postal
> Order/Demand Draft No. **[NUMBER]** dated **[DATE]**, drawn on
> **[BANK]**] in favour of "Accounts Officer, FSSAI", payable at New
> Delhi. [If filing online: fee paid online via the RTI portal, receipt
> enclosed.]
>
> Kindly provide the information within the statutory period of 30 days
> as prescribed under Section 7(1) of the RTI Act, 2005.
>
> Thanking you,
>
> **[YOUR FULL NAME]**
> **[YOUR PHONE NUMBER]**
> **[YOUR EMAIL]**
> Date: **[DATE OF FILING]**
> Place: **[YOUR CITY]**

---

## Notes / decisions for you before filing

1. **Scope vs. speed tradeoff.** Item 1 as written is broad (full schema,
   multi-year range) — broad requests are more likely to get a partial
   refusal or a "not centrally maintained, contact state authorities"
   response, which is *itself* useful data for the paper (documents that
   the data isn't centrally structured) but slower than a narrower ask.
   Consider filing this exact broad version to one central FSSAI CPIO, and
   separately deciding whether to also fire narrower state-level requests
   in parallel (item 4 in the letter sets that up regardless).
2. **Time window placeholders** — pick a range that matches whatever
   `PAPER_SCOPING.md` eventually settles on, or leave it broad ("earliest
   available to present") to maximize the chance of learning what actually
   exists internally, independent of what's public.
3. **Grounds for refusal to anticipate:** FSSAI may cite Section 8(1)(j)
   (personal information exemption) if district-level data could identify
   specific FBOs/individuals — this is exactly the same brand/firm
   anonymization tension flagged in the paper's ethics section, so a
   refusal on those grounds is itself a citable, on-topic finding, not just
   a dead end.
4. **First appeal path**, if no response within 30 days or an unsatisfying
   response: Section 19(1) first appeal to the First Appellate Authority
   (a designated FSSAI officer senior to the CPIO) within 30 days of the
   response deadline. Worth deciding now whether you'll pursue this if the
   initial request stalls, since it affects the realistic total timeline
   (30 days + possible appeal cycle) for whether an RTI response can make
   it into the paper's writing window at all.
