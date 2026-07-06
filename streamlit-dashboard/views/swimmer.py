"""
views/swimmer.py
================
View 1 — Schwimmer suchen / Find Swimmer

Sections
--------
1. Search + swimmer header (name, birth year, club, age)
2. Highlight cards  — PB count, competitions, disciplines, best meet
3. Personal Bests   — horizontal bar with improvement delta vs first race
4. Recent form      — last 3 results per discipline with trend arrow
5. Progress chart   — scatter + line, inverted Y, PB line, trend line (per tab)
6. Results table    — per-discipline detail table
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
        m = int(sec // 60)
        s = sec - m * 60
        return f"{m}:{s:05.2f}"
    return f"{sec:.2f}"


def _fmt_delta(delta: float) -> str:
    """Format a time improvement (negative = faster) as −X.xx s."""
    if pd.isna(delta):
        return ""
    sign = "−" if delta < 0 else "+"
    return f"{sign}{abs(delta):.2f}s"


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


def _age_group_label(birth_year, lang: str) -> str:
    """Return a rough age-group label based on birth year."""
    if pd.isna(birth_year):
        return ""
    try:
        age = pd.Timestamp.now().year - int(birth_year)
    except Exception:
        return ""
    if age <= 10:
        return t("age_group_mini", lang)
    if age <= 12:
        return t("age_group_youth_a", lang)
    if age <= 14:
        return t("age_group_youth_b", lang)
    if age <= 17:
        return t("age_group_junior", lang)
    return t("age_group_adult", lang)


def _trend_arrow(first_sec: float, last_sec: float) -> str:
    """Return ↑ (faster), ↓ (slower) or → (same) comparing two times."""
    if pd.isna(first_sec) or pd.isna(last_sec):
        return "→"
    diff = last_sec - first_sec
    if diff < -0.1:
        return "↑"
    if diff > 0.1:
        return "↓"
    return "→"


def _recent_form_color(arrow: str) -> str:
    return {"↑": "#22c55e", "↓": "#ef4444", "→": "#94a3b8"}.get(arrow, "#94a3b8")


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
    age_label  = _age_group_label(birth_year, lang)
    year_str   = f"{t('swimmer_info_year', lang)}: {int(birth_year)}" if pd.notna(birth_year) and birth_year else ""
    club_str   = f"{t('swimmer_info_club', lang)}: {club}" if club else ""
    group_str  = age_label if age_label else ""

    st.markdown(f"## 🏊 {selected_name}")
    caption_parts = [p for p in [year_str, group_str, club_str] if p]
    if caption_parts:
        st.caption("  ·  ".join(caption_parts))

    all_results = load_results()
    if all_results.empty:
        st.info(t("no_results", lang))
        return

    swimmer_results = all_results[all_results["swimmer_id"] == swimmer_id].copy()
    if swimmer_results.empty:
        st.info(t("no_results", lang))
        return

    swimmer_results = compute_personal_bests(swimmer_results)

    # ── Pre-compute stats used in multiple sections ─────────────────────────
    n_disc    = swimmer_results["discipline"].nunique()
    n_comp    = swimmer_results["event_name"].nunique()
    n_pb      = int(swimmer_results["is_pb"].sum())

    # Best meet = competition where swimmer achieved the most PBs
    pb_rows = swimmer_results[swimmer_results["is_pb"] == True]
    if not pb_rows.empty:
        best_meet_series = pb_rows.groupby("event_name").size()
        best_meet_name   = best_meet_series.idxmax()
        best_meet_count  = int(best_meet_series.max())
    else:
        best_meet_name  = "—"
        best_meet_count = 0

    # Overall improvement: sum of (first_time − pb_time) across all disciplines
    total_improvement = 0.0
    per_disc_delta = {}
    for disc, grp in swimmer_results.dropna(subset=["time_sec"]).groupby("discipline"):
        grp_sorted = grp.sort_values("date_parsed")
        first_sec  = grp_sorted.iloc[0]["time_sec"]
        pb_sec_val = grp_sorted["time_sec"].min()
        delta      = pb_sec_val - first_sec   # negative = improvement
        per_disc_delta[disc] = delta
        total_improvement += delta

    # ── Highlight cards ─────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(t("personal_bests_label", lang), n_pb)
    c2.metric(t("competitions_label",   lang), n_comp)
    c3.metric(t("disciplines_label",    lang), n_disc)

    with c4:
        st.metric(
            t("best_meet_label", lang),
            best_meet_name if best_meet_name != "—" else "—",
            delta=f"{best_meet_count} PB{'s' if best_meet_count != 1 else ''}" if best_meet_count > 0 else None,
            delta_color="normal",
        )

    # ── Overall improvement callout ────────────────────────────────────────
    if total_improvement < -0.5 and n_disc > 0:
        avg_improvement = total_improvement / n_disc
        st.success(
            f"📈 {t('improvement_callout', lang).format(avg=_fmt_delta(avg_improvement))}",
            icon=None,
        )

    st.divider()

    # ══════════════════════════════════════════════════════════════════════
    # SECTION: Personal Bests + improvement delta
    # ══════════════════════════════════════════════════════════════════════
    pb_data = (
        swimmer_results.dropna(subset=["time_sec"])
        .groupby("discipline", as_index=False)["time_sec"].min()
        .rename(columns={"time_sec": "pb_sec"})
    )
    pb_data = pb_data.sort_values(
        "pb_sec",
        key=lambda s: [_disc_sort_key(d) for d in pb_data["discipline"]],
        ascending=True,
    )
    pb_data["time_label"] = pb_data["pb_sec"].apply(_fmt_time)
    pb_data["delta"]      = pb_data["discipline"].map(per_disc_delta)
    pb_data["delta_label"] = pb_data["delta"].apply(
        lambda d: _fmt_delta(d) if not pd.isna(d) and d < -0.05 else ""
    )
    pb_data["bar_color"]   = pb_data["delta"].apply(
        lambda d: "#22c55e" if (not pd.isna(d) and d < -0.5) else "#3b82d4"
    )

    fig_pb = go.Figure(go.Bar(
        x             = pb_data["pb_sec"],
        y             = pb_data["discipline"],
        orientation   = "h",
        text          = pb_data["time_label"],
        textposition  = "outside",
        marker_color  = pb_data["bar_color"].tolist(),
        hovertemplate = (
            "<b>%{y}</b><br>"
            + t("col_time", lang) + ": %{text}<br>"
            + t("improvement_label", lang) + ": %{customdata}<extra></extra>"
        ),
        customdata    = pb_data["delta_label"].tolist(),
    ))
    fig_pb.update_layout(
        title        = t("pb_chart_title", lang),
        xaxis        = dict(showticklabels=False, showgrid=False, zeroline=False),
        yaxis        = dict(autorange="reversed"),
        height       = max(160, len(pb_data) * 42 + 60),
        margin       = dict(l=160, r=100, t=40, b=10),
        plot_bgcolor = "#f7f8fa",
    )
    st.plotly_chart(fig_pb, use_container_width=True)

    # ── Legend note for green bars ──────────────────────────────────────────
    if any(pb_data["bar_color"] == "#22c55e"):
        st.caption(f"🟢 {t('pb_green_legend', lang)}")

    st.divider()

    # ══════════════════════════════════════════════════════════════════════
    # SECTION: Recent form — last 3 results vs PB per discipline
    # ══════════════════════════════════════════════════════════════════════
    st.markdown(f"#### {t('recent_form_title', lang)}")

    disciplines_sorted = sorted(
        swimmer_results["discipline"].dropna().unique().tolist(),
        key=_disc_sort_key,
    )

    form_cols = st.columns(min(len(disciplines_sorted), 4))
    shown = 0
    for disc in disciplines_sorted:
        if shown >= 8:
            break
        grp = (
            swimmer_results[swimmer_results["discipline"] == disc]
            .dropna(subset=["date_parsed", "time_sec"])
            .sort_values("date_parsed")
        )
        if len(grp) < 1:
            continue

        pb_val    = grp["time_sec"].min()
        last3     = grp.tail(3)
        last_time = grp.iloc[-1]["time_sec"]
        first_time = grp.iloc[0]["time_sec"]
        arrow     = _trend_arrow(first_time, last_time)
        arrow_col = _recent_form_color(arrow)
        col_idx   = shown % 4

        with form_cols[col_idx]:
            st.markdown(
                f"""
