"""
views/recent.py
===============
View 4 — Letzte Ergebnisse / Recent Results

Grouped by event (most recent first).
Within each event: all SU MöDLING swimmers who competed.
Green time pills = personal best in that discipline.
Filters: competition, discipline, birth year.
"""

import streamlit as st
import pandas as pd
from data import load_results, compute_personal_bests, get_last_run_label
from i18n import t


def render(lang: str) -> None:
    st.caption(f"{t('recent_scraper_run', lang)}: {get_last_run_label()}")

    all_results = load_results()
    if all_results.empty:
        st.info(t("no_results", lang))
        return

    results = compute_personal_bests(all_results)

    # ── Filters ────────────────────────────────────────────────────────────
    competitions = sorted(results["event_name"].dropna().unique().tolist(),
                          key=lambda x: results[results["event_name"] == x]["date_parsed"].max(),
                          reverse=True)
    disciplines  = sorted(results["discipline"].dropna().unique().tolist())
    birth_years  = sorted(results["birth_year"].dropna().unique().astype(int).tolist())

    col1, col2, col3 = st.columns(3)
    with col1:
        sel_comp = st.selectbox(
            t("filter_competition", lang),
            [t("all_competitions", lang)] + competitions,
            key="rec_comp",
        )
    with col2:
        sel_disc = st.selectbox(
            t("filter_discipline", lang),
            [t("all_disciplines", lang)] + disciplines,
            key="rec_disc",
        )
    with col3:
        sel_year = st.selectbox(
            t("filter_birth_year", lang),
            [t("all_years", lang)] + [str(y) for y in birth_years],
            key="rec_year",
        )

    # Apply filters
    view = results.copy()
    if sel_comp != t("all_competitions", lang):
        view = view[view["event_name"] == sel_comp]
    if sel_disc != t("all_disciplines", lang):
        view = view[view["discipline"] == sel_disc]
    if sel_year != t("all_years", lang):
        view = view[view["birth_year"] == int(sel_year)]

    if view.empty:
        st.info(t("no_results", lang))
        return

    # ── Group by event, most recent first ─────────────────────────────────
    event_order = (
        view.groupby("event_id")["date_parsed"]
        .max()
        .sort_values(ascending=False)
        .index.tolist()
    )

    for event_id in event_order:
        event_rows = view[view["event_id"] == event_id]
        event_name = event_rows["event_name"].iloc[0]
        event_date = event_rows["date"].iloc[0]

        st.markdown(f"#### 🏊 {event_name} — {event_date}")

        # Group by swimmer within this event
        swimmer_ids = event_rows["swimmer_id"].unique().tolist()
        for sid in swimmer_ids:
            sw_rows = event_rows[event_rows["swimmer_id"] == sid]
            name    = sw_rows["name"].iloc[0]

            # Build inline time pills for each discipline
            pills = []
            for _, res_row in sw_rows.sort_values("discipline").iterrows():
                disc_short = (
                    res_row["discipline"]
                    .replace("Freistil", "FS")
                    .replace("Brust",    "BR")
                    .replace("Schmetterling", "SM")
                    .replace("Rücken",   "RK")
                    .replace("Lagen",    "LA")
                )
                badge = " 🟢" if res_row["is_pb"] else ""
                pills.append(f"`{res_row['time_str']} {disc_short}{badge}`")

            st.markdown(f"**{name}** &nbsp; " + " &nbsp; ".join(pills), unsafe_allow_html=True)

        st.divider()
