"""Build the English report from saved results."""

import base64
import html
import hashlib
import io
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import markdown
import pandas as pd
from matplotlib import rc_context
from matplotlib.font_manager import FontProperties
from matplotlib.mathtext import math_to_image

from . import config as c


def pct(value):
    return "n/a" if pd.isna(value) else f"{value * 100:.2f}%"


def pp(value):
    return "n/a" if pd.isna(value) else f"{value * 100:+.2f} pp"


def table(headers, rows, summaries=()):
    def cells(row, tag):
        return "".join(f"<{tag}>{html.escape(str(x))}</{tag}>" for x in row)
    header = "<thead><tr>" + cells(headers, "th") + "</tr></thead>"
    body = []
    for i, row in enumerate(rows):
        kind = ' class="subtotal"' if i in summaries else ""
        body.append(f"<tr{kind}>" + cells(row, "td") + "</tr>")
    return '<div class="table-scroll"><table>' + header + "<tbody>" + "".join(body) + "</tbody></table></div>"


def fields():
    samples = json.loads((c.OUTPUT / "samples.json").read_text())
    selected = pd.read_csv(c.OUTPUT / "selected_portfolios.csv")
    comparison = pd.read_csv(c.OUTPUT / "strategy_comparison.csv").set_index("case")
    diagnostic = pd.read_csv(c.OUTPUT / "simulation_check.csv")
    window = pd.read_csv(c.OUTPUT / "window_comparison.csv")
    source = json.loads((c.DATA / "sources.json").read_text())
    out = {}

    def period(case):
        sample = samples[case]
        return f"{sample['price_start']} to {sample['last_return']}; {sample['n_weeks']} weekly returns"

    for case in ["teacher", *c.MAIN_CASES]:
        inputs = diagnostic.loc[diagnostic.case == case]
        rows = [[r.etf, pct(r.simulated_mean), pct(r.simulated_volatility), "n/a"]
                for r in inputs.itertuples()]
        n_assets = len(rows)
        group = selected.loc[selected.case == case]
        equal = group.loc[group.strategy == "Equal weight"].iloc[0]
        rows.append(["Portfolio · equal weight", pct(equal.mean_return), pct(equal.volatility), "n/a"])
        best = group.loc[group.selection == "Highest sampled return"].set_index("strategy")
        for strategy, label in [("Long only", "Portfolio · long only"),
                                ("Long/short", "Portfolio · shorts allowed")]:
            row = best.loc[strategy]
            rows.append([label, pct(row.mean_return), pct(row.volatility),
                         pp(comparison.loc[case, "mean_delta"]) if strategy == "Long/short" else "n/a"])
        out["strategy_" + case] = table(
            ["Asset / portfolio", "Simulated mean", "Volatility", "Δ mean"],
            rows, range(n_assets, len(rows)))
        if case != "teacher":
            out["period_" + case] = period(case)

    for case in c.MAIN_CASES:
        currency = c.currency(case)
        group = window.loc[window.currency == currency]
        for metric in ["mean_return", "volatility"]:
            rows = [["Portfolio · equal weight" if r.etf == "Equal weight" else r.etf,
                     pct(getattr(r, metric + "_long")), pct(getattr(r, metric + "_recent")),
                     pp(getattr(r, metric + "_delta"))] for r in group.itertuples()]
            out["window_" + currency.lower() + "_" + metric] = table(
                ["Asset / portfolio", "Long", "Recent", "Δ"], rows, [len(rows) - 1])

    for metric in ["mean", "volatility"]:
        rows = []
        for case in c.BLOCK_CASES:
            row = comparison.loc[case]
            label = c.currency(case) + " · " + ("long" if case.endswith("long") else "recent")
            rows.append([label, pct(row["long_only_" + metric]), pct(row["shorts_" + metric]),
                         pp(row[metric + "_delta"])])
        out["strategy_windows_" + metric] = table(
            ["Budget / window", "Long only", "Shorts", "Δ"], rows)

    out["period_long"], out["period_recent"] = period("usd_long"), period("usd_recent")
    out["teacher_inputs"] = table(["Asset", "Target mean", "Target volatility"],
        [[name, pct(mean), pct(sd)] for name, mean, sd in zip("ABCD", c.TEACHER_MEAN, c.TEACHER_SD)])
    out["asset_list"] = table(["Budget", "ETF / Yahoo symbol", "Rule", "Quote currency"],
        [["BRL" if market == "Brazil" else "USD", f"{name} / {symbol}", rule, currency]
         for name, symbol, market, rule, currency in c.ETFS])
    rows = []
    for case in c.MAIN_CASES:
        names = samples[case]["assets"]
        group = selected.loc[(selected.case == case) & (selected.selection == "Highest sampled return")]
        for row in group.itertuples():
            weights = " · ".join(f"{name} {pct(getattr(row, name))}" for name in names)
            rows.append([c.currency(case), row.strategy, weights, pct(row.gross_exposure)])
    out["weights"] = table(["Case", "Strategy", "Weights", "Gross exposure"], rows)
    convergence = pd.read_csv(c.OUTPUT / "convergence.csv")
    rows = []
    for case in c.MAIN_CASES:
        for strategy in ["Long only", "Long/short"]:
            group = convergence.loc[(convergence.case == case) & (convergence.strategy == strategy)].set_index("n_portfolios")
            change = group.loc[c.N_PORTFOLIOS, "maximum_return"] - group.loc[50_000, "maximum_return"]
            rows.append([c.currency(case), strategy, f"{change * 100:+.4f} pp"])
    out["search_stability"] = table(["Budget", "Strategy", "Highest-mean change: 50k to 500k"], rows)
    for case in c.MAIN_CASES:
        out["gain_" + c.currency(case).lower()] = pp(comparison.loc[case, "mean_delta"])
        out["risk_change_" + c.currency(case).lower()] = pp(comparison.loc[case, "volatility_delta"])
    for row in window.loc[window.etf == "Equal weight"].itertuples():
        for metric in ["mean_return", "volatility"]:
            for suffix in ["long", "recent", "delta"]:
                value = getattr(row, metric + "_" + suffix)
                out[f"equal_{row.currency.lower()}_{metric}_{suffix}"] = pp(value) if suffix == "delta" else pct(value)
    out["n_portfolios"] = f"{c.N_PORTFOLIOS:,}"
    out["n_etf_returns"] = f"{c.N_ETF_RETURNS:,}"
    out["download_date"] = source["downloaded_utc"][:10]
    return out


