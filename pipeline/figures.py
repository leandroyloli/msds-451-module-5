"""Draw the report figures with one shared academic style."""

import json
import os

from . import config as c

os.environ.setdefault("MPLCONFIGDIR", str(c.ROOT / ".matplotlib"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.dates import DateFormatter, YearLocator
from matplotlib.ticker import PercentFormatter
import pandas as pd

PAPER = "#f3f6f4"
INK, MUTED, LINE = "#1c2420", "#5c6b63", "#d5ded8"
BLUE, GREEN, RED, GOLD = "#24558a", "#1f6b56", "#8e3a32", "#a8843a"
# Same fund colors used in the earlier discussions.
ETF_COLORS = {"VOO": "#0e2744", "VYM": "#3d6ea8", "QUAL": "#7fa4d4",
              "VWRA": "#0a3d32", "VHYL": "#1f8a72", "IWQU": "#7dbeab",
              "BOVA11": "#5c3a0c", "DIVO11": "#b8862a"}


def style():
    plt.rcParams.update({"font.family": ["Segoe UI", "DejaVu Sans"], "font.size": 11,
                         "font.serif": ["Palatino Linotype", "DejaVu Serif"],
                         "figure.facecolor": PAPER, "axes.facecolor": PAPER,
                         "text.color": INK, "axes.labelcolor": INK,
                         "axes.edgecolor": LINE, "xtick.color": MUTED, "ytick.color": MUTED,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.titleweight": "normal", "axes.titlesize": 12,
                         "axes.labelpad": 10, "xtick.major.size": 0, "ytick.major.size": 0,
                         "xtick.major.pad": 8, "ytick.major.pad": 8,
                         "legend.frameon": False, "savefig.facecolor": PAPER,
                         "axes.unicode_minus": False})


def header(fig, title, subtitle="", left=.085):
    fig.text(left, .965, title, fontfamily="serif", fontsize=21, va="top")
    if subtitle:
        fig.text(left, .903, subtitle, fontsize=10.5, color=MUTED, va="top")


def finish(fig, name, note):
    fig.text(.085, .025, note, fontsize=9, color=MUTED, va="bottom", linespacing=1.6)
    fig.savefig(c.FIGURES / f"{name}.png", dpi=180)
    plt.close(fig)


def percent_axes(ax):
    ax.set_xlim(*c.CHART_VOLATILITY_RANGE)
    ax.set_ylim(*c.CHART_MEAN_RANGE)
    ax.set_xticks([i / 10 for i in range(0, 9, 2)])
    ax.set_yticks([i / 10 for i in range(-2, 7, 2)])
    ax.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.grid(color=LINE, alpha=.7, linewidth=.6)
    ax.axhline(0, color=LINE, lw=1)
    ax.set_axisbelow(True)


def teacher_plot():
    frame = pd.read_csv(c.OUTPUT / "portfolios_teacher.csv")
    fig, axes = plt.subplots(1, 2, figsize=(12.4, 6.2), sharex=True, sharey=True)
    fig.subplots_adjust(left=.085, right=.98, bottom=.22, top=.75, wspace=.12)
    for ax, strategy in zip(axes, ["Long only", "Long/short"]):
        part = frame.loc[frame.strategy == strategy]
        for short, color in [(False, BLUE), (True, RED)]:
            subset = part.loc[part.has_short == short]
            ax.scatter(subset.volatility, subset.mean_return, s=13, color=color, alpha=.6, linewidths=0)
        ax.set_title("Long only" if strategy == "Long only" else
                     "Shorts allowed", loc="left", pad=14)
        ax.set_xlabel("Annualized volatility")
        percent_axes(ax)
    axes[0].set_ylabel("Annualized mean")
    header(fig, "Validation with the four supplied assets",
           "Same rules and scales used for the ETFs")
    finish(fig, "01-teacher", "700 annual observations and 700 allocations per strategy. Blue: no short. Terracotta: has shorts.")


def weekly_series(cases):
    samples = json.loads((c.OUTPUT / "samples.json").read_text())
    levels = {}
    for case in c.MAIN_CASES:
        # Prepend the starting price so that all series begin at exactly 100.
        returns = cases[case]
        start = pd.Timestamp(samples[case]["price_start"])
        initial = pd.DataFrame(1.0, index=pd.DatetimeIndex([start]), columns=returns.columns)
        levels[case] = pd.concat([initial, (1 + returns).cumprod()]) * 100
    ymax = max(frame.max().max() for frame in levels.values())
    top = (int(ymax / 50) + 1) * 50
    for case, frame in levels.items():
        fig, ax = plt.subplots(figsize=(12.4, 6.4))
        fig.subplots_adjust(left=.085, right=.98, bottom=.20, top=.76)
        start = pd.Timestamp(samples[case]["price_start"])
        recent = pd.Timestamp(samples[case.replace("long", "recent")]["price_start"])
        end = frame.index[-1]
        ax.axvspan(recent, end, color=GREEN, alpha=.08, linewidth=0, zorder=0)
        ax.axvline(recent, color=GREEN, alpha=.5, lw=.8, ls=(0, (3, 3)))
        for name in frame:
            dashed = (0, (4, 2)) if name in ["QUAL", "IWQU"] else "-"
            ax.plot(frame.index, frame[name], color=ETF_COLORS[name], lw=1.8,
                    ls=dashed, label=name, zorder=3)
        ax.set_xlim(start, end)
        ax.set_ylim(50, top)
        ax.xaxis.set_major_locator(YearLocator())
        ax.xaxis.set_major_formatter(DateFormatter("%Y"))
        ax.yaxis.grid(True, color=LINE, lw=.6)
        ax.axhline(100, color=LINE, lw=1)
        ax.set_axisbelow(True)
        ax.set_ylabel("Adjusted price index")
        ax.legend(loc="lower left", bbox_to_anchor=(0, 1.035), ncol=len(frame.columns),
                  fontsize=10, handlelength=2.3, columnspacing=1.6, borderaxespad=0)
        ax.text(recent + (end - recent) / 2, top - 12,
                "Recent window", ha="center", va="top", fontsize=10, color=GREEN)
        header(fig, f"Weekly ETF paths in {c.currency(case)}",
               "Rebased to 100 on 26 Jul 2019. Same vertical scale for both budgets.")
        finish(fig, f"00-weekly-{c.currency(case).lower()}", "Weekly adjusted prices. Shading: 27 Oct 2023 to 23 Oct 2026, the window for the last 156 returns.\n"
            "Colors follow the earlier modules. Dashed lines: quality funds. Observed history, not a simulation.")


def opportunity_plot(keys):
    selected = pd.read_csv(c.OUTPUT / "selected_portfolios.csv")
    for case in keys:
        frame = pd.read_csv(c.OUTPUT / f"portfolios_{case}.csv")
        for strategy, suffix in [("Long only", "long-only"), ("Long/short", "shorts")]:
            fig, ax = plt.subplots(figsize=(12.4, 6.5))
            fig.subplots_adjust(left=.085, right=.98, bottom=.22, top=.77)
            part = frame.loc[frame.strategy == strategy]
            for short, color, label in [
                (False, BLUE, "No short position"),
                (True, RED, "Has short positions"),
            ]:
                subset = part.loc[part.has_short == short]
                if len(subset):
                    ax.scatter(subset.volatility, subset.mean_return, s=5, color=color,
                               alpha=.25, linewidths=0, rasterized=True, label=label)
            group = selected.loc[selected.case == case]
            equal = group.loc[group.strategy == "Equal weight"].iloc[0]
            best = group.loc[(group.strategy == strategy) &
                             (group.selection == "Highest sampled return")].iloc[0]
            ax.scatter(equal.volatility, equal.mean_return, s=100, marker="*", color=GOLD,
                       edgecolor=INK, linewidth=.6, zorder=5, label="Equal weight")
            ax.scatter(best.volatility, best.mean_return, s=65, marker="D",
                       facecolors="none", edgecolors=INK, linewidth=1.2, zorder=6,
                       label="Highest mean found")
            percent_axes(ax)
            ax.set_xlabel("Annualized volatility")
            ax.set_ylabel("Annualized mean")
            label = "long only" if strategy == "Long only" else "shorts allowed"
            header(fig, f"{c.currency(case)}: {label}", "Long window, 378 weekly returns. Shared limits across all risk and return plots.")
            legend = ax.legend(fontsize=10, loc="lower left", bbox_to_anchor=(0, 1.035),
                               ncol=4, borderaxespad=0, columnspacing=1.5)
            for handle in legend.legend_handles:
                handle.set_alpha(1)
                if handle.get_sizes()[0] < 10:
                    handle.set_sizes([24])
            finish(fig, f"02-{c.currency(case).lower()}-{suffix}", "Search: 500,000 allocations per strategy. Cloud: 20,000 points.\n"
                "The diamond marks the full-search selection; a higher mean may require more risk.")


def correlation_plot(cases):
    cmap = LinearSegmentedColormap.from_list("correlation", [RED, PAPER, GREEN])
    fig, axes = plt.subplots(1, 2, figsize=(12.4, 6.6))
    fig.subplots_adjust(left=.085, right=.9, bottom=.23, top=.77, wspace=.4)
    for ax, case in zip(axes, c.MAIN_CASES):
        corr = cases[case].corr()
        im = ax.imshow(corr, vmin=-1, vmax=1, cmap=cmap)
        ax.set_xticks(range(len(corr)), corr.columns, rotation=45, ha="right", fontsize=10)
        ax.set_yticks(range(len(corr)), corr.columns, fontsize=10)
        ax.set_title(c.currency(case), loc="left", pad=15, fontfamily="serif", fontsize=15)
        for i in range(len(corr)):
            for j in range(len(corr)):
                value = f"{corr.iloc[i, j]:.2f}"
                ax.text(j, i, value,
                        ha="center", va="center", fontsize=10,
                        color="white" if abs(corr.iloc[i, j]) > .65 else INK)
        for spine in ax.spines.values():
            spine.set_visible(False)
    bar_ax = fig.add_axes((.94, .25, .012, .49))
    fig.colorbar(im, cax=bar_ax, ticks=[-1, -.5, 0, .5, 1])
    header(fig, "How the ETFs move together",
           "Pearson correlations of weekly returns, long window")
    finish(fig, "03-correlations", "Each matrix uses its own budget currency. Correlation ranges from -1 to 1.")


def window_plot():
    comparison = pd.read_csv(c.OUTPUT / "window_comparison.csv")
    names = c.USD_ASSETS + ["Equal weight"] + c.BRL_ASSETS + ["Equal weight"]
    rows = []
    for case in c.MAIN_CASES:
        group = comparison.loc[comparison.currency == c.currency(case)].set_index("etf")
        rows.extend([group.loc[name] for name in (c.USD_ASSETS if case == "usd_long" else c.BRL_ASSETS) + ["Equal weight"]])
    positions = [0, 1, 2, 3, 4, 5, 6, 8.5, 9.5, 10.5]
    labels = ["USD portfolio" if i == 6 else
              "BRL portfolio" if i == 9 else name
              for i, name in enumerate(names)]
    fig, axes = plt.subplots(1, 2, figsize=(12.4, 7.6), sharey=True)
    fig.subplots_adjust(left=.14, right=.98, bottom=.17, top=.76, wspace=.12)
    for ax, metric, title in zip(axes, ["mean_return", "volatility"],
                                 ["Annualized mean",
                                  "Annualized volatility"]):
        for i, (row, y) in enumerate(zip(rows, positions)):
            long, recent = row[metric + "_long"], row[metric + "_recent"]
            ax.plot([long, recent], [y, y], color=LINE, lw=2, zorder=1)
            ax.scatter(long, y, color=BLUE, s=42, zorder=3,
                       label="Long window" if i == 0 else None)
            ax.scatter(recent, y, color=GOLD, marker="s", s=36, zorder=3,
                       label="Recent window" if i == 0 else None)
        ax.set_yticks(positions, labels)
        ax.set_ylim(11.3, -.8)
        ax.set_title(title, loc="left", pad=15, fontfamily="serif", fontsize=15)
        limits = c.CHART_MEAN_RANGE if metric == "mean_return" else c.CHART_VOLATILITY_RANGE
        ax.set_xlim(*limits)
        ax.set_xticks([limits[0] + .2 * i for i in range(5)])
        ax.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
        ax.grid(axis="x", color=LINE, lw=.6)
        ax.set_axisbelow(True)
        ax.axhline(7.3, color=LINE, lw=.8)
        for y in [6, 10.5]:
            ax.axhspan(y - .4, y + .4, color=GREEN, alpha=.04, zorder=0, linewidth=0)
    handles, legend_labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, legend_labels, loc="upper left", bbox_to_anchor=(.135, .865),
               ncol=2, fontsize=10, columnspacing=2, borderaxespad=0)
    header(fig, "What changes with the historical window",
           "Same ETFs and weights. USD above; BRL below. Lines connect the two estimates.", left=.14)
    finish(fig, "08-fixed-portfolio-comparison", "Long: 26 Jul 2019 to 23 Oct 2026. Recent: 27 Oct 2023 to 23 Oct 2026.\n"
        "Equal weight portfolios: 1/6 per ETF in USD and 1/2 per ETF in BRL.")


def run(cases):
    style()
    weekly_series(cases)
    teacher_plot()
    opportunity_plot(c.MAIN_CASES)
    correlation_plot(cases)
    window_plot()
