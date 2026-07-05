"""
views/team_overview.py
======================
View 2 — Mannschaftsübersicht / Team Overview

Layout:
  • Filter bar (discipline, birth year, competition, date range, name search)
  • Mode toggle: Cards | Table
  • Card mode:  one card per swimmer, sorted by birth year ascending.
                Shows all PBs as a mini horizontal bar chart (same style as View 1).
                "→ Profil" button navigates to View 1.
  • Table mode: pivot table — rows = swimmers sorted by name,
                columns = disciplines sorted by stroke group + distance,
                cells = best time (formatted), empty = "—".
                Fastest per column highlighted in bold.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from data import load_swimmers, load_results, compute_personal_bests
from i18n import t
from views.swimmer import _fmt_time, _disc_sort_key


def render(lang: str) -> None:
    all_results  = load_results()
    all_swimmers = load_swimmers()

    if all_results.empty or all_swimmers.empty:
        st.info(t("no_results", lang))
        return

    results = compute_personal_bests(all_results)

    # ── Filter bar ─────────────────────────────────────────────────────────
    disciplines = sorted(results["discipline"].dropna().unique().tolist(), key=_disc_sort_key)
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
        dates = results["date_parsed"].dropna()
        min_d = dates.min().date() if not dates.empty else None
        max_d = dates.max().date() if not dates.empty else None
        if min_d and max_d and min_d < max_d:
            sel_range = st.date_input(
                t("filter_period", lang),
                value=(min_d, max_d),
                min_value=min_d, max_value=max_d,
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

    if view.empty:
        st.info(t("no_results", lang))
        return

    # Best time per (swimmer, discipline) within filtered view
    pb_view = (
        view.dropna(subset=["time_sec"])
        .groupby(["swimmer_id", "name", "birth_year", "discipline"], as_index=False)["time_sec"]
        .min()
        .rename(columns={"time_sec": "best_sec"})
    )
    pb_view["time_label"] = pb_view["best_sec"].apply(_fmt_time)

    # Sort swimmers by birth year ascending (youngest first)
    swimmer_order = (
        pb_view.drop_duplicates("swimmer_id")
        .sort_values(["birth_year", "name"])["swimmer_id"]
        .tolist()
    )

    # ── Mode toggle ────────────────────────────────────────────────────────
    mode = st.radio(
        label="",
        options=[t("view_toggle_cards", lang), t("view_toggle_table", lang)],
        horizontal=True,
        key="to_mode",
        label_visibility="collapsed",
    )

    # ══════════════════════════════════════════════════════════════════════
    # CARD MODE
    # ══════════════════════════════════════════════════════════════════════
    if mode == t("view_toggle_cards", lang):
        cols_per_row = 3
        for row_start in range(0, len(swimmer_order), cols_per_row):
            cols = st.columns(cols_per_row)
            for col_i, sid in enumerate(swimmer_order[row_start:row_start + cols_per_row]):
                sw_data = pb_view[pb_view["swimmer_id"] == sid].copy()
                sw_data = sw_data.sort_values(
                    "discipline", key=lambda s: [_disc_sort_key(d) for d in s]
                )
                sw_row     = sw_data.iloc[0]
                name       = sw_row["name"]
                birth_year = sw_row.get("birth_year", "")
                year_str   = f"Jg. {int(birth_year)}" if pd.notna(birth_year) else ""

                with cols[col_i]:
                    with st.container(border=True):
                        st.markdown(f"**{name}**")
                        st.caption(year_str)

                        # Mini horizontal bar chart — all disciplines, sorted
                        fig = go.Figure(go.Bar(
                            x            = sw_data["best_sec"],
                            y            = sw_data["discipline"],
                            orientation  = "h",
                            text         = sw_data["time_label"],
                            textposition = "outside",
                            marker_color = "#3b82d4",
                            hovertemplate= "%{y}: %{text}<extra></extra>",
                        ))
                        fig.update_layout(
                            xaxis  = dict(showticklabels=False, showgrid=False, zeroline=False),
                            yaxis  = dict(autorange="reversed"),
                            height = max(100, len(sw_data) * 28 + 30),
                            margin = dict(l=100, r=60, t=4, b=4),
                            plot_bgcolor = "#f7f8fa",
                        )
                        st.plotly_chart(fig, use_container_width=True, key=f"card_chart_{sid}")

                        if st.button(
                            "→ Profil" if lang == "de" else "→ Profile",
                            key=f"card_{sid}",
                            use_container_width=True,
                        ):
                            st.session_state["swimmer_search"] = name
                            st.session_state["active_view"]    = "swimmer"
                            st.rerun()

    # ══════════════════════════════════════════════════════════════════════
    # TABLE MODE — pivot, fastest per column in bold
    # ══════════════════════════════════════════════════════════════════════
    else:
        pivot_raw = pb_view.pivot_table(
            index   = ["swimmer_id", "name", "birth_year"],
            columns = "discipline",
            values  = "best_sec",
            aggfunc = "min",
        ).reset_index()
        pivot_raw.columns.name = None

        # Sort discipline columns by stroke group + distance
        disc_cols = [c for c in pivot_raw.columns if c not in ("swimmer_id", "name", "birth_year")]
        disc_cols_sorted = sorted(disc_cols, key=_disc_sort_key)

        # Sort rows by name
        pivot_raw = pivot_raw.sort_values("name").reset_index(drop=True)

        # Build display dataframe with formatted times
        display = pd.DataFrame()
        display[t("col_name", lang)]  = pivot_raw["name"]
        display[t("col_year", lang)]  = pivot_raw["birth_year"].apply(
            lambda y: int(y) if pd.notna(y) else ""
        )
        for disc in disc_cols_sorted:
            display[disc] = pivot_raw[disc].apply(
                lambda v: _fmt_time(v) if pd.notna(v) else "—"
            )

        # Mark fastest per discipline column with 🥇
        for disc in disc_cols_sorted:
            col_sec = pivot_raw[disc]
            if col_sec.dropna().empty:
                continue
            fastest_idx = col_sec.idxmin()
            display.loc[fastest_idx, disc] = "🥇 " + display.loc[fastest_idx, disc]

        st.dataframe(display, use_container_width=True, hide_index=True)
