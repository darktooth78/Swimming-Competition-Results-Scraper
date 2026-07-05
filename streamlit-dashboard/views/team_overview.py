"""
views/team_overview.py
======================
View 2 — Mannschaftsübersicht / Team Overview

Filter bar + card/table toggle.
Card mode:   swimmer cards showing top-3 PBs.
Table mode:  pivot table with one column per discipline.
Clicking a card sets the swimmer search in View 1.
"""

import streamlit as st
import pandas as pd
from data import load_swimmers, load_results, compute_personal_bests
from i18n import t


def render(lang: str) -> None:
    all_results  = load_results()
    all_swimmers = load_swimmers()

    if all_results.empty or all_swimmers.empty:
        st.info(t("no_results", lang))
        return

    results = compute_personal_bests(all_results)

    # ── Filter bar ─────────────────────────────────────────────────────────
    disciplines  = sorted(results["discipline"].dropna().unique().tolist())
    competitions = sorted(results["event_name"].dropna().unique().tolist())
    birth_years  = sorted(all_swimmers["birth_year"].dropna().unique().astype(int).tolist())

    col1, col2, col3, col4, col5 = st.columns([2, 2, 2, 2, 2])

    with col1:
        sel_disc = st.selectbox(
            t("filter_discipline", lang),
            [t("all_disciplines", lang)] + disciplines,
            key="to_disc",
        )
    with col2:
        sel_year = st.selectbox(
            t("filter_birth_year", lang),
            [t("all_years", lang)] + [str(y) for y in birth_years],
            key="to_year",
        )
    with col3:
        sel_comp = st.selectbox(
            t("filter_competition", lang),
            [t("all_competitions", lang)] + competitions,
            key="to_comp",
        )
    with col4:
        dates  = results["date_parsed"].dropna()
        min_d  = dates.min().date() if not dates.empty else None
        max_d  = dates.max().date() if not dates.empty else None
        if min_d and max_d and min_d < max_d:
            sel_range = st.date_input(
                t("filter_period", lang),
                value=(min_d, max_d),
                min_value=min_d,
                max_value=max_d,
                key="to_range",
            )
        else:
            sel_range = None
    with col5:
        name_filter = st.text_input(t("filter_name", lang), key="to_name")

    # Apply filters
    view = results.copy()
    if sel_disc != t("all_disciplines", lang):
        view = view[view["discipline"] == sel_disc]
    if sel_year != t("all_years", lang):
        view = view[view["birth_year"] == int(sel_year)]
    if sel_comp != t("all_competitions", lang):
        view = view[view["event_name"] == sel_comp]
    if sel_range and len(sel_range) == 2:
        s, e = pd.Timestamp(sel_range[0]), pd.Timestamp(sel_range[1])
        view = view[(view["date_parsed"] >= s) & (view["date_parsed"] <= e)]
    if name_filter.strip():
        view = view[view["name"].str.contains(name_filter.strip(), case=False, na=False)]

    # ── Mode toggle ────────────────────────────────────────────────────────
    mode = st.radio(
        label="",
        options=[t("view_toggle_cards", lang), t("view_toggle_table", lang)],
        horizontal=True,
        key="to_mode",
        label_visibility="collapsed",
    )

    # Best time per (swimmer, discipline) within filtered view
    pb_view = (
        view.dropna(subset=["time_sec"])
        .groupby(["swimmer_id", "name", "birth_year", "discipline"], as_index=False)["time_sec"]
        .min()
        .rename(columns={"time_sec": "best_sec"})
    )
    # Re-join time_str for the best time row
    pb_view = pb_view.merge(
        view[["swimmer_id", "discipline", "time_sec", "time_str"]]
        .rename(columns={"time_sec": "best_sec"}),
        on=["swimmer_id", "discipline", "best_sec"],
        how="left",
    ).drop_duplicates(subset=["swimmer_id", "discipline"])

    swimmer_ids = pb_view["swimmer_id"].unique().tolist()

    if mode == t("view_toggle_cards", lang):
        # ── Card mode ──────────────────────────────────────────────────────
        cols_per_row = 3
        for row_start in range(0, len(swimmer_ids), cols_per_row):
            cols = st.columns(cols_per_row)
            for col_i, sid in enumerate(swimmer_ids[row_start:row_start + cols_per_row]):
                sw_data = pb_view[pb_view["swimmer_id"] == sid]
                sw_row  = sw_data.iloc[0]
                name       = sw_row["name"]
                birth_year = sw_row.get("birth_year", "")
                year_str   = f"Jg.{int(birth_year)}" if pd.notna(birth_year) else ""

                with cols[col_i]:
                    # Card-style container
                    with st.container(border=True):
                        st.markdown(f"**{name}**")
                        st.caption(year_str + " · SU Möd.")

                        # Show up to 3 PBs
                        for _, disc_row in sw_data.head(3).iterrows():
                            disc_short = disc_row["discipline"].replace("m ", "m ")
                            time_disp  = disc_row.get("time_str", "")
                            pb_flag    = (
                                results[(results["swimmer_id"] == sid) &
                                        (results["discipline"] == disc_row["discipline"]) &
                                        results["is_pb"]].shape[0] > 0
                            )
                            badge = " 🟢" if pb_flag else ""
                            st.markdown(f"`{disc_short}` {time_disp}{badge}")

                        if st.button(
                            "→",
                            key=f"card_{sid}",
                            help=name,
                            use_container_width=True,
                        ):
                            st.session_state["swimmer_search"] = name
                            st.session_state["active_view"]    = t("nav_swimmer", lang)
                            st.rerun()
    else:
        # ── Table mode (pivot) ─────────────────────────────────────────────
        if pb_view.empty:
            st.info(t("no_results", lang))
            return

        pivot = pb_view.pivot_table(
            index   =["swimmer_id", "name", "birth_year"],
            columns ="discipline",
            values  ="time_str",
            aggfunc ="first",
        ).reset_index()
        pivot.columns.name = None

        # Sort by name
        pivot = pivot.sort_values("name").reset_index(drop=True)

        # Rename index columns
        pivot = pivot.rename(columns={
            "name":       t("col_name", lang),
            "birth_year": t("col_year", lang),
        }).drop(columns=["swimmer_id"], errors="ignore")

        # Replace NaN with em dash
        pivot = pivot.fillna("—")

        st.dataframe(pivot, use_container_width=True, hide_index=True)
