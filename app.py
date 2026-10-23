"""Real Exchange Rate Explorer — IMF monthly CPI and FX data.

Compatible with Python 3.12 and Streamlit Community Cloud.
Source: IMF SDMX 3.0 API (CPI and ER flows, IMF.STA).
"""

from __future__ import annotations

from datetime import date
from io import StringIO
import re
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pycountry
import requests
from babel.numbers import get_territory_currencies
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import streamlit as st

API_ROOT = "https://api.imf.org/external/sdmx/3.0"
FIRST_MONTH = "1976-01"
EURO_AREA_CODE = "G163"

st.set_page_config(page_title="Real Exchange Rate Explorer", page_icon="🌐", layout="wide")


def http_session() -> requests.Session:
    """Create a request session with conservative retries for transient IMF outages."""
    session = requests.Session()
    retry = Retry(
        total=2,
        backoff_factor=0.8,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({
        "Accept": "application/vnd.sdmx.data+csv",
        "User-Agent": "MBA-Real-Exchange-Rate-Explorer/1.0 (educational Streamlit app)",
    })
    return session


def imf_get(url: str, accept: str = "application/vnd.sdmx.data+csv", timeout: int = 30) -> requests.Response:
    """Fetch only public IMF resources, raising explanatory errors on failure."""
    try:
        with http_session() as session:
            response = session.get(url, headers={"Accept": accept}, timeout=timeout)
            response.raise_for_status()
            return response
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        raise RuntimeError(f"IMF API returned HTTP {status}. The series may be unavailable or the service may be busy.") from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not connect to the IMF API: {exc}") from exc


def period_to_month(raw: object) -> Optional[pd.Timestamp]:
    """Parse IMF monthly periods such as 2024-M02, 2024-02 or 2024-02-29."""
    value = str(raw).strip()
    match = re.fullmatch(r"(\d{4})-(?:M)?(0?[1-9]|1[0-2])(?:-\d{2})?", value)
    if not match:
        return None
    try:
        return pd.Timestamp(year=int(match.group(1)), month=int(match.group(2)), day=1)
    except ValueError:
        return None


def parse_imf_csv(payload: str, label: str) -> pd.Series:
    """Extract a validated single monthly series from IMF SDMX CSV response."""
    if not payload.strip():
        return pd.Series(dtype=float, name=label)
    try:
        frame = pd.read_csv(StringIO(payload), dtype={"TIME_PERIOD": str}, low_memory=False)
    except (ValueError, pd.errors.ParserError) as exc:
        raise RuntimeError(f"Unable to decode IMF CSV for {label}: {exc}") from exc
    frame.columns = frame.columns.str.replace("\ufeff", "", regex=False).str.strip()
    if "TIME_PERIOD" not in frame.columns or "OBS_VALUE" not in frame.columns:
        raise RuntimeError(f"Unexpected IMF data structure for {label}. Expected TIME_PERIOD and OBS_VALUE columns.")
    months = frame["TIME_PERIOD"].map(period_to_month)
    values = pd.to_numeric(frame["OBS_VALUE"], errors="coerce")
    series = pd.Series(values.to_numpy(dtype=float), index=pd.DatetimeIndex(months), name=label)
    series = series.loc[series.index.notna()]
    # IMF series should have one observation per month. Prefer the last if duplicated.
    series = series[~series.index.duplicated(keep="last")].sort_index()
    series = series.loc[series.index >= pd.Timestamp(FIRST_MONTH)]
    return series


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def fetch_imf_series(country: str, indicator: str) -> pd.Series:
    """Fetch the full available monthly CPI or local-currency-per-USD rate."""
    if indicator == "cpi":
        flow, key, label = "CPI", f"{country}.CPI._T.IX.M", f"CPI_{country}"
    elif indicator == "fx":
        flow, key, label = "ER", f"{country}.XDC_USD.PA_RT.M", f"FX_{country}"
        if country == "USA":
            # For the United States, domestic currency is USD, so USD per USD = 1.
            # Some IMF ER API selections do not publish this identity series.
            end = pd.Timestamp.today().to_period("M").start_time
            months = pd.date_range(FIRST_MONTH, end, freq="MS")
            return pd.Series(1.0, index=months, name=label)
    else:
        raise ValueError(f"Unknown indicator: {indicator}")

    url = f"{API_ROOT}/data/dataflow/IMF.STA/{flow}/+/{key}"
    response = imf_get(url)
    series = parse_imf_csv(response.content.decode("utf-8-sig", errors="replace"), label)
    # CPI levels and FX units/USD must be positive for economically valid RERs.
    return series.where(series > 0)


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def imf_country_codes() -> Optional[tuple[str, ...]]:
    """Find countries represented in the IMF CPI dataflow availability metadata.

    The selection is based on IMF reporting areas; an area's individual CPI or
    exchange-rate observations may still be absent for a chosen sample period.
    """
    url = f"{API_ROOT}/availability/dataflow/IMF.STA/CPI/+/*/*?mode=exact"
    try:
        response = imf_get(url, accept="application/json", timeout=15)
        payload = response.json()
        constraints = payload.get("data", {}).get("dataConstraints", [])
        codes: set[str] = set()
        for constraint in constraints:
            for region in constraint.get("cubeRegions", []):
                for component in region.get("components", []):
                    if component.get("id") == "COUNTRY":
                        for item in component.get("values", []):
                            code = item.get("value", "")
                            if code == EURO_AREA_CODE or (
                                len(code) == 3 and code.isalpha() and pycountry.countries.get(alpha_3=code)
                            ):
                                codes.add(code)
        return tuple(sorted(codes)) if len(codes) >= 25 else None
    except (RuntimeError, ValueError, KeyError, TypeError):
        return None


def country_choices() -> dict[str, str]:
    codes = imf_country_codes()
    if codes is None:
        # Fallback when the IMF availability endpoint is down. Some ISO countries
        # may not have IMF observations; missing data are reported to the user.
        codes = tuple(c.alpha_3 for c in pycountry.countries)
    choices = {}
    for code in codes:
        if code == EURO_AREA_CODE:
            choices[code] = "Euro area (G163)"
        else:
            country = pycountry.countries.get(alpha_3=code)
            if country:
                choices[code] = f"{country.name} ({code})"
    choices[EURO_AREA_CODE] = "Euro area (G163)"
    return choices


def currency_name(country: str) -> str:
    """Provide current currency labels for readability; series are IMF-defined."""
    if country == EURO_AREA_CODE:
        return "EUR"
    if country == "USA":
        return "USD"
    if country == "GBR":
        return "GBP"
    entry = pycountry.countries.get(alpha_3=country)
    if entry is None:
        return country
    try:
        currencies = get_territory_currencies(entry.alpha_2, start_date=date.today())
        return currencies[0] if currencies else country
    except (KeyError, ValueError, AttributeError):
        return country


def calculate_table(cpi1: pd.Series, cpi2: pd.Series,
                    fx1: pd.Series, fx2: pd.Series,
                    start: str, end: str) -> tuple[pd.DataFrame, float]:
    """Align by month, compute S=FX2/FX1 and normalize by sample-mean RER."""
    months = pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="MS")
    table = pd.DataFrame(index=months)
    table.index.name = "month"
    for col, series in [("cpi_1", cpi1), ("cpi_2", cpi2),
                        ("fx_1_lcu_per_usd", fx1), ("fx_2_lcu_per_usd", fx2)]:
        table[col] = series.reindex(months)
        table[col] = table[col].where(table[col] > 0)

    # Missing data propagate as NaN; do not interpolate or invent observations.
    table["nominal_S"] = table["fx_2_lcu_per_usd"] / table["fx_1_lcu_per_usd"]
    table["rer"] = table["nominal_S"] * table["cpi_1"] / table["cpi_2"]
    valid = table["rer"].dropna()
    if valid.empty:
        raise ValueError("No overlapping valid monthly CPI and exchange-rate observations in the selected sample.")
    rer_star = float(valid.mean())
    if rer_star <= 0:
        raise ValueError("The sample RER mean is not positive; check IMF inputs.")
    table["rer_star_sample"] = rer_star
    table["real_index"] = 100.0 * table["rer"] / rer_star
    return table, rer_star


