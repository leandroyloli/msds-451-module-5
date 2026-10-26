"""Inputs used by the study. Change these before starting a new run."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = ROOT / "output"
FIGURES = ROOT / "figures"
REPORT = ROOT / "report"

START = "2000-01-01"
END = "2026-10-24"  # Exclusive: the last possible session is 23 October.
WEEKS = 52
N_RETURNS = 700
N_ETF_RETURNS = 10_000
N_PORTFOLIOS = 500_000
N_PLOT_PORTFOLIOS = 20_000
RECENT_WEEKS = 156
# Shared percentage scales for every return and volatility chart.
CHART_VOLATILITY_RANGE = (0.0, 0.80)
CHART_MEAN_RANGE = (-0.20, 0.60)
RETURN_SEED = 1111
WEIGHT_SEED = 9999

# Display name, Yahoo symbol, market, investment rule, quote currency.
ETFS = [
    ("VOO", "VOO", "United States", "Market", "USD"),
    ("VYM", "VYM", "United States", "Dividend", "USD"),
    ("QUAL", "QUAL", "United States", "Quality", "USD"),
    ("VWRA", "VWRA.L", "World", "Market", "USD"),
    ("VHYL", "VHYL.L", "World", "Dividend", "GBP"),
    ("IWQU", "IWQU.L", "World", "Quality", "USD"),
    ("BOVA11", "BOVA11.SA", "Brazil", "Market", "BRL"),
    ("DIVO11", "DIVO11.SA", "Brazil", "Dividend", "BRL"),
]

TEACHER_MEAN = [0.02, 0.07, 0.15, 0.20]
TEACHER_SD = [0.05, 0.12, 0.17, 0.25]
TEACHER_CORR = [
    [1.0, 0.3, 0.3, 0.3],
    [0.3, 1.0, 0.6, 0.6],
    [0.3, 0.6, 1.0, 0.6],
    [0.3, 0.6, 0.6, 1.0],
]

CASE_LABELS = {
    "usd_long": "USD block / six ETFs / long window",
    "usd_recent": "USD block / six ETFs / recent window",
    "brl_long": "BRL block / two ETFs / long window",
    "brl_recent": "BRL block / two ETFs / recent window",
}
USD_ASSETS = [row[0] for row in ETFS if row[2] != "Brazil"]
BRL_ASSETS = [row[0] for row in ETFS if row[2] == "Brazil"]
MAIN_CASES = ["usd_long", "brl_long"]
USD_CASES = ["usd_long", "usd_recent"]
BRL_CASES = ["brl_long", "brl_recent"]
BLOCK_CASES = USD_CASES + BRL_CASES


def currency(case):
    return "BRL" if case in BRL_CASES else "USD"


def make_folders():
    for folder in (DATA, OUTPUT, FIGURES, REPORT):
        folder.mkdir(parents=True, exist_ok=True)
