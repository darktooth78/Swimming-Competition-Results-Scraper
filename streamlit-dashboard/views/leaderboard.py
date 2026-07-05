"""
views/leaderboard.py
====================
View 3 — Bestzeiten / Personal Bests Leaderboard

Shows the fastest times per discipline across all SU MöDLING swimmers.
Medal badges for top 3. Filter by discipline, birth year, competition, date range.
"""

import streamlit as st
import pandas as pd
from data import load_results, load_swimmers
from i18n import t


def render(lang: str) -> None:
    all_results  = load_results()
    all_swimmers = load_swimmers()

    if all_results.empty:
        st.info(t("no_results", lang))
        return

    # Compute personal bests per swimmer × discipline
    pb_df = (
        all_results.dropna(subset=["time_sec"])
        .groupby(["swimmer_id", "name", "birth_year", "discipline"], as_index=False)
        .agg(
            best_sec   =("time_sec",    "min"),
            event_count=("event_id",    "nunique"),
        )
    )
    # Re-join time_str, event_name, date for the row with the best time
    best_rows = (
        all_results
        .sort_values("time_sec")
        .drop_duplicates(subset=["swimmer_id", "discipline"])
        [["swimmer_id", "discipline", "time_str", "event_name", "date", "date_parsed"]]
    )
    pb_df = pb_df.merge(best_rows, on=["swimmer_id", "discipline"], how="left")

    # ── Filters ────────────────────────────────────────────────────────────
    disciplines  = sorted(pb_df["discipline"].dropna().unique().tolist())
    birth_years  = sorted(pb_df["birth_year"].dropna().unique().astype(int).tolist())
    competitions = sorted(pb_df["event_name"].dropna().unique().tolist())

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        sel_disc = st.selectbox(
            t("filter_discipline", lang),
            [t("all_disciplines", lang)] + disciplines,
            key="lb_disc",
        )
    with col2:
        sel_year = st.selectbox(
            t("filter_birth_year", lang),
            [t("all_years", lang)] + [str(y) for y in birth_years],
            key="lb_year",
        )
    with col3:
        sel_comp = st.selectbox(
            t("filter_competition", lang),
            [t("all_competitions", lang)] + competitions,
            key="lb_comp",
        )
    with col4:
        dates = pb_df["date_parsed"].dropna()
        min_d = dates.min().date() if not dates.empty else None
        max_d = dates.max().date() if not dates.empty else None
        if min_d and max_d and min_d < max_d:
            sel_range = st.date_input(
                t("filter_period", lang),
                value=(min_d, max_d),
                min_value=min_d,
                max_value=max_d,
                key="lb_range",
            )
        else:
            sel_range = None

    # Apply filters
    view = pb_df.copy()
    if sel_disc != t("all_disciplines", lang):
        view = view[view["discipline"] == sel_disc]
    if sel_year != t("all_years", lang):
        view = view[view["birth_year"] == int(sel_year)]
    if sel_comp != t("all_competitions", lang):
        view = view[view["event_name"] == sel_comp]
    if sel_range and len(sel_range) == 2:
        s, e = pd.Timestamp(sel_range[0]), pd.Timestamp(sel_range[1])
        view = view[(view["date_parsed"] >= s) & (view["date_parsed"] <= e)]

    if view.empty:
        st.info(t("no_results", lang))
        return

    # When no discipline filter: show each swimmer's single best time overall
    if sel_disc == t("all_disciplines", lang):
        view = (
            view.sort_values("best_sec")
            .drop_duplicates(subset=["swimmer_id"])
        )

    view = view.sort_values("best_sec").reset_index(drop=True)

    # ── Build display table ────────────────────────────────────────────────
    def rank_badge(i: int) -> str:
        return ["🥇", "🥈", "🥉"][i] if i < 3 else str(i + 1)

    rows = []
    for i, row in view.iterrows():
        # Detect "newly achieved" PB — compare to most recent event in the full results
        latest_event_id = (
            all_results.sort_values("date_parsed", ascending=False)
            .iloc[0]["event_id"]
            if not all_results.empty else None
        )
        new_pb = (
            all_results[
                (all_results["swimmer_id"] == row["swimmer_id"]) &
                (all_results["discipline"]  == row["discipline"]) &
                (all_results["event_id"]    == latest_event_id)
            ]["time_sec"].min() == row["best_sec"]
            if latest_event_id else False
        )
        time_display = row["time_str"] + (" 🏅" if new_pb else "")

        rows.append({
            t("col_rank", lang):        rank_badge(len(rows)),
            t("col_name", lang):        row["name"],
            t("col_year", lang):        int(row["birth_year"]) if pd.notna(row["birth_year"]) else "",
            "Disziplin":                row.get("discipline", ""),
            t("col_best_time", lang):   time_display,
            t("col_competition", lang): row.get("event_name", ""),
            t("col_date", lang):        row.get("date", ""),
        })

    table = pd.DataFrame(rows)
    # Drop discipline column when a specific one is selected
    if sel_disc != t("all_disciplines", lang):
        table = table.drop(columns=["Disziplin"], errors="ignore")

    st.dataframe(table, use_container_width=True, hide_index=True)