st.title("🌐 Real Exchange Rate Explorer")
st.caption("IMF monthly Consumer Price Index (CPI) & Exchange Rates (ER) • 1976 onward, where available")
st.markdown(
    "Choose two countries, compare the **real exchange-rate index** and the "
    "**nominal exchange rate**, and export the complete calculation."
)

with st.sidebar:
    st.header("Country selection")
    with st.spinner("Loading IMF reporting areas..."):
        countries = country_choices()
    codes = sorted(countries.keys(), key=lambda x: countries[x].lower())
    country1 = st.selectbox("Country 1 (base currency)", codes,
                            index=codes.index("GBR") if "GBR" in codes else 0,
                            format_func=lambda code: countries[code])
    country2 = st.selectbox("Country 2 (quote currency)", codes,
                            index=codes.index("USA") if "USA" in codes else min(1, len(codes)-1),
                            format_func=lambda code: countries[code])
    st.divider()
    st.header("Sample window")
    current_month = pd.Timestamp.today().to_period("M").strftime("%Y-%m")
    months = pd.period_range(FIRST_MONTH, current_month, freq="M").astype(str).tolist()
    default_start = "2000-01" if "2000-01" in months else FIRST_MONTH
    start = st.selectbox("Start month", months, index=months.index(default_start))
    end = st.selectbox("End month", months, index=len(months) - 1)
    st.divider()
    view = st.radio("Chart series", ["Both", "Real", "Nominal"], horizontal=False)
    st.caption("Data are retrieved from the IMF API. Missing observations are never filled in.")

if country1 == country2:
    st.info("Select different countries to compare two currencies.")
    st.stop()
if start > end:
    st.error("Start month must be no later than end month.")
    st.stop()

c1_currency, c2_currency = currency_name(country1), currency_name(country2)
nominal_unit = f"{c2_currency} per {c1_currency}"