def equation(match):
    """Render LaTeX notation as inline SVG, with no browser math dependency."""
    tex = match.group(1).strip()
    buffer = io.BytesIO()
    with rc_context({"mathtext.fontset": "cm", "svg.hashsalt": "msds451", "savefig.transparent": True}):
        math_to_image("$" + tex + "$", buffer, prop=FontProperties(size=14),
                      format="svg", color="#1c2420")
    svg = buffer.getvalue().decode("utf-8")
    svg = svg[svg.index("<svg"):]
    svg = re.sub(r"<metadata>.*?</metadata>", "", svg, flags=re.S)
    prefix = "eq-" + hashlib.sha256(tex.encode()).hexdigest()[:10] + "-"
    for name in re.findall(r' id="([^"]+)"', svg):
        svg = svg.replace(f'id="{name}"', f'id="{prefix}{name}"')
        svg = svg.replace(f'href="#{name}"', f'href="#{prefix}{name}"')
        svg = svg.replace(f"url(#{name})", f"url(#{prefix}{name})")
    svg = svg.replace("#1c2420", "currentColor")
    return ('<div class="equation" role="img" aria-label="' +
            html.escape(tex, quote=True) + '">' + svg + "</div>")


def render_text(path, values):
    source = path.read_text(encoding="utf-8")
    for key, value in values.items():
        source = source.replace("{{" + key + "}}", value)
    if "{{" in source:
        raise ValueError(f"Unresolved report field in {path.name}.")
    source = re.sub(r"\$\$(.*?)\$\$", equation, source, flags=re.S)
    body = markdown.markdown(source, extensions=["tables", "fenced_code", "sane_lists", "md_in_html", "toc"])
    def caption(match):
        image = match.group(1)
        label = re.search(r'alt="([^"]*)"', image).group(1)
        link = ""
        if re.match(r"Figure 2[a-d]\.", label):
            path = re.search(r'src="([^"]+)"', image).group(1)
            link = f' <a class="image-link" href="{path}" target="_blank" rel="noopener">Open original image</a>'
        return "<figure>" + image + "<figcaption>" + label + link + "</figcaption></figure>"
    return re.sub(r"<p>(<img[^>]+>)</p>", caption, body)


