"""Run the study from saved data. Use --download only to refresh the inputs."""

import argparse
import hashlib
import json

import numpy as np
import pandas as pd

from pipeline import config as c, data, figures, report, simulation


def check_results():
    checks = []
    manifest = json.loads((c.DATA / "sources.json").read_text())
    for name, expected in manifest["files_sha256"].items():
        assert hashlib.sha256((c.DATA / name).read_bytes()).hexdigest() == expected, name
    checks.append("Daily price and FX files match their download hashes")

    raw = pd.read_csv(c.DATA / "prices.csv", parse_dates=["date"])
    fx_raw = pd.read_csv(c.DATA / "fx.csv", parse_dates=["date"])
    fx = fx_raw.pivot(index="date", columns="etf", values="adjusted_close").resample("W-FRI").last()
    weekly = pd.read_csv(c.DATA / "weekly_prices_usd.csv", index_col="date", parse_dates=True)
    weekly_brl = pd.read_csv(c.DATA / "weekly_prices_brl.csv", index_col="date", parse_dates=True)
    assert len(c.ETFS) == 8
    assert {row[0] for row in c.ETFS}.issubset(set(raw.etf))
    assert set(weekly.columns) == {row[0] for row in c.ETFS}
    assert raw.date.max() < pd.Timestamp(c.END)
    for name, symbol, market, rule, currency in c.ETFS:
        local = raw.loc[raw.etf == name].set_index("date").adjusted_close.resample("W-FRI").last()
        expected = local / fx.USDBRL if currency == "BRL" else local * fx.GBPUSD if currency == "GBP" else local
        dates = weekly[name].dropna().index
        np.testing.assert_allclose(weekly.loc[dates, name], expected.loc[dates], rtol=1e-12)
        if name in c.BRL_ASSETS:
            np.testing.assert_allclose(weekly_brl.loc[dates, name], local.loc[dates], rtol=1e-12)
    checks.append("Each weekly ETF price uses the correct USD conversion")
    checks.append("The BRL block retains its original BRL prices")
    fx_daily = fx_raw.pivot(index="date", columns="etf", values="adjusted_close")
    changed_fx = fx_daily.copy()
    changed_fx["USDBRL"] *= np.linspace(1, 1.4, len(changed_fx))
    changed_brl = data.weekly_prices(raw, changed_fx, target="BRL")
    pd.testing.assert_frame_equal(changed_brl[c.BRL_ASSETS], weekly_brl[c.BRL_ASSETS],
                                  check_freq=False, atol=1e-12)
    checks.append("Changing BRL/USD leaves Brazilian-block returns unchanged")

    cases = {case: pd.read_csv(c.DATA / f"returns_{case}.csv", index_col="date", parse_dates=True)
             for case in c.CASE_LABELS}
    pd.testing.assert_index_equal(cases["usd_long"].index, cases["brl_long"].index)
    for long_case, recent_case in [c.USD_CASES, c.BRL_CASES]:
        pd.testing.assert_frame_equal(cases[long_case].iloc[-c.RECENT_WEEKS:], cases[recent_case])
    checks.append("Exactly eight ETFs; both budgets share the same long and recent dates")
    for case, returns in cases.items():
        panel = weekly_brl if c.currency(case) == "BRL" else weekly
        expected = panel[returns.columns].pct_change(fill_method=None).loc[returns.index]
        np.testing.assert_allclose(returns, expected, atol=1e-14)
        assert returns.index.is_unique and returns.index.is_monotonic_increasing
        assert np.isfinite(returns).all().all()
        assert np.linalg.eigvalsh(returns.cov()).min() >= -1e-12
    checks.append("Sample dates, weekly returns and covariance matrices are valid")

    counts = pd.read_csv(c.OUTPUT / "allocation_summary.csv")
    for case in ["teacher", *cases]:
        frame = pd.read_csv(c.OUTPUT / f"portfolios_{case}.csv")
        names = list("ABCD") if case == "teacher" else list(cases[case].columns)
        draws = pd.read_csv(c.DATA / f"simulated_returns_{case}.csv").to_numpy()
        assert len(draws) == (c.N_RETURNS if case == "teacher" else c.N_ETF_RETURNS)
        for strategy, group in frame.groupby("strategy"):
            weights = group[names].to_numpy()
            assert len(group) == (700 if case == "teacher" else c.N_PLOT_PORTFOLIOS)
            record = counts.loc[(counts.case == case) & (counts.strategy == strategy)].iloc[0]
            assert record.generated == (700 if case == "teacher" else c.N_PORTFOLIOS)
            assert record.saved_for_plot == len(group)
            assert record.max_weight_sum_error < 1e-10
            simulation.check_weights(weights, strategy)
            # Direct portfolio return series provide an independent check of the covariance formula.
            sample = group.iloc[np.linspace(0, len(group) - 1, 25, dtype=int)]
            portfolio = draws @ sample[names].to_numpy().T
            np.testing.assert_allclose(portfolio.mean(axis=0), sample.sim_mean_return, atol=1e-12)
            np.testing.assert_allclose(portfolio.std(axis=0, ddof=1), sample.sim_volatility, atol=1e-12)
            np.testing.assert_allclose(portfolio.mean(axis=0), sample.mean_return, atol=1e-12)
            np.testing.assert_allclose(portfolio.std(axis=0, ddof=1), sample.volatility, atol=1e-12)
    checks.append("All allocation counts and exposures pass; direct return series match portfolio formulas")
    for first, second in [c.USD_CASES, c.BRL_CASES]:
        left = pd.read_csv(c.OUTPUT / f"portfolios_{first}.csv")
        right = pd.read_csv(c.OUTPUT / f"portfolios_{second}.csv")
        np.testing.assert_array_equal(left[cases[first].columns], right[cases[second].columns])
    checks.append("Unchanged asset lists reuse identical allocation samples across windows")
    selected = pd.read_csv(c.OUTPUT / "selected_portfolios.csv")
    for case in c.BLOCK_CASES:
        group = selected.loc[selected.case == case]
        allowed = c.USD_ASSETS if case in c.USD_CASES else c.BRL_ASSETS
        excluded = [name for name in c.USD_ASSETS + c.BRL_ASSETS if name not in allowed]
        assert group[excluded].isna().all().all()
        np.testing.assert_allclose(group[cases[case].columns].sum(axis=1), 1, atol=1e-12)
    checks.append("Each currency block has its own net budget and contains no assets from the other block")

    strategy_summary = pd.read_csv(c.OUTPUT / "strategy_comparison.csv")
    assert len(strategy_summary) == len(c.CASE_LABELS) + 1
    assert (strategy_summary.shorts_mean >= strategy_summary.long_only_mean - 1e-12).all()
    for case, group in selected.groupby("case"):
        names = list("ABCD") if case == "teacher" else list(cases[case].columns)
        simulation.check_weights(group[names].to_numpy(), "Long/short")
        observed = pd.read_csv(c.DATA / f"simulated_returns_{case}.csv").to_numpy()
        values = observed @ group[names].to_numpy().T
        np.testing.assert_allclose(values.mean(axis=0), group.mean_return, atol=1e-12)
        np.testing.assert_allclose(values.std(axis=0, ddof=1), group.volatility, atol=1e-12)
        best = group.loc[group.selection == "Highest sampled return"].set_index("strategy")
        row = strategy_summary.loc[strategy_summary.case == case].iloc[0]
        for label, strategy in [("long_only", "Long only"), ("shorts", "Long/short")]:
            np.testing.assert_allclose(row[label + "_mean"], best.loc[strategy, "mean_return"], atol=1e-12)
            np.testing.assert_allclose(row[label + "_volatility"], best.loc[strategy, "volatility"], atol=1e-12)
        np.testing.assert_allclose(row.mean_delta, row.shorts_mean - row.long_only_mean, atol=1e-12)
        np.testing.assert_allclose(row.volatility_delta, row.shorts_volatility - row.long_only_volatility, atol=1e-12)
    assert (counts.loc[(counts.case != "teacher") & (counts.strategy == "Long/short"), "maximum_gross"] > 2).all()
    checks.append("Original weight rules and simulated-return summaries pass without added exposure or risk ceilings")

    comparison = pd.read_csv(c.OUTPUT / "window_comparison.csv")
    assert len(comparison) == 10
    for long_case, recent_case in [c.USD_CASES, c.BRL_CASES]:
        group = comparison.loc[comparison.currency == c.currency(long_case)]
        for row in group.itertuples():
            stats = {}
            for case, suffix in [(long_case, "long"), (recent_case, "recent")]:
                values = cases[case].mean(axis=1) if row.etf == "Equal weight" else cases[case][row.etf]
                stats["mean_return_" + suffix] = values.mean() * c.WEEKS
                stats["volatility_" + suffix] = values.std() * np.sqrt(c.WEEKS)
            for metric in ["mean_return", "volatility"]:
                stats[metric + "_delta"] = stats[metric + "_recent"] - stats[metric + "_long"]
            for name, expected in stats.items():
                np.testing.assert_allclose(getattr(row, name), expected, atol=1e-12)
    checks.append("Every ETF and equal-weight window statistic and delta matches its weekly returns")

    page = (c.REPORT / "msds451-pa2.html").read_text(encoding="utf-8")
    assert "{{" not in page
    assert page.count('src="data:image/png;base64,') == 9
    assert len(list(c.FIGURES.glob("*.png"))) == 9
    assert "AUVP11" not in page
    assert 'id="question-1"' in page and 'id="question-2"' in page
    assert 'lang="en"' in page
    assert "\u2014" not in page and "\u2013" not in page
    assert page.count('class="image-link"') == 4
    assert page.count('class="equation"') == 5
    assert "$$" not in page and '<script src=' not in page
    assert 'id="appendix-a' in page
    source = (c.REPORT / "report.md").read_text(encoding="utf-8")
    assert source.index("{{strategy_teacher}}") > source.index("## Appendix")
    assert source.index("{{teacher_inputs}}") > source.index("## Appendix")
    assert all(f'Figure 2{letter}' in page for letter in 'abcd')
    report_files = {p.name for p in c.REPORT.iterdir() if p.is_file()}
    assert {"report.md", "msds451-pa2.html"}.issubset(report_files)
    assert report_files <= {"report.md", "msds451-pa2.html", "msds451-pa2.pdf"}
    checks.append("The English report contains weekly paths, four large ETF panels, the required appendix and five equations")
    (c.OUTPUT / "verification.json").write_text(json.dumps({"passed": checks}, indent=2), encoding="utf-8")
    samples = json.loads((c.OUTPUT / "samples.json").read_text())
    lines = ["MSDS 451 - Programming Assignment 2", "Eight ETFs: independent six-ETF USD and two-ETF BRL budgets.",
             "Teacher: 700 annual return draws; 700 portfolios per strategy.",
             f"ETFs: {c.N_PORTFOLIOS:,} random portfolios per strategy and sample.", ""]
    lines += [f"Full searches use {c.N_PORTFOLIOS:,} allocations; clouds save {c.N_PLOT_PORTFOLIOS:,} per strategy.", ""]
    lines += [f"{case}: {s['n_weeks']} weekly returns; {s['price_start']} to {s['last_return']}"
              for case, s in samples.items()]
    lines += ["", "Highest sampled means and their associated volatilities:",
              strategy_summary.to_string(index=False, float_format=lambda x: f"{x:.6f}"), "", "Checks:"]
    lines += [f"PASS: {item}" for item in checks]
    (c.OUTPUT / "run_summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for item in checks:
        print(f"PASS: {item}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Refresh Yahoo prices and FX before running")
    parser.add_argument("--report-only", action="store_true", help="Rebuild HTML from saved results and report.md")
    parser.add_argument("--check", action="store_true", help="Check the saved results without rerunning the analysis")
    parser.add_argument("--pdf", action="store_true", help="Also print the HTML report to PDF with Edge or Chrome")
    args = parser.parse_args()
    c.make_folders()
    if args.check:
        check_results()
        return
    if args.report_only:
        report.run()
        if args.pdf:
            report.build_pdf()
        check_results()
        return
    if args.download:
        data.download()
    if not (c.DATA / "prices.csv").exists():
        parser.error("No saved prices. Run once with --download.")
    print("Preparing separate weekly USD and BRL blocks", flush=True)
    cases = data.prepare()
    print("Running the four-asset example and the ETF allocations", flush=True)
    simulation.run(cases)
    print("Drawing figures and building the HTML report", flush=True)
    figures.run(cases)
    report.run()
    if args.pdf:
        report.build_pdf()
    check_results()
    print(f"Report: {c.REPORT / 'msds451-pa2.html'}")


if __name__ == "__main__":
    main()