with st.spinner("Downloading and aligning IMF monthly data..."):
    try:
        cpi1 = fetch_imf_series(country1, "cpi")
        cpi2 = fetch_imf_series(country2, "cpi")
        fx1 = fetch_imf_series(country1, "fx")
        fx2 = fetch_imf_series(country2, "fx")
    except RuntimeError as exc:
        st.error(str(exc))
        st.info("Try a different country pair or reload later. The IMF API may be temporarily unavailable. No sample or synthetic data are substituted.")
        st.stop()

try:
    table, rer_star = calculate_table(cpi1, cpi2, fx1, fx2, start, end)
except ValueError as exc:
    st.error(str(exc))
    st.info("This may occur for a country without monthly IMF CPI or FX observations. Try UK / United States and a shorter recent sample.")
    st.stop()

observed = table.dropna(subset=["rer"])
missing_months = len(table) - len(observed)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Valid monthly observations", f"{len(observed):,}")
m2.metric("Sample mean RER (RER*)", f"{rer_star:,.4f}")
m3.metric("Mean real index", f"{observed['real_index'].mean():.6f}")
m4.metric("Missing months", f"{missing_months:,}")

if missing_months:
    st.warning(f"{missing_months} of {len(table)} months lack at least one valid input. They are excluded from the RER* average, and appear as blank cells in the CSV.")

st.subheader(f"{countries[country1]} → {countries[country2]}")
st.caption(f"Nominal exchange rate: {nominal_unit}; one unit of Country 1 currency buys S units of Country 2 currency.")

fig = make_subplots(specs=[[{"secondary_y": True}]])
if view in ("Real", "Both"):
    fig.add_trace(go.Scatter(x=table.index, y=table["real_index"], mode="lines",
                             name="Real index (sample mean = 100)",
                             hovertemplate="%{x|%b %Y}<br>Index %{y:.3f}<extra></extra>",
                             connectgaps=False), secondary_y=False)
    fig.add_hline(y=100, line_dash="dot", line_color="gray",
                  annotation_text="Sample mean = 100", annotation_position="top left")
if view in ("Nominal", "Both"):
    fig.add_trace(go.Scatter(x=table.index, y=table["nominal_S"], mode="lines",
                             name=f"Nominal S ({nominal_unit})",
                             hovertemplate=f"%{{x|%b %Y}}<br>S %{{y:.5f}} {nominal_unit}<extra></extra>",
                             connectgaps=False), secondary_y=(view == "Both"))

fig.update_yaxes(title_text="Real index (sample mean = 100)",
                 secondary_y=False, visible=(view != "Nominal"))
fig.update_yaxes(title_text=f"Nominal S ({nominal_unit})", secondary_y=True,
                 visible=(view == "Both"))
if view == "Nominal":
    # A single series uses the main left axis; keep it in actual currency units.
    fig.update_yaxes(title_text=f"Nominal S ({nominal_unit})", secondary_y=False, visible=True)
fig.update_layout(height=530, hovermode="x unified", legend=dict(orientation="h", y=1.12),
                  margin=dict(l=45, r=45, t=70, b=30), xaxis_title="Month")
st.plotly_chart(fig, use_container_width=True)

with st.expander("Show formulas and data definitions", expanded=False):
    st.latex(r"S_t=\frac{FX_{2,t}}{FX_{1,t}}")
    st.latex(r"RER_t=S_t\times\frac{CPI_{1,t}}{CPI_{2,t}}")
    st.latex(r"RER^*=\frac{1}{N}\sum_{t\in\mathcal{V}}RER_t")
    st.latex(r"\mathrm{Real\ Index}_t=100\times\frac{RER_t}{RER^*}")
    st.write("CPI is the IMF all-items monthly CPI index (`CPI._T.IX.M`). "
             "FX is the IMF monthly average domestic-currency units per USD (`XDC_USD.PA_RT.M`). "
             "The US domestic currency per USD is identically 1. "
             "RER* is recomputed each time you change the sample. "
             "Only months with all four valid inputs enter the mean.")

st.subheader("Download or inspect calculations")
export = table.reset_index().copy()
export.insert(1, "country_1", country1)
export.insert(2, "country_2", country2)
export["month"] = export["month"].dt.strftime("%Y-%m")
export = export.rename(columns={
    "nominal_S": "nominal_S_country2_per_country1",
    "rer": "RER",
    "real_index": "Real_Index",
    "rer_star_sample": "RER_star_sample_mean",
})
csv_text = export.to_csv(index=False, float_format="%.12g", na_rep="")
st.download_button("⬇️ Download CSV (selected sample)", data=csv_text,
                   file_name=f"imf_rer_{country1}_{country2}_{start}_{end}.csv",
                   mime="text/csv", type="primary")
st.dataframe(export, use_container_width=True, hide_index=True)

st.caption("Source: International Monetary Fund (IMF), CPI and Exchange Rates (ER) dataflows, IMF SDMX 3.0 API. "
           "Data coverage and availability depend on the selected economy. Current currency labels are for display; "
           "historical series are as published by the IMF.")
