"""Save daily inputs and build dated, separate USD and BRL return samples."""

import hashlib
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

from . import config as c


def download():
    c.make_folders()
    rows, sources = [], []
    symbols = c.ETFS + [("USDBRL", "BRL=X", "FX", "FX", "BRL"),
                        ("GBPUSD", "GBPUSD=X", "FX", "FX", "USD")]
    for name, symbol, market, rule, currency in symbols:
        print(f"Downloading {symbol}", flush=True)
        ticker = yf.Ticker(symbol)
        frame = ticker.history(start=c.START, end=c.END, auto_adjust=False,
                               actions=True, raise_errors=True)
        if frame.empty or "Adj Close" not in frame:
            raise ValueError(f"No adjusted prices returned for {symbol}.")
        metadata = ticker.get_history_metadata()
        reported_currency = metadata.get("currency")
        if reported_currency != currency:
            raise ValueError(f"{symbol}: expected {currency}, got {reported_currency}.")
        frame.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
        frame = frame.loc[~frame.index.duplicated()].sort_index()
        saved = pd.DataFrame({
            "date": frame.index,
            "etf": name,
            "symbol": symbol,
            "currency": currency,
            "close": frame["Close"].to_numpy(),
            "adjusted_close": frame["Adj Close"].to_numpy(),
            "dividends": frame.get("Dividends", pd.Series(0, index=frame.index)).to_numpy(),
            "splits": frame.get("Stock Splits", pd.Series(0, index=frame.index)).to_numpy(),
        }).dropna(subset=["adjusted_close"])
        if (saved["adjusted_close"] <= 0).any():
            raise ValueError(f"Nonpositive prices in {symbol}.")
        rows.append(saved)
        sources.append({"etf": name, "symbol": symbol, "currency": currency,
                        "market": market, "rule": rule,
                        "first_date": str(saved.date.min().date()),
                        "last_date": str(saved.date.max().date()), "rows": len(saved),
                        "url": f"https://finance.yahoo.com/quote/{symbol}/history/"})
    all_prices = pd.concat(rows, ignore_index=True)
    is_fx = all_prices.etf.isin(["USDBRL", "GBPUSD"])
    all_prices.loc[~is_fx].to_csv(c.DATA / "prices.csv", index=False)
    all_prices.loc[is_fx].to_csv(c.DATA / "fx.csv", index=False)
    manifest = {"downloaded_utc": datetime.now(timezone.utc).isoformat(),
                "requested_start": c.START, "requested_end_exclusive": c.END,
                "provider": "Yahoo Finance via yfinance", "series": sources,
                "files_sha256": {name: hashlib.sha256((c.DATA / name).read_bytes()).hexdigest()
                                 for name in ("prices.csv", "fx.csv")}}
    (c.DATA / "sources.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def weekly_prices(prices, fx, target="USD"):
    columns = {}
    for name, symbol, market, rule, currency in c.ETFS:
        daily = prices.loc[prices.etf == name].set_index("date")["adjusted_close"].sort_index()
        # Use the same Friday FX valuation, even if an exchange closed on Thursday.
        weekly = daily.resample("W-FRI").last()
        if currency == "BRL" and target == "BRL":
            pass  # The Brazilian block keeps its original BRL prices.
        elif currency in ("BRL", "GBP"):
            key = "USDBRL" if currency == "BRL" else "GBPUSD"
            rate = fx[key].dropna().resample("W-FRI").last().reindex(weekly.index)
            if rate.loc[weekly.notna()].isna().any():
                raise ValueError(f"Missing FX observations for {name}.")
            weekly = weekly / rate if currency == "BRL" else weekly * rate
        if target == "BRL" and currency != "BRL":
            rate = fx["USDBRL"].dropna().resample("W-FRI").last().reindex(weekly.index)
            weekly = weekly * rate
        # Friday labels refer to the last available price within that week.
        complete_fridays = weekly.index < pd.Timestamp(c.END)
        columns[name] = weekly.loc[complete_fridays]
    return pd.concat(columns, axis=1)


def prepare():
    c.make_folders()
    prices = pd.read_csv(c.DATA / "prices.csv", parse_dates=["date"])
    fx_frame = pd.read_csv(c.DATA / "fx.csv", parse_dates=["date"])
    fx = fx_frame.pivot(index="date", columns="etf", values="adjusted_close").sort_index()
    panel = weekly_prices(prices, fx)
    brl_panel = weekly_prices(prices, fx, target="BRL")
    usd = panel[c.USD_ASSETS].pct_change(fill_method=None).dropna()
    brl = brl_panel[c.BRL_ASSETS].pct_change(fill_method=None).dropna()
    # Both budgets use the same dates. No observations are created before inception.
    common = usd.index.intersection(brl.index)
    if len(common) < c.RECENT_WEEKS:
        raise ValueError("Insufficient common weekly history.")
    recent = common[-c.RECENT_WEEKS:]
    cases = {"usd_long": usd.loc[common], "usd_recent": usd.loc[recent],
             "brl_long": brl.loc[common], "brl_recent": brl.loc[recent]}
    panel.to_csv(c.DATA / "weekly_prices_usd.csv", index_label="date")
    brl_panel.to_csv(c.DATA / "weekly_prices_brl.csv", index_label="date")
    metadata, asset_rows = {}, []
    for case, returns in cases.items():
        if returns.isna().any().any() or not np.isfinite(returns.to_numpy()).all():
            raise ValueError(f"Invalid returns in {case}.")
        returns.to_csv(c.DATA / f"returns_{case}.csv", index_label="date")
        covariance = returns.cov() * c.WEEKS
        correlation = returns.corr()
        covariance.to_csv(c.DATA / f"covariance_{case}.csv", index_label="etf")
        correlation.to_csv(c.DATA / f"correlation_{case}.csv", index_label="etf")
        start_price = returns.index[0] - pd.Timedelta(weeks=1)
        metadata[case] = {"assets": list(returns.columns), "currency": c.currency(case),
                          "role": "Independent currency budget",
                          "n_weeks": len(returns),
                          "price_start": str(start_price.date()),
                          "first_return": str(returns.index[0].date()),
                          "last_return": str(returns.index[-1].date())}
        years = (returns.index[-1] - start_price).days / 365.25
        for name in returns:
            values = returns[name]
            level = (1 + values).cumprod()
            wealth = np.r_[1.0, level.to_numpy()]
            drawdown = wealth / np.maximum.accumulate(wealth) - 1
            asset_rows.append({"case": case, "etf": name,
                               "mean_return": values.mean() * c.WEEKS,
                               "volatility": values.std() * np.sqrt(c.WEEKS),
                               "cagr": level.iloc[-1] ** (1 / years) - 1,
                               "max_drawdown": drawdown.min()})
    pd.DataFrame(asset_rows).to_csv(c.OUTPUT / "asset_statistics.csv", index=False)
    (c.OUTPUT / "samples.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return cases
