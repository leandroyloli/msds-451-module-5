# MSDS 451: Programming Assignment 2

Portfolio allocation with Monte Carlo. The study answers two questions:

1. What changes in return and risk when short sales are allowed?
2. How do asset and portfolio estimates change with the historical window?

Student: Leandro Loli. Northwestern University, MSDS 451, Section 001, Fall 2026.

Clone URL: https://github.com/leandroyloli/msds-451-module-5.git

## Read

- [PDF research report](report/msds451-pa2.pdf): submission version.
- [HTML research report](report/msds451-pa2.html): browser version of the same report.

The main analysis covers eight ETFs in separate USD and BRL budgets. Appendix A reproduces the supplied four-asset example, as required by the assignment.

## Folder structure

| Path | Purpose |
| --- | --- |
| `run.py` | Run the study, rebuild reports or check saved results |
| `pipeline/config.py` | ETFs, periods, simulation counts and seeds |
| `pipeline/data.py` | Read saved prices and prepare aligned weekly returns |
| `pipeline/simulation.py` | Simulate returns, generate weights and compare strategies and windows |
| `pipeline/figures.py` | Draw weekly paths, allocation clouds and comparisons in English |
| `pipeline/report.py` | Fill report tables and render HTML with typeset equations |
| `data/` | Original downloads, source hashes and derived input samples |
| `output/` | Selected weights, comparison tables and verification results |
| `figures/` | Nine English figures referenced by the report source |
| `report/` | Editable Markdown source and the generated HTML and PDF reports |

The five folders follow the structure used in Module 3. The report filename follows the same assignment pattern: msds451-pa1.html there and msds451-pa2.html here. Python files have descriptive names, with run.py as the entry point.

There are no notebooks. The environment and Python caches are excluded by `.gitignore`.

## Run

Tested with Python 3.13.15. Create an environment and install the pinned requirements:

```bash
python -m venv .venv
```

Windows:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe run.py
```

macOS or Linux:

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run.py
```

The default run is offline. It uses saved prices through 23 October 2026 and needs no token or API key.

- `python run.py --check`: verify saved results without rerunning the analysis.
- `python run.py --report-only`: rebuild HTML after editing report text.
- `python run.py --report-only --pdf`: rebuild HTML and PDF using Edge or Chrome. No new data download or simulation is needed.
- `python run.py --download`: deliberately refresh prices and FX, then rerun. Vendor revisions may change results.

## Analysis choices

The USD budget contains VOO, VYM, QUAL, VWRA.L, VHYL.L and IWQU.L. VHYL's GBP quotation is converted to USD. The BRL budget contains BOVA11.SA and DIVO11.SA in their original currency. Each budget sums to 100% independently. The six-ETF USD case meets the requirement of at least four chosen assets; BRL is an additional application.

Both budgets use 378 weekly returns, with price endpoints from 26 July 2019 to 23 October 2026. The recent sample is the last 156 returns, with price endpoints from 27 October 2023 to 23 October 2026. The windows overlap. Missing observations are not filled. The weekly charts start at 100 on the common starting date and shade the recent sample. Colors follow the earlier discussion modules.

All cases use the supplied allocation rule. Long only weights are uniform draws from 0 to 1, divided by their sum. With shorts, the first n - 1 weights are uniform from -1 to 1; the last equals one minus their sum. There is no added exposure or volatility ceiling. The last asset is D in the supplied example, IWQU in USD and DIVO11 in BRL. This asymmetry follows the original construction.

The supplied example uses 700 joint annual normal return observations and 700 portfolios per strategy. Each ETF sample uses 10,000 annual normal observations fitted to historical weekly means and covariances, then 500,000 portfolios per strategy. Four ETF samples give four million allocations. Python and R do not generate identical observations from the same integer seed.

Strategy summaries show the highest simulated mean found and its corresponding volatility. Allowing shorts includes long only candidates. These summaries use the simulated annual return sample. Window comparisons separately use historical weekly estimates and fixed equal weights: one-sixth per USD ETF and one-half per BRL ETF. The same candidate weights are reused across windows.

Annual means and covariances use a factor of 52. Arithmetic means are not CAGR or forecasts. The study is in sample and excludes trading, financing, borrowing costs and investor taxes.

## Outputs and verification

The main outputs are:

- `strategy_comparison.csv`: highest-mean strategy selections, associated volatilities and deltas.
- `window_comparison.csv`: every ETF and equal weight portfolio in both windows.
- `selected_portfolios.csv`: selected weights and exposures.
- `verification.json` and `run_summary.txt`: saved checks and numerical summary.

Additional CSV files retain simulated observations, cloud samples, covariance matrices and search diagnostics used to reproduce or verify the calculations. The original download is preserved with its hashes; only the eight ETFs in the configuration enter the analysis.

Checks reconstruct weekly returns from prices, verify source hashes, dates, currency separation and allocation rules, and independently recalculate portfolio statistics and deltas. They also check the generated reports.

Mean and volatility charts share ranges of -20% to 60% and 0% to 80%, respectively. Weekly price charts share their own base-100 scale; correlations range from -1 to 1. Figures use Palatino titles, readable labels and the earlier market colors. The HTML follows the academic style of Programming Assignment 1. Equations use LaTeX notation rendered as SVG.