<div style="background:#f7f8fa;border:1px solid #e5e7eb;border-radius:8px;padding:12px 14px;margin-bottom:8px">
  <div style="font-size:12px;color:#57606a;font-weight:600;text-transform:uppercase;letter-spacing:.04em">{disc}</div>
  <div style="font-size:22px;font-weight:700;color:#1f2328;line-height:1.2">{_fmt_time(pb_val)}</div>
  <div style="font-size:11px;color:#57606a;margin-bottom:6px">PB</div>
  <div style="font-size:18px;font-weight:600;color:{arrow_col}">{arrow} {_fmt_time(last_time)}</div>
  <div style="font-size:11px;color:#57606a">{t('recent_last', lang)}</div>
  <div style="margin-top:6px;font-size:11px;color:#57606a">
    {'  ·  '.join([_fmt_time(r['time_sec']) for _, r in last3.iterrows()])}
  </div>
</div>
""",
                unsafe_allow_html=True,
            )
        shown += 1

    st.divider()

    # ══════════════════════════════════════════════════════════════════════
    # SECTION: Filters (apply to progress chart + table only)
    # ══════════════════════════════════════════════════════════════════════
    competitions = sorted(swimmer_results["event_name"].dropna().unique().tolist())

    col1, col2, col3 = st.columns(3)
    with col1:
        sel_disc = st.selectbox(
            t("filter_discipline", lang),
            [t("all_disciplines", lang)] + disciplines_sorted,
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

    # ══════════════════════════════════════════════════════════════════════
    # SECTION: Progress charts — one tab per discipline
    # ══════════════════════════════════════════════════════════════════════
    view_disciplines = sorted(view["discipline"].dropna().unique().tolist(), key=_disc_sort_key)
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
                axis=1,
            )

            pb_sec  = disc_data["time_sec"].min()
            pb_row  = disc_data.loc[disc_data["time_sec"].idxmin()]

            # Recent form caption above chart
            if len(disc_data) >= 2:
                first_s = disc_data.iloc[0]["time_sec"]
                last_s  = disc_data.iloc[-1]["time_sec"]
                arrow   = _trend_arrow(first_s, last_s)
                delta_s = last_s - first_s
                form_label = t("trend_improving", lang) if arrow == "↑" else (
                    t("trend_declining", lang) if arrow == "↓" else t("trend_stable", lang)
                )
                col_cap = _recent_form_color(arrow)
                st.markdown(
                    f'<span style="color:{col_cap};font-weight:600">{arrow} {form_label}</span>'
                    f' &nbsp;<span style="color:#57606a;font-size:13px">({_fmt_delta(delta_s)} {t("vs_first", lang)})</span>',
                    unsafe_allow_html=True,
                )

            fig = go.Figure()

            # ── Trend line (linear regression) ────────────────────────────
            if len(disc_data) >= 3:
                x_num = (disc_data["date_parsed"] - disc_data["date_parsed"].min()).dt.days.values
                y_num = disc_data["time_sec"].values
                coef  = np.polyfit(x_num, y_num, 1)
                y_fit = np.polyval(coef, x_num)
                improving = coef[0] < 0
                trend_col = "#22c55e" if improving else "#94a3b8"
                fig.add_trace(go.Scatter(
                    x         = disc_data["date_parsed"],
                    y         = y_fit,
                    mode      = "lines",
                    name      = "Trend",
                    line      = dict(color=trend_col, width=1.5, dash="dot"),
                    hoverinfo = "skip",
                ))

            # ── PB horizontal reference line ──────────────────────────────
            fig.add_hline(
                y                    = pb_sec,
                line_dash            = "dash",
                line_color           = "#f59e0b",
                line_width           = 1,
                annotation_text      = f"PB {_fmt_time(pb_sec)}",
                annotation_position  = "right",
                annotation_font_color= "#f59e0b",
            )

            # ── Main scatter + line ───────────────────────────────────────
            fig.add_trace(go.Scatter(
                x             = disc_data["date_parsed"],
                y             = disc_data["time_sec"],
                mode          = "lines+markers",
                name          = disc,
                line          = dict(color="#3b82d4", width=2),
                marker        = dict(size=9, color="#3b82d4"),
                text          = disc_data["hover_text"],
                hovertemplate = "%{text}<extra></extra>",
            ))

            # ── PB marker (gold star) ─────────────────────────────────────
            fig.add_trace(go.Scatter(
                x             = [pb_row["date_parsed"]],
                y             = [pb_row["time_sec"]],
                mode          = "markers",
                name          = "PB",
                marker        = dict(symbol="star", size=16, color="#f59e0b",
                                     line=dict(color="#92400e", width=1)),
                text          = [f"<b>🏅 PB: {pb_row['time_fmt']}</b>"],
                hovertemplate = "%{text}<extra></extra>",
            ))

            # ── Y axis: inverted (lower = faster = higher on chart) ───────
            y_min   = disc_data["time_sec"].min()
            y_max   = disc_data["time_sec"].max()
            padding = max((y_max - y_min) * 0.15, 0.5)
            tick_vals = np.linspace(y_min - padding, y_max + padding, 6)
            tick_text = [_fmt_time(v) for v in tick_vals]

            fig.update_yaxes(
                autorange  = "reversed",
                tickvals   = tick_vals,
                ticktext   = tick_text,
                gridcolor  = "#e5e7eb",
                title_text = t("col_time", lang),
            )
            fig.update_xaxes(
                tickformat = "%d.%m.%y",
                gridcolor  = "#e5e7eb",
            )
            fig.update_layout(
                height        = 340,
                showlegend    = False,
                plot_bgcolor  = "#ffffff",
                paper_bgcolor = "#ffffff",
                margin        = dict(l=20, r=80, t=20, b=30),
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
