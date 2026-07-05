"""
views/swimmer.py
================
View 1 — Schwimmer suchen / Find Swimmer

Charts used (evidence-based for swim performance):

1. PROGRESS CHART — Scatter + line, inverted Y axis (lower time = faster = higher on chart).
   X = competition date, Y = time in seconds (displayed as MM:SS.ss).
   Each point labelled with the formatted time on hover + competition name.
   Personal best highlighted with a gold star marker and dashed horizontal PB line.
   Trend line (rolling mean or linear regression) shows direction of improvement.
   Why: Standard in Swim.com, SwimCloud, Olympic analytics. Inverted axis is the
   universal convention — swimmers and coaches read "going up" as improving.

2. PERSONAL BESTS BAR CHART — Horizontal bars, one per discipline, sorted by
   stroke group then distance. Bar length = time in seconds, label = formatted time.
   Why: Instantly shows a swimmer's full profile and strongest events at a glance.
   Better than a table for quick visual comparison across disciplines.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from data import load_swimmers, load_results, compute_personal_bests
from i18n import t


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_time(sec: float) -> str:
    """Format seconds as M:SS.ss or SS.ss (matching myresults.eu convention)."""
    if pd.isna(sec) or sec >= 999999:
        return "—"
    if sec >= 60:
        m  = int(sec // 60)
        s  = sec - m * 60
        return f"{m}:{s:05.2f}"
    return f"{sec:.2f}"


# Stroke sort order for discipline bar chart
_STROKE_ORDER = ["freistil", "brust", "schmetterling", "rücken", "lagen"]

def _disc_sort_key(disc: str):
    parts = disc.lower().split()
    try:
        dist = int(parts[0].rstrip("m"))
    except (ValueError, IndexError):
        dist = 9999
    stroke = parts[1] if len(parts) > 1 else ""
    rank = _STROKE_ORDER.index(stroke) if stroke in _STROKE_ORDER else len(_STROKE_ORDER)
    return (rank, dist)


# ---------------------------------------------------------------------------
# Main view
# ---------------------------------------------------------------------------

def render(lang: str) -> None:
    st.markdown(f"### 🏊 {t('hero_title', lang)}")

    swimmers = load_swimmers()
    if swimmers.empty:
        st.info(t("no_results", lang))
        return

    # ── Search ─────────────────────────────────────────────────────────────
    search_query = st.text_input(
        label=t("nav_swimmer", lang),
        placeholder=t("search_placeholder", lang),
        key="swimmer_search",
        label_visibility="collapsed",
    )

    filtered = (
        swimmers[swimmers["name"].str.contains(search_query.strip(), case=False, na=False)]
        if search_query.strip() else swimmers
    )

    if filtered.empty:
        st.info(t("no_results", lang))
        return

    selected_name = st.selectbox(
        label=t("select_swimmer", lang),
        options=filtered["name"].tolist(),
        key="swimmer_select",
        label_visibility="collapsed",
    )

    selected_row = filtered[filtered["name"] == selected_name].iloc[0]
    swimmer_id   = selected_row["swimmer_id"]
    birth_year   = selected_row.get("birth_year", "")
    club         = selected_row.get("club", "")

    # ── Header ─────────────────────────────────────────────────────────────
    year_str = f"{t('swimmer_info_year', lang)}: {int(birth_year)}" if pd.notna(birth_year) else ""
    club_str = f"{t('swimmer_info_club', lang)}: {club}" if club else ""
    st.markdown(f"## 🏊 {selected_name}")
    if year_str or club_str:
        st.caption("  ·  ".join(filter(None, [year_str, club_str])))

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
    disciplines  = sorted(swimmer_results["discipline"].dropna().unique().tolist(),
                          key=_disc_sort_key)
    competitions = sorted(swimmer_results["event_name"].dropna().unique().tolist())

    col1, col2, col3 = st.columns(3)
    with col1:
        sel_disc = st.selectbox(
            t("filter_discipline", lang),
            [t("all_disciplines", lang)] + disciplines,
            key="sw_disc",
        )
    with col2:
        sel_comp = st.selectbox(
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
                min_value=min_d, max_value=max_d,
                key="sw_range",
            )
        else:
            sel_range = None

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
    n_pb   = int(swimmer_results["is_pb"].sum())
    c1, c2, c3 = st.columns(3)
    c1.metric(t("disciplines_label",    lang), n_disc)
    c2.metric(t("competitions_label",   lang), n_comp)
    c3.metric(t("personal_bests_label", lang), n_pb)

    st.divider()

    # ══════════════════════════════════════════════════════════════════════
    # CHART 2 — Personal Bests horizontal bar (always shown, not filtered)
    # ══════════════════════════════════════════════════════════════════════
    pb_data = (
        swimmer_results.dropna(subset=["time_sec"])
        .groupby("discipline", as_index=False)["time_sec"].min()
        .rename(columns={"time_sec": "pb_sec"})
    )
    pb_data = pb_data.sort_values("pb_sec",
                                   key=lambda s: [_disc_sort_key(d) for d in pb_data["discipline"]],
                                   ascending=True)
    pb_data["time_label"] = pb_data["pb_sec"].apply(_fmt_time)

    fig_pb = go.Figure(go.Bar(
        x            = pb_data["pb_sec"],
        y            = pb_data["discipline"],
        orientation  = "h",
        text         = pb_data["time_label"],
        textposition = "outside",
        marker_color = "#3b82d4",
        hovertemplate = "%{y}: %{text}<extra></extra>",
    ))
    fig_pb.update_layout(
        title       = "Bestzeiten" if lang == "de" else "Personal Bests",
        xaxis       = dict(showticklabels=False, showgrid=False, zeroline=False),
        yaxis       = dict(autorange="reversed"),
        height      = max(160, len(pb_data) * 38 + 60),
        margin      = dict(l=160, r=80, t=40, b=10),
        plot_bgcolor= "#f7f8fa",
    )
    st.plotly_chart(fig_pb, use_container_width=True)

    st.divider()

    # ══════════════════════════════════════════════════════════════════════
    # CHART 1 — Progress over time, one tab per discipline
    # ══════════════════════════════════════════════════════════════════════
    view_disciplines = sorted(view["discipline"].dropna().unique().tolist(),
                              key=_disc_sort_key)
    if not view_disciplines:
        st.info(t("no_results", lang))
        return

    st.markdown(f"#### {t('chart_title', lang)}")
    tabs = st.tabs(view_disciplines)

    for tab, disc in zip(tabs, view_disciplines):
        with tab:
            disc_data = (
                view[view["discipline"] == disc]
                .dropna(subset=["date_parsed", "time_sec"])
                .sort_values("date_parsed")
                .copy()
            )
            if disc_data.empty:
                st.info(t("no_results", lang))
                continue

            disc_data["time_fmt"]   = disc_data["time_sec"].apply(_fmt_time)
            disc_data["hover_text"] = disc_data.apply(
                lambda r: f"<b>{r['time_fmt']}</b><br>{r.get('event_name','')}<br>{r.get('date','')}",
                axis=1
            )

            pb_sec  = disc_data["time_sec"].min()
            pb_row  = disc_data.loc[disc_data["time_sec"].idxmin()]

            fig = go.Figure()

            # ── Trend line (linear regression) ────────────────────────────
            if len(disc_data) >= 3:
                x_num = (disc_data["date_parsed"] - disc_data["date_parsed"].min()).dt.days.values
                y_num = disc_data["time_sec"].values
                coef  = np.polyfit(x_num, y_num, 1)
                y_fit = np.polyval(coef, x_num)
                improving = coef[0] < 0   # negative slope = getting faster
                trend_col = "#22c55e" if improving else "#94a3b8"
                fig.add_trace(go.Scatter(
                    x         = disc_data["date_parsed"],
                    y         = y_fit,
                    mode      = "lines",
                    name      = "Trend" if lang == "en" else "Trend",
                    line      = dict(color=trend_col, width=1.5, dash="dot"),
                    hoverinfo = "skip",
                ))

            # ── PB horizontal reference line ──────────────────────────────
            fig.add_hline(
                y           = pb_sec,
                line_dash   = "dash",
                line_color  = "#f59e0b",
                line_width  = 1,
                annotation_text = f"PB {_fmt_time(pb_sec)}",
                annotation_position = "right",
                annotation_font_color = "#f59e0b",
            )

            # ── Main scatter + line ───────────────────────────────────────
            fig.add_trace(go.Scatter(
                x            = disc_data["date_parsed"],
                y            = disc_data["time_sec"],
                mode         = "lines+markers",
                name         = disc,
                line         = dict(color="#3b82d4", width=2),
                marker       = dict(size=9, color="#3b82d4"),
                text         = disc_data["hover_text"],
                hovertemplate= "%{text}<extra></extra>",
            ))

            # ── PB marker (gold star) ─────────────────────────────────────
            fig.add_trace(go.Scatter(
                x          = [pb_row["date_parsed"]],
                y          = [pb_row["time_sec"]],
                mode       = "markers",
                name       = "PB",
                marker     = dict(symbol="star", size=16, color="#f59e0b",
                                  line=dict(color="#92400e", width=1)),
                text       = [f"<b>🏅 PB: {pb_row['time_fmt']}</b>"],
                hovertemplate = "%{text}<extra></extra>",
            ))

            # ── Y axis: inverted (lower = faster = higher on chart) ───────
            # Tick labels show formatted times, not raw seconds
            y_min = disc_data["time_sec"].min()
            y_max = disc_data["time_sec"].max()
            padding = max((y_max - y_min) * 0.15, 0.5)
            tick_vals = np.linspace(y_min - padding, y_max + padding, 6)
            tick_text = [_fmt_time(v) for v in tick_vals]

            fig.update_yaxes(
                autorange   = "reversed",
                tickvals    = tick_vals,
                ticktext    = tick_text,
                gridcolor   = "#e5e7eb",
                title_text  = t("col_time", lang),
            )
            fig.update_xaxes(
                tickformat  = "%d.%m.%y",
                gridcolor   = "#e5e7eb",
            )
            fig.update_layout(
                height       = 340,
                showlegend   = False,
                plot_bgcolor = "#ffffff",
                paper_bgcolor= "#ffffff",
                margin       = dict(l=20, r=80, t=20, b=30),
            )
            st.plotly_chart(fig, use_container_width=True)

            # ── Results table ──────────────────────────────────────────────
            table = disc_data[["date", "event_name", "location", "time_fmt", "is_pb"]].copy()
            table["time_fmt"] = table.apply(
                lambda r: r["time_fmt"] + " 🏅" if r["is_pb"] else r["time_fmt"], axis=1
            )
            table = table.drop(columns=["is_pb"])
            table.columns = [
                t("col_date", lang), t("col_competition", lang),
                t("col_location", lang), t("col_time", lang),
            ]
            st.dataframe(table, use_container_width=True, hide_index=True)
