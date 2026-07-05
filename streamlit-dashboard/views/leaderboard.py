"""
views/leaderboard.py
====================
View 3 — Bestzeiten / Personal Bests Leaderboard

Layout:
  • Discipline selector tabs (one per stroke group: Freistil, Brust, Schmetterling,
    Rücken, Lagen) — shows rankings within each stroke.
  • When a discipline tab is selected: horizontal bar chart (fastest → slowest,
    colour-coded by medal position) + ranking table below.
  • Filter bar: birth year, competition, date range.

Chart: horizontal bar chart sorted fastest-first, bars colour-coded
  🥇 gold / 🥈 silver / 🥉 bronze / rest blue.
  Each bar labelled with formatted time. Faster = longer bar (inverted X axis).
  Why: universally used for rankings — gives immediate visual sense of the gap
  between swimmers. A table alone doesn't show the spread.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from data import load_results
from i18n import t
from views.swimmer import _fmt_time, _disc_sort_key


# Medal colours
_MEDAL_COLORS = {0: "#f59e0b", 1: "#9ca3af", 2: "#b45309"}
_DEFAULT_COLOR = "#3b82d4"


def render(lang: str) -> None:
    all_results = load_results()
    if all_results.empty:
        st.info(t("no_results", lang))
        return

    # Compute PB per (swimmer, discipline)
    pb_df = (
        all_results.dropna(subset=["time_sec"])
        .sort_values("time_sec")
        .drop_duplicates(subset=["swimmer_id", "discipline"])
        [["swimmer_id", "name", "birth_year", "discipline",
          "time_sec", "time_str", "event_name", "date", "date_parsed"]]
        .copy()
    )
    pb_df["time_label"] = pb_df["time_sec"].apply(_fmt_time)

    # ── Filters ────────────────────────────────────────────────────────────
    birth_years  = sorted(pb_df["birth_year"].dropna().unique().astype(int).tolist())
    competitions = sorted(pb_df["event_name"].dropna().unique().tolist())

    col1, col2, col3 = st.columns(3)
    with col1:
        sel_year = st.selectbox(
            t("filter_birth_year", lang),
            [t("all_years", lang)] + [str(y) for y in birth_years],
            key="lb_year",
        )
    with col2:
        sel_comp = st.selectbox(
            t("filter_competition", lang),
            [t("all_competitions", lang)] + competitions,
            key="lb_comp",
        )
    with col3:
        dates = pb_df["date_parsed"].dropna()
        min_d = dates.min().date() if not dates.empty else None
        max_d = dates.max().date() if not dates.empty else None
        if min_d and max_d and min_d < max_d:
            sel_range = st.date_input(
                t("filter_period", lang),
                value=(min_d, max_d),
                min_value=min_d, max_value=max_d,
                key="lb_range",
            )
        else:
            sel_range = None

    # Apply filters (re-compute PBs within the filtered window)
    filtered = all_results.dropna(subset=["time_sec"]).copy()
    if sel_year != t("all_years", lang):
        filtered = filtered[filtered["birth_year"] == int(sel_year)]
    if sel_comp != t("all_competitions", lang):
        filtered = filtered[filtered["event_name"] == sel_comp]
    if sel_range and len(sel_range) == 2:
        s, e = pd.Timestamp(sel_range[0]), pd.Timestamp(sel_range[1])
        filtered = filtered[(filtered["date_parsed"] >= s) & (filtered["date_parsed"] <= e)]

    if filtered.empty:
        st.info(t("no_results", lang))
        return

    # Best time per (swimmer, discipline) within filtered window
    view = (
        filtered.sort_values("time_sec")
        .drop_duplicates(subset=["swimmer_id", "discipline"])
        [["swimmer_id", "name", "birth_year", "discipline",
          "time_sec", "time_str", "event_name", "date", "date_parsed"]]
        .copy()
    )
    view["time_label"] = view["time_sec"].apply(_fmt_time)

    # ── Discipline tabs ────────────────────────────────────────────────────
    all_discs = sorted(view["discipline"].dropna().unique().tolist(), key=_disc_sort_key)
    if not all_discs:
        st.info(t("no_results", lang))
        return

    # Group disciplines by stroke for tab labels
    _STROKE_LABELS = {
        "freistil":      "Freistil",
        "brust":         "Brust",
        "schmetterling": "Schmetterling",
        "rücken":        "Rücken",
        "lagen":         "Lagen",
    }

    # Build tab list: individual discipline tabs
    tab_labels = all_discs
    tabs = st.tabs(tab_labels)

    for tab, disc in zip(tabs, tab_labels):
        with tab:
            disc_view = (
                view[view["discipline"] == disc]
                .sort_values("time_sec")
                .reset_index(drop=True)
            )
            if disc_view.empty:
                st.info(t("no_results", lang))
                continue

            # ── Ranking bar chart ──────────────────────────────────────────
            # Sorted fastest → slowest (top to bottom), bars go right
            # Inverted X axis: fastest bar extends furthest
            n = len(disc_view)
            colors = [
                _MEDAL_COLORS.get(i, _DEFAULT_COLOR) for i in range(n)
            ]

            # Invert: use max_sec - time_sec so fastest = longest bar
            max_sec = disc_view["time_sec"].max()
            bar_len = max_sec - disc_view["time_sec"] + (max_sec * 0.05)

            fig = go.Figure(go.Bar(
                x            = bar_len,
                y            = disc_view["name"],
                orientation  = "h",
                text         = disc_view["time_label"],
                textposition = "inside",
                insidetextanchor = "end",
                marker_color = colors,
                hovertemplate= "<b>%{y}</b><br>" + disc + ": %{text}<extra></extra>",
                textfont     = dict(size=13, color="white"),
            ))

            # Medal annotations on first 3 bars
            medals = ["🥇", "🥈", "🥉"]
            for i in range(min(3, n)):
                fig.add_annotation(
                    x         = bar_len.iloc[i],
                    y         = disc_view["name"].iloc[i],
                    text      = medals[i],
                    showarrow = False,
                    xanchor   = "left",
                    xshift    = 6,
                    font      = dict(size=16),
                )

            fig.update_layout(
                xaxis        = dict(showticklabels=False, showgrid=False, zeroline=False, range=[0, bar_len.max() * 1.15]),
                yaxis        = dict(autorange="reversed"),
                height       = max(160, n * 38 + 50),
                margin       = dict(l=140, r=40, t=10, b=10),
                plot_bgcolor = "#f7f8fa",
            )
            st.plotly_chart(fig, use_container_width=True)

            # ── Ranking table ──────────────────────────────────────────────
            def rank_badge(i):
                return ["🥇", "🥈", "🥉"][i] if i < 3 else str(i + 1)

            table = disc_view[["name", "birth_year", "time_label", "event_name", "date"]].copy()
            table.insert(0, t("col_rank", lang),
                         [rank_badge(i) for i in range(len(table))])
            table["birth_year"] = table["birth_year"].apply(
                lambda y: int(y) if pd.notna(y) else ""
            )
            table.columns = [
                t("col_rank", lang),
                t("col_name", lang),
                t("col_year", lang),
                t("col_best_time", lang),
                t("col_competition", lang),
                t("col_date", lang),
            ]
            st.dataframe(table, use_container_width=True, hide_index=True)