def page(body):
    headings = re.findall(r'<h2 id="([^"]+)">([^<]+)</h2>', body)
    nav = "".join(f'<a href="#{anchor}">{label}</a>' for anchor, label in headings)
    return PAGE.replace("__NAV__", nav).replace("__BODY__", body)


def run():
    def embed(match):
        image = base64.b64encode((c.REPORT / match.group(1)).resolve().read_bytes()).decode("ascii")
        return f'src="data:image/png;base64,{image}"'
    body = render_text(c.REPORT / "report.md", fields())
    body = re.sub(r'src="(\.\./figures/[^"]+\.png)"', embed, body)
    (c.REPORT / "msds451-pa2.html").write_text(page(body), encoding="utf-8")


def build_pdf():
    """Print the saved HTML with Edge or Chrome, using an isolated temporary profile."""
    browsers = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "google-chrome", "chromium", "msedge", "chrome",
    ]
    browser = next((shutil.which(name) for name in browsers if shutil.which(name)), None)
    if browser is None:
        raise RuntimeError("Install Edge or Chrome to use --pdf, or print the HTML manually.")
    output = c.REPORT / "msds451-pa2.pdf"
    with tempfile.TemporaryDirectory(prefix="msds451-pdf-", ignore_cleanup_errors=True) as profile:
        profile_path = Path(profile).resolve()
        assert profile_path.is_relative_to(Path(tempfile.gettempdir()).resolve())
        print_html = profile_path / "report.html"
        document = (c.REPORT / "msds451-pa2.html").read_text(encoding="utf-8")
        print_html.write_text(document.replace("<details>", "<details open>"), encoding="utf-8")
        subprocess.run([
            browser, "--headless=new", f"--user-data-dir={profile_path / 'browser'}", "--disable-gpu",
            "--no-first-run", "--no-pdf-header-footer", "--virtual-time-budget=3000",
            f"--print-to-pdf={output}", print_html.as_uri(),
        ], check=True, capture_output=True, timeout=60)
    if not output.is_file() or not output.read_bytes().startswith(b"%PDF-"):
        raise RuntimeError("The browser did not produce a valid PDF file.")
    print(f"PDF: {output}")


