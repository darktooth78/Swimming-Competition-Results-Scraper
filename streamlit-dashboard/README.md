# SU MöDLING Swimming Results Dashboard

Streamlit dashboard for SU MöDLING swimming competition results.
Live at: **https://swimming-competition-results-scraper-he6oihvtaox7ftfygiov6t.streamlit.app**

---

## Views

| View | Description |
|---|---|
| **Schwimmer suchen** | Swimmer profile with insights — see below |
| **Mannschaftsübersicht** | Team overview with mini bar charts per swimmer |
| **Bestzeiten** | Leaderboard with ranking bar charts per discipline |
| **Letzte Ergebnisse** | Most recently scraped competition results |

### Swimmer profile (views/swimmer.py)

The swimmer view surfaces the following insights when a swimmer is selected:

| Section | What it shows |
|---|---|
| **Header** | Name · Birth year · Age group (Mini / Jugend A-B / Junioren / Erwachsene) · Club |
| **4 metric cards** | Personal best count · Competitions attended · Disciplines swum · Best meet (most PBs achieved at one competition) |
| **Improvement callout** | Green banner with average time improvement per discipline (only shown when meaningful improvement exists) |
| **Personal Bests bar chart** | Horizontal bars per discipline — green when improved >0.5 s since first race; hover shows improvement delta (e.g. `−3.45s`) |
| **Recent form cards** | One card per discipline: PB time, ↑/↓/→ trend arrow, last result, last 3 results |
| **Progress chart** | Scatter + line per discipline tab, inverted Y axis (up = faster), gold star on PB, dashed PB reference line, dotted trend line (green = improving) |
| **Results table** | Full per-discipline result history with 🏅 badge on PB rows |

Filters (discipline, competition, date range) apply only to the progress chart and results table — the PB bar and recent form cards always show the full career picture.

---

## Local development

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Fill in real token values in secrets.toml (run generate_streamlit_token.py once locally)
streamlit run app.py
```

---

## Deployment

Deployed on [Streamlit Community Cloud](https://share.streamlit.io).

| Setting | Value |
|---|---|
| Repository | `darktooth78/Swimming-Competition-Results-Scraper` |
| **Branch** | **`feature/google-workspace-migration`** |
| Main file path | `streamlit-dashboard/app.py` |

> ⚠️ **Important:** Streamlit Cloud is deployed from the `feature/google-workspace-migration` branch, **not** `main`.
> Any code changes must be merged into `feature/google-workspace-migration` and pushed to appear on the live app.

Secrets (Google OAuth token) are stored in the Streamlit Cloud app settings — never committed to git.

---

## Data source

Results are read from the **SwimmingResults_DB** Google Sheet via the gspread library.
Sheets: `Swimmers`, `Events`, `Results`, `Log`.
All data loaders use `@st.cache_data(ttl=300)` — data refreshes every 5 minutes.
