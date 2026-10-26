"""Apply the professor's return simulation and weight rules to every asset set."""

import json

import numpy as np
import pandas as pd

from . import config as c


def portfolio_stats(weights, mean, covariance):
    returns = weights @ mean
    variance = np.einsum("ij,jk,ik->i", weights, covariance, weights)
    if variance.min() < -1e-10:
        raise ValueError("Negative portfolio variance.")
    return returns, np.sqrt(np.maximum(variance, 0))


def check_weights(weights, strategy):
    if not np.allclose(weights.sum(axis=1), 1, atol=1e-10):
        raise ValueError("Portfolio weights do not sum to one.")
    if strategy == "Long only" and weights.min() < -1e-12:
        raise ValueError("A long-only portfolio contains a short position.")
    first = weights[:, :-1]
    if first.min() < -1 - 1e-12 or first.max() > 1 + 1e-12:
        raise ValueError("An initial weight is outside the professor's uniform bounds.")
    if not np.allclose(weights[:, -1], 1 - first.sum(axis=1), atol=1e-10):
        raise ValueError("The last weight does not equal the residual budget.")


def allocation_weights(n_assets, n_portfolios, shorts):
    rng = np.random.default_rng(c.WEIGHT_SEED)
    if shorts:
        first = rng.uniform(-1, 1, size=(n_portfolios, n_assets - 1))
        return np.column_stack([first, 1 - first.sum(axis=1)])
    initial = rng.uniform(0, 1, size=(n_portfolios, n_assets))
    return initial / initial.sum(axis=1, keepdims=True)


def result_frame(weights, names, mean, covariance, sample_mean, sample_covariance):
    result = pd.DataFrame(weights, columns=names)
    result["mean_return"], result["volatility"] = portfolio_stats(weights, mean, covariance)
    result["sim_mean_return"], result["sim_volatility"] = portfolio_stats(
        weights, sample_mean, sample_covariance)
    result["gross_exposure"] = np.abs(weights).sum(axis=1)
    result["has_short"] = (weights < -1e-12).any(axis=1)
    result["random_id"] = np.arange(1, len(weights) + 1)
    return result


def select_portfolios(frame, names, mean, covariance):
    selected = []
    for strategy, group in frame.groupby("strategy", sort=False):
        if strategy == "Long/short":
            group = frame  # Permission to short includes the long-only portfolios.
        for label, index in [("Lowest sampled risk", group.volatility.idxmin()),
                             ("Highest sampled return", group.mean_return.idxmax())]:
            row = frame.loc[index].copy()
            row["strategy"] = strategy
            row["selection"] = label
            selected.append(row)
    weights = np.ones((1, len(names))) / len(names)
    row = result_frame(weights, names, mean, covariance, mean, covariance).iloc[0]
    row["strategy"] = "Equal weight"
    row["selection"] = "Equal weight"
    row["random_id"] = 0
    selected.append(row)
    return pd.DataFrame(selected)


def strategy_comparison(selected):
    rows = []
    for case, group in selected.groupby("case", sort=False):
        best = group.loc[group.selection == "Highest sampled return"].set_index("strategy")
        long, shorts = best.loc["Long only"], best.loc["Long/short"]
        rows.append({"case": case, "currency": "Model" if case == "teacher" else c.currency(case),
                     "long_only_mean": long.mean_return, "shorts_mean": shorts.mean_return,
                     "mean_delta": shorts.mean_return - long.mean_return,
                     "long_only_volatility": long.volatility, "shorts_volatility": shorts.volatility,
                     "volatility_delta": shorts.volatility - long.volatility})
    pd.DataFrame(rows).to_csv(c.OUTPUT / "strategy_comparison.csv", index=False)


def window_comparison(cases):
    # Fixed historical equal weights isolate the change in estimation dates.
    assets = pd.read_csv(c.OUTPUT / "asset_statistics.csv")
    equal = []
    for case, returns in cases.items():
        values = returns.mean(axis=1)
        equal.append({"case": case, "etf": "Equal weight",
                      "mean_return": values.mean() * c.WEEKS,
                      "volatility": values.std() * np.sqrt(c.WEEKS)})
    combined = pd.concat([assets, pd.DataFrame(equal)], ignore_index=True)
    rows = []
    for long_case, recent_case in [c.USD_CASES, c.BRL_CASES]:
        long = combined.loc[combined.case == long_case].set_index("etf")
        recent = combined.loc[combined.case == recent_case].set_index("etf")
        for name in long.index:
            row = {"currency": c.currency(long_case), "etf": name}
            for metric in ["mean_return", "volatility"]:
                row[metric + "_long"] = long.loc[name, metric]
                row[metric + "_recent"] = recent.loc[name, metric]
                row[metric + "_delta"] = recent.loc[name, metric] - long.loc[name, metric]
            rows.append(row)
    pd.DataFrame(rows).to_csv(c.OUTPUT / "window_comparison.csv", index=False)


