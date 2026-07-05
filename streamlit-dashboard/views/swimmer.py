"""
views/swimmer.py
================
View 1 — Schwimmer suchen / Find Swimmer

Search for a swimmer by name, then display:
  • Swimmer header with stat pills
  • Discipline tab selector
  • Progress line chart (time_sec inverted — lower = better = higher on chart)
  • Filterable results table with PB badge
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from data import load_swimmers, load_results, load_events, compute_personal_bests
from i18n import t


def render(lang: str) -> None:
    # ── Hero banner ────────────────────────────────────────────────────────
    st.markdown(f"### 🏊 {t('hero_title', lang)}")

    swimmers = load_swimmers()
    if swimmers.empty:
        st.info(t("no_results", lang))
        return

    # ── Search box ─────────────────────────────────────────────────────────
    search_query = st.text_input(
        label=t("nav_swimmer", lang),
        placeholder=t("search_placeholder", lang),
        key="swimmer_search",
        label_visibility="collapsed",
    )

    # Filter swimmer list by search query
    if search_query.strip():
        mask = swimmers["name"].str.contains(search_query.strip(), case=False, na=False)
        filtered = swimmers[mask]
    else:
        filtered = swimmers

    if filtered.empty:
        st.info(t("no_results", lang))
        return

    # Dropdown to select one swimmer
    name_options = filtered["name"].tolist()
    selected_name = st.selectbox(
        label=t("select_swimmer", lang),
        options=name_options,
        key="swimmer_select",
        label_visibility="collapsed",
    )

    selected_row = filtered[filtered["name"] == selected_name].iloc[0]
    swimmer_id   = selected_row["swimmer_id"]
    birth_year   = selected_row.get("birth_year", "")
    club         = selected_row.get("club", "")

    # ── Swimmer header ─────────────────────────────────────────────────────
    year_str = f"{t('swimmer_info_year', lang)}: {int(birth_year)}" if pd.notna(birth_year) else ""
    club_str = f"{t('swimmer_info_club', lang)}: {club}" if club else ""
    st.markdown(f"## 🏊 {selected_name}")
    if year_str or club_str:
        st.caption("  ·  ".join(filter(None, [year_str, club_str])))

    # Load results for this swimmer
    all_results = load_results()
    if all_results.empty:
        st.info(t("no_results", lang))
        return

    swimmer_results = all_results[all_results["swimmer_id"] == swimmer_id].copy()
    if swimmer_results.empty:
        st.info(t("no_results", lang))
        return

    swimmer_results = compute_personal_bests(swimmer_results)

    # ── Filters ────────────────────────────────────────────────────────────
    disciplines  = sorted(swimmer_results["discipline"].dropna().unique().tolist())
    competitions = sorted(swimmer_results["event_name"].dropna().unique().tolist())

    col1, col2, col3 = st.columns(3)
    with col1:
        sel_disc  = st.selectbox(
            t("filter_discipline", lang),
            [t("all_disciplines", lang)] + disciplines,
            key="sw_disc",
        )
    with col2:
        sel_comp  = st.selectbox(
            t("filter_competition", lang),
            [t("all_competitions", lang)] + competitions,
            key="sw_comp",
        )
    with col3:
        dates = swimmer_results["date_parsed"].dropna()
        min_d = dates.min().date() if not dates.empty else None
        max_d = dates.max().date() if not dates.empty else None
        if min_d and max_d and min_d < max_d:
            sel_range = st.date_input(
                t("filter_period", lang),
                value=(min_d, max_d),
                min_value=min_d,
                max_value=max_d,
                key="sw_range",
            )
        else:
            sel_range = None

    # Apply filters
    view = swimmer_results.copy()
    if sel_disc != t("all_disciplines", lang):
        view = view[view["discipline"] == sel_disc]
    if sel_comp != t("all_competitions", lang):
        view = view[view["event_name"] == sel_comp]
    if sel_range and len(sel_range) == 2:
        s, e = pd.Timestamp(sel_range[0]), pd.Timestamp(sel_range[1])
        view = view[(view["date_parsed"] >= s) & (view["date_parsed"] <= e)]

    # ── Stat pills ─────────────────────────────────────────────────────────
    n_disc = swimmer_results["discipline"].nunique()
    n_comp = swimmer_results["event_name"].nunique()
    n_pb   = swimmer_results["is_pb"].sum()
    c1, c2, c3 = st.columns(3)
    c1.metric(t("disciplines_label",    lang), n_disc)
    c2.metric(t("competitions_label",   lang), n_comp)
    c3.metric(t("personal_bests_label", lang), int(n_pb))

    # ── Discipline tabs ────────────────────────────────────────────────────
    view_disciplines = sorted(view["discipline"].dropna().unique().tolist())
    if not view_disciplines:
        st.info(t("no_results", lang))
        return

    tab_labels = view_disciplines
    tabs = st.tabs(tab_labels)

    for tab, disc in zip(tabs, tab_labels):
        with tab:
            disc_data = view[view["discipline"] == disc].sort_values("date_parsed")
            if disc_data.empty:
                st.info(t("no_results", lang))
                continue

            # ── Line chart ─────────────────────────────────────────────────
            pb_row = disc_data.loc[disc_data["time_sec"].idxmin()]
            fig    = go.Figure()

            fig.add_trace(go.Scatter(
                x    = disc_data["date_parsed"],
                y    = disc_data["time_sec"],
                mode = "lines+markers",
                name = disc,
                line = dict(color="#3b82d4", width=2),
                marker = dict(size=8),
                text = disc_data["time_str"],
                hovertemplate="%{text}<br>%{x|%d.%m.%Y}<extra></extra>",
            ))

            # PB annotation
            fig.add_annotation(
                x    = pb_row["date_parsed"],
                y    = pb_row["time_sec"],
                text = "🏅 PB",
                showarrow=True,
                arrowhead=2,
                ax=0, ay=-30,
            )

            # Invert y-axis: lower time (faster) appears higher
            fig.update_yaxes(
                autorange="reversed",
                tickformat=".2f",
                title_text=t("col_time", lang),
            )
            fig.update_layout(
                title=f"{t('chart_title', lang)} — {disc}",
                xaxis_title="",
                showlegend=False,
                height=320,
                margin=dict(l=20, r=20, t=40, b=20),
            )
            st.plotly_chart(fig, use_container_width=True)

            # ── Results table ──────────────────────────────────────────────
            table = disc_data[["date", "event_name", "location", "time_str", "is_pb"]].copy()
            table["time_str"] = table.apply(
                lambda r: r["time_str"] + " 🏅" if r["is_pb"] else r["time_str"],
                axis=1,
            )
            table = table.drop(columns=["is_pb"])
            table.columns = [
                t("col_date", lang),
                t("col_competition", lang),
                t("col_location", lang),
                t("col_time", lang),
            ]
            st.dataframe(table, use_container_width=True, hide_index=True)