PAGE = '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Portfolio Allocation with Monte Carlo | Leandro Loli</title>
<style>
:root { --paper:#f3f6f4; --sheet:#ffffff; --ink:#1c2420; --muted:#5c6b63; --line:#d5ded8; --green:#1f6b56; }
* { box-sizing:border-box; }
html { scroll-behavior:smooth; }
body { margin:0; background:var(--paper); color:var(--ink); font-family:"Palatino Linotype",Palatino,"Book Antiqua",Georgia,serif; font-size:1.05rem; line-height:1.65; }
.layout { display:grid; grid-template-columns:160px minmax(0,1fr); gap:36px; width:100%; max-width:1760px; margin:0 auto; padding:36px 32px 80px; }
nav { position:sticky; top:24px; align-self:start; font-family:"Segoe UI",Helvetica,Arial,sans-serif; font-size:.78rem; letter-spacing:.04em; text-transform:uppercase; }
nav a { display:block; color:var(--ink); text-decoration:none; padding:7px 0 7px 12px; border-left:2px solid var(--line); }
nav a:hover { border-left-color:var(--green); color:var(--green); }
main { min-width:0; }
h1,h2,h3 { font-weight:650; letter-spacing:-.02em; line-height:1.25; }
h1 { font-size:1.7rem; margin:2.2rem 0 .8rem; }
h2 { font-size:1.2rem; margin:1.6rem 0 .6rem; }
h3 { font-size:1.05rem; margin:1.2rem 0 .4rem; }
.mast { margin-bottom:2rem; padding-bottom:1.3rem; border-bottom:1px solid var(--ink); }
.mast h1 { margin:0; font-size:2.05rem; line-height:1.15; }
.facts { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:.85rem 1.2rem; margin:0 0 1.45rem; }
.facts div { grid-column:span 2; min-width:0; }
.facts div.wide { grid-column:span 3; }
.facts dt { font-family:"Segoe UI",Helvetica,Arial,sans-serif; font-size:.68rem; font-weight:600; letter-spacing:.06em; text-transform:uppercase; color:var(--muted); }
.facts dd { margin:.12rem 0 0; }
p { margin:0 0 .85rem; }
a { color:var(--green); text-underline-offset:3px; overflow-wrap:anywhere; }
ul,ol { margin:0 0 .9rem; padding-left:1.2rem; }
li { margin:.2rem 0; }
.equation { margin:.5rem 0 1rem; max-width:100%; overflow-x:auto; text-align:center; }
.equation svg { display:inline-block; max-width:100%; height:auto; }
.table-scroll { max-width:100%; overflow-x:auto; margin:.4rem 0 1.4rem; }
table { width:100%; border-collapse:collapse; font-family:"Segoe UI",Helvetica,Arial,sans-serif; font-size:.82rem; font-variant-numeric:tabular-nums; line-height:1.4; }
th { text-align:left; font-size:.72rem; font-weight:600; letter-spacing:.04em; text-transform:uppercase; color:var(--muted); border-bottom:1px solid var(--ink); padding:8px 8px 8px 0; }
td { border-bottom:1px solid var(--line); padding:8px 8px 8px 0; vertical-align:middle; }
.subtotal { font-weight:600; }
.subtotal td { border-top:1px solid var(--line); }
.metric-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:20px; }
.metric-grid > div { min-width:0; }
figure { margin:1.2rem 0 1.6rem; }
img { display:block; width:100%; height:auto; }
figcaption { margin-top:8px; color:var(--muted); font-size:.92rem; }
.image-link { margin-left:.5rem; font-family:"Segoe UI",Helvetica,Arial,sans-serif; font-size:.85em; }
code { font-family:"Segoe UI",Helvetica,Arial,sans-serif; font-size:.88em; }
pre { white-space:pre-wrap; overflow-wrap:anywhere; }
details { margin:1.4rem 0; }
summary { cursor:pointer; font-family:"Segoe UI",Helvetica,Arial,sans-serif; font-weight:600; padding:.5rem 0; }
details[open] > summary { margin-bottom:1rem; }
@media(max-width:800px) {
  .layout { display:block; padding:20px 16px 48px; }
  nav { position:static; margin-bottom:24px; }
  .facts { grid-template-columns:1fr 1fr; }
  .facts div,.facts div.wide { grid-column:auto; }
}
@media(max-width:600px) { .metric-grid { grid-template-columns:1fr; } .facts { grid-template-columns:1fr; } }
@page { size:A4; margin:18mm 16mm; }
@media print {
  body { background:white; font-size:10.5pt; line-height:1.45; }
  .layout { display:block; max-width:none; padding:0; }
  nav { display:none; }
  .image-link { display:none; }
  h1,h2,h3 { break-after:avoid; }
  p { orphans:3; widows:3; }
  figure,.equation,tr { break-inside:avoid; }
  table { font-size:8pt; break-inside:avoid; }
  h2[id^="appendix-"] { break-before:page; }
  thead { display:table-header-group; }
  th,td { padding:5pt 5pt 5pt 0; }
  .table-scroll { overflow:visible; }
  img { max-height:220mm; object-fit:contain; }
  details:not([open]) > :not(summary) { display:block !important; }
}
</style>
</head>
<body><div class="layout"><nav aria-label="Contents">__NAV__</nav><main>__BODY__</main></div></body></html>'''