def run(cases):
    c.make_folders()
    diagnostics, selected_rows, convergence, counts = [], [], [], []
    settings = {"n_teacher_returns": c.N_RETURNS, "n_etf_returns": c.N_ETF_RETURNS,
                "n_etf_portfolios_per_strategy": c.N_PORTFOLIOS,
                "saved_plot_portfolios_per_strategy": c.N_PLOT_PORTFOLIOS,
                "return_seed": c.RETURN_SEED, "weight_seed": c.WEIGHT_SEED,
                "weight_rule": "normalized uniform; initial uniform shorts and residual last asset",
                "portfolio_moments": "simulated annual return sample", "annualization": c.WEEKS,
                "teacher_mean": c.TEACHER_MEAN, "teacher_sd": c.TEACHER_SD,
                "teacher_correlation": c.TEACHER_CORR}
    (c.OUTPUT / "settings.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")
    inputs = {"teacher": None, **cases}
    for case, returns in inputs.items():
        print(f"  Allocations: {case}", flush=True)
        if case == "teacher":
            names = list("ABCD")
            mean = np.array(c.TEACHER_MEAN)
            sd = np.array(c.TEACHER_SD)
            covariance = np.diag(sd) @ np.array(c.TEACHER_CORR) @ np.diag(sd)
        else:
            names = list(returns.columns)
            mean = returns.mean().to_numpy() * c.WEEKS
            covariance = returns.cov().to_numpy() * c.WEEKS
        if np.linalg.eigvalsh(covariance).min() < -1e-10:
            raise ValueError(f"Invalid covariance matrix: {case}.")
        rng = np.random.default_rng(c.RETURN_SEED)
        n_returns = c.N_RETURNS if case == "teacher" else c.N_ETF_RETURNS
        draws = rng.multivariate_normal(mean, covariance, size=n_returns, check_valid="raise")
        pd.DataFrame(draws, columns=names).to_csv(c.DATA / f"simulated_returns_{case}.csv", index=False)
        sample_mean, sample_cov = draws.mean(axis=0), np.cov(draws, rowvar=False)
        pd.DataFrame(sample_cov, index=names, columns=names).to_csv(
            c.OUTPUT / f"simulated_covariance_{case}.csv", index_label="etf")
        pd.DataFrame(np.corrcoef(draws, rowvar=False), index=names, columns=names).to_csv(
            c.OUTPUT / f"simulated_correlation_{case}.csv", index_label="etf")
        frames = []
        for strategy, shorts in [("Long only", False), ("Long/short", True)]:
            weights = allocation_weights(len(names), c.N_RETURNS if case == "teacher" else c.N_PORTFOLIOS, shorts)
            check_weights(weights, strategy)
            # All cases follow the professor: use moments of the simulated returns.
            used_mean, used_cov = sample_mean, sample_cov
            frame = result_frame(weights, names, used_mean, used_cov, sample_mean, sample_cov)
            frame["strategy"] = strategy
            frames.append(frame)
            counts.append({"case": case, "currency": "Model" if case == "teacher" else c.currency(case),
                           "strategy": strategy, "generated": len(frame),
                           "saved_for_plot": min(len(frame), c.N_PLOT_PORTFOLIOS),
                           "minimum_risk": frame.volatility.min(), "maximum_risk": frame.volatility.max(),
                           "minimum_return": frame.mean_return.min(), "maximum_return": frame.mean_return.max(),
                           "max_weight_sum_error": float(np.abs(weights.sum(axis=1) - 1).max()),
                           "maximum_gross": float(np.abs(weights).sum(axis=1).max())})
            for n in ([700] if case == "teacher" else [700, 5_000, 10_000, 50_000, 100_000, c.N_PORTFOLIOS]):
                subset = frame.iloc[:n]
                convergence.append({"case": case, "strategy": strategy, "n_portfolios": n,
                                    "minimum_risk": subset.volatility.min(),
                                    "maximum_return": subset.mean_return.max(),
                                    "volatility_at_maximum_return":
                                    subset.loc[subset.mean_return.idxmax(), "volatility"]})
        frame = pd.concat(frames, ignore_index=True)
        # The report needs a cloud sample, not millions of redundant CSV rows.
        plot_rows = pd.concat([group.iloc[np.linspace(0, len(group) - 1,
                               min(len(group), c.N_PLOT_PORTFOLIOS), dtype=int)]
                               for _, group in frame.groupby("strategy", sort=False)])
        plot_rows.to_csv(c.OUTPUT / f"portfolios_{case}.csv", index=False)
        chosen = select_portfolios(frame, names, used_mean, used_cov)
        chosen["case"] = case
        selected_rows.append(chosen)
        for i, name in enumerate(names):
            diagnostics.append({"case": case, "etf": name, "input_mean": mean[i],
                                "simulated_mean": sample_mean[i],
                                "input_volatility": np.sqrt(covariance[i, i]),
                                "simulated_volatility": np.sqrt(sample_cov[i, i])})
    selected = pd.concat(selected_rows, ignore_index=True)
    selected.to_csv(c.OUTPUT / "selected_portfolios.csv", index=False)
    strategy_comparison(selected)
    window_comparison(cases)
    pd.DataFrame(diagnostics).to_csv(c.OUTPUT / "simulation_check.csv", index=False)
    pd.DataFrame(convergence).to_csv(c.OUTPUT / "convergence.csv", index=False)
    pd.DataFrame(counts).to_csv(c.OUTPUT / "allocation_summary.csv", index=False)
