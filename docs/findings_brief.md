# Contract awards in World Bank Investment Project Financing: five trends, FY2020–FY2026

*Briefing for senior management · source: World Bank Finances One, dataset DS00005 (from STEP), as of 9 Nov 2026 ·
all figures computed by `analysis/build_findings.py` from the gold tables. Complete fiscal years FY2020–FY2026
unless stated: USD 132.0 bn across 278,790 contracts. FY2027 (data to
2026-10-31) is excluded from multi-year comparisons.*

**1. Contracts are getting fewer and larger.**
Annual award value ranged from USD 15.1 bn (FY2020) to a peak of USD 21.3 bn (FY2025). FY2026 recorded USD 19.0 bn
(down 10.4% on FY2025) while the number of contracts fell 24.8%
to 33,182. The median contract rose from USD 21,973 in FY2021 to
USD 42,000 in FY2026 (+91%); it had already risen 63%
by FY2025, so this is a multi-year shift, not a one-year blip. Small Request-for-Quotation contracts account for
60% of the FY2026 drop in count (18,103 → 11,485). *Check:* the
FY2026 fall is steeper in January–June (-30.3%) than in July–December (-20.2%).
That pattern could reflect contracts not yet entered in STEP as well as a real decline, so the count should be re-checked after the next data refresh.

**2. The COVID-era surge in direct selection has unwound; open competition is at a period high.**
Direct selection took 28.6% of award value in FY2021 and 28.2% in FY2022, versus
17.5% in FY2020. Contracts whose description or project name mentions COVID-19 or vaccines account for USD 7.3 bn
of the USD 10.9 bn directly awarded in those two years. By FY2026 direct selection was down to
12.4% and the open-competitive share reached 81.8%, the highest of any complete year
(low: 65.8% in FY2021). Awards to UN agencies and other international
organisations peaked at 13.3% of value in FY2022.

**3. Value is extremely concentrated, and prior review already follows the money.**
The largest 1% of contracts (2,788 contracts, each USD 7.7 m or more) carry
54.1% of award value; the smaller half of all contracts carries 1.0%.
Prior review covers 6.2% of contracts but 63.0% of value. Request for
Quotations and Individual Consultant Selection make up 60.3% of contracts but only
6.3% of value. Implication: value-based oversight is well targeted; analytics on
the high-volume, low-value tail (e.g. split purchases, repeat awards) needs different tools, such as pattern
detection rather than case-by-case review.

**4. Firms registered in China are the largest foreign supplier group, mostly in civil works.**
Outside China's own projects, Chinese-registered firms won USD 19.1 bn: 14.8% of
award value and 22.3% of Works value in those countries, through
1,304 contracts in 102 borrower countries or regional programmes;
85.6% of their value is Works. Among firms competing outside their home country,
they won 41.7% of value, more than the next five supplier countries combined
(USD 7.8 bn; second is India with USD 1.8 bn). Their share of regional award value (excluding China) is highest in
Eastern and Southern Africa (27.9%) and
Western and Central Africa (16.9%). This is a lower
bound: a further USD 0.3 bn went to suppliers with Chinese names but no recorded country.

**5. Domestic firms win 60.1% of value overall, but this ranges from 41.9% to 77.2% by region.**
The domestic share (value to firms registered in the borrower country, as a share of value to all identified suppliers)
ranged between 53.4% and 64.5% across fiscal years. It is lowest in
Eastern and Southern Africa (41.9%), the largest region by award value (23.8% of the total),
and highest in South Asia (77.2%). In Eastern and Southern Africa, domestic firms win
38.7% of Works value. Where local contracting capacity
is the policy aim, this is the gap to target.

**Caveats.** Excludes subcontracts and cofinancing. Joint-venture values are split equally among members by the publisher.
There is no field for international vs. national competition, number of bids or estimated cost, so competition
intensity and price efficiency cannot be measured. 837 probable duplicate entries were removed and
330 extreme-value records were flagged but kept (see `docs/data_profile.md`, `dq_results`). Supplier country is the
country of registration, not where the work is done.
