[README.md](https://github.com/user-attachments/files/33854350/README.md)
# Real Exchange Rate Explorer — IMF Data

A Streamlit app for comparing nominal and real exchange rates between two IMF reporting economies, including the euro area (G163). Built for an international macroeconomics assignment.

## Live data source

- **IMF Data Portal:** https://data.imf.org/
- **IMF SDMX 3.0 API:** https://api.imf.org/external/sdmx/3.0
- **Monthly CPI (all items, index):** `IMF.STA/CPI` series `{ISO3}.CPI._T.IX.M`
- **Monthly exchange rate (domestic currency per USD, period average):** `IMF.STA/ER` series `{ISO3}.XDC_USD.PA_RT.M`
- **Euro area:** `G163` (when IMF CPI and exchange-rate observations exist)
- **US exchange rate:** 1 USD per USD, by definition.

The application requests actual IMF data. No fabricated observations, substitutions, or interpolation are used. IMF coverage varies by country, and API calls can occasionally fail.

## Economic method

For a pair of countries and a given month *t*:

- `FX1` and `FX2` are local-currency units per USD from the IMF.
- `S(t) = FX2(t) / FX1(t)` is **Country 2 currency units per one unit of Country 1 currency**.
- `RER(t) = S(t) × CPI1(t) / CPI2(t)`.
- `RER* = mean(RER(t))` across **valid months within the user-selected sample**.
- `Real Index(t) = 100 × RER(t) / RER*`.

By construction, the mean of all valid `Real_Index` observations is 100, except for floating-point rounding. Changing start/end months recalculates `RER*`. The nominal exchange rate is never normalized. The **Both** option uses separate Y axes. Missing months appear as blank entries in the downloaded CSV and are excluded from the real-index average.

## Features

- Country 1 and Country 2 selectors and euro-area aggregate
- Monthly data since January 1976, where IMF observations exist
- User-selected start and end months
- Interactive Real, Nominal, and Both Plotly charts
- Dual Y axes in Both mode
- Transparent missing-data reporting
- Downloadable CSV with monthly CPI, FX, nominal S, RER, RER* and real index
- Caching and retry handling for temporary IMF service issues

## Files

- `app.py` — Streamlit application
- `requirements.txt` — Python 3.12 dependencies
- `README.md` — Documentation

## Deploy on Streamlit Community Cloud (no local Python required)

1. Create a **public** GitHub repository named `real-exchange-rate-app` with a README.
2. Put all three files at the repository root (top level). Replace the existing README content.
3. Open https://share.streamlit.io and sign in with GitHub.
4. Select **Create app → Yup, I have an app**.
5. Choose repository `real-exchange-rate-app`, branch `main`, and main file `app.py`.
6. In Advanced settings choose **Python 3.12**. Leave secrets empty.
7. Click **Deploy** and copy your `*.streamlit.app` URL.

To run locally (optional): `pip install -r requirements.txt && streamlit run app.py`.

## Verification checklist (for class submission)

- Select **United Kingdom (GBR)** as Country 1 and **United States (USA)** as Country 2.
- Confirm nominal `S` is **USD per GBP** (not GBP per USD).
- Use **Real**, **Nominal**, and **Both** chart modes.
- Change the sample dates; download a new CSV and verify that the mean of nonblank `Real_Index` entries is 100.
- For one month, manually verify: `S = FX2 / FX1` and `RER = S * CPI1 / CPI2`, using actual downloaded IMF input numbers.
- Submit the Streamlit URL, GitHub URL, prompt/chat screenshots, AI model name/date, manual verification, and the downloaded CSV.

## Notes

The app first tries to populate reporting countries from the IMF CPI availability metadata. If that metadata endpoint is temporarily unavailable, it falls back to a broad ISO country selection. Not every country has monthly CPI or FX data; the app displays an error instead of inventing missing data. IMF source data are fetched from the public SDMX 3.0 endpoint (generally no API key required).

### AI assistance

Prepared with OpenAI GPT-6 on October 22, 2026. For academic submission, include **your actual prompt and conversation screenshots**, and record any subsequent AI revisions/dates.
