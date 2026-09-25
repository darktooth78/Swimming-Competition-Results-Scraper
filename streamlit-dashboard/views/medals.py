"""
views/medals.py
===============
Medaillenspiegel — Medal Table view.

Displays KPI metrics, a filterable data table, and a CSV export button.
All UI text is routed through i18n.t() for DE/EN support.
"""

import io
import streamlit as st
import pandas as pd

from data import load_medals
from i18n import t


def render(lang: str) -> None:
    st.markdown(f"## 🏅 {t('medals_title', lang)}")

    df = load_medals()

    # ------------------------------------------------------------------
    # Empty-state guard
    # ------------------------------------------------------------------
    if df.empty:
        st.info(t("medals_empty", lang))
        return

    # Ensure date_parsed exists for period filtering
    if "date_parsed" not in df.columns:
        df["date_parsed"] = pd.NaT

    # ------------------------------------------------------------------
    # KPI row
    # ------------------------------------------------------------------
    gold_df   = df[df["medal"] == "Gold"]
    silver_df = df[df["medal"].isin(["Silber", "Silver"])]
    bronze_df = df[df["medal"] == "Bronze"]

    total_medals   = len(df)
    n_gold         = len(gold_df)
    n_silver       = len(silver_df)
    n_bronze       = len(bronze_df)
    n_athletes     = df["name"].nunique() if "name" in df.columns else df["swimmer_id"].nunique()

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric(t("medals_kpi_total",    lang), total_medals)
    k2.metric(t("medals_kpi_gold",     lang), n_gold)
    k3.metric(t("medals_kpi_silver",   lang), n_silver)
    k4.metric(t("medals_kpi_bronze",   lang), n_bronze)
    k5.metric(t("medals_kpi_athletes", lang), n_athletes)

    st.divider()

    # ------------------------------------------------------------------
    # Filters
    # ------------------------------------------------------------------
    with st.expander("🔍 Filter", expanded=True):
        f1, f2, f3 = st.columns(3)
        f4, f5, f6 = st.columns(3)

        # Name search
        name_options = sorted(
            df["name"].dropna().unique().tolist()
            if "name" in df.columns else []
        )
        sel_name = f1.multiselect(
            t("filter_name", lang),
            options=name_options,
            default=[],
            placeholder=t("filter_name", lang),
        )

        # Competition / event
        event_options = sorted(df["event_name"].dropna().unique().tolist()) if "event_name" in df.columns else []
        sel_event = f2.multiselect(
            t("filter_competition", lang),
            options=event_options,
            default=[],
        )

        # Age group
        ak_options = sorted(df["age_group"].dropna().replace("", pd.NA).dropna().unique().tolist()) if "age_group" in df.columns else []
        sel_ak = f3.multiselect(
            t("filter_age_group", lang),
            options=ak_options,
            default=[],
        )

        # Medal type
        medal_type_opts = [
            t("medal_gold",   lang),
            t("medal_silver", lang),
            t("medal_bronze", lang),
        ]
        sel_medal = f4.multiselect(
            t("filter_medal_type", lang),
            options=medal_type_opts,
            default=[],
        )

        # Date range
        valid_dates = df["date_parsed"].dropna()
        min_date = valid_dates.min().date() if not valid_dates.empty else None
        max_date = valid_dates.max().date() if not valid_dates.empty else None
        date_from = f5.date_input(t("filter_period", lang) + " (von)", value=min_date, min_value=min_date, max_value=max_date)
        date_to   = f6.date_input(t("filter_period", lang) + " (bis)", value=max_date, min_value=min_date, max_value=max_date)

    # ------------------------------------------------------------------
    # Apply filters
    # ------------------------------------------------------------------
    filtered = df.copy()

    if sel_name:
        filtered = filtered[filtered["name"].isin(sel_name)]
    if sel_event:
        filtered = filtered[filtered["event_name"].isin(sel_event)]
    if sel_ak:
        filtered = filtered[filtered["age_group"].isin(sel_ak)]
    if sel_medal:
        # Map display labels back to internal values
        raw_map = {
            t("medal_gold",   lang): ["Gold"],
            t("medal_silver", lang): ["Silber", "Silver"],
            t("medal_bronze", lang): ["Bronze"],
        }
        allowed_raw = []
        for label in sel_medal:
            allowed_raw.extend(raw_map.get(label, []))
        filtered = filtered[filtered["medal"].isin(allowed_raw)]
    if min_date and date_from:
        filtered = filtered[filtered["date_parsed"].isna() | (filtered["date_parsed"].dt.date >= date_from)]
    if max_date and date_to:
        filtered = filtered[filtered["date_parsed"].isna() | (filtered["date_parsed"].dt.date <= date_to)]

    # ------------------------------------------------------------------
    # Table
    # ------------------------------------------------------------------
    if filtered.empty:
        st.info(t("medals_empty", lang))
        return

    # Build display columns
    col_map = {
        "date":       t("col_date",       lang),
        "event_name": t("col_competition", lang),
        "location":   t("col_location",   lang),
        "name":       t("col_name",       lang),
        "discipline": t("col_discipline", lang),
        "time_str":   t("col_time",       lang),
        "place":      t("col_place",      lang),
        "medal":      t("col_medal",      lang),
        "age_group":  t("col_age_group",  lang),
    }
    # Keep only columns that actually exist
    present_cols = [c for c in col_map if c in filtered.columns]
    display = filtered[present_cols].rename(columns={c: col_map[c] for c in present_cols})

    # Sort: date descending, then name
    date_col = col_map.get("date", "date")
    if date_col in display.columns:
        display = display.sort_values(date_col, ascending=False, na_position="last")

    st.dataframe(display, use_container_width=True, hide_index=True)

    # ------------------------------------------------------------------
    # CSV export
    # ------------------------------------------------------------------
    csv_bytes = display.to_csv(index=False, sep=";", encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button(
        label=f"⬇️ {t('export_csv', lang)}",
        data=csv_bytes,
        file_name="SUM_Medaillenspiegel.csv",
        mime="text/csv",
    )
