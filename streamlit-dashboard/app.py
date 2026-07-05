"""
app.py
======
Main Streamlit entry point.

Layout:
  • Top bar: app title + DE/EN language toggle + last scraper run timestamp
  • Sidebar navigation with two sections
  • View router dispatches to the four view modules
"""

import streamlit as st

st.set_page_config(
    page_title="SU MöDLING Schwimmergebnisse",
    page_icon="🏊",
    layout="wide",
    initial_sidebar_state="expanded",
)

from data import get_last_run_label
from i18n import t
import views.swimmer       as view_swimmer
import views.team_overview as view_team
import views.leaderboard   as view_leaderboard
import views.recent        as view_recent


# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------
if "lang"         not in st.session_state: st.session_state["lang"]         = "de"
if "active_view"  not in st.session_state: st.session_state["active_view"]  = None


def lang() -> str:
    return st.session_state["lang"]


# ---------------------------------------------------------------------------
# Top bar
# ---------------------------------------------------------------------------
top_left, top_right = st.columns([5, 1])

with top_left:
    st.markdown(f"## 🏊 {t('app_title', lang())}")
    st.caption(f"{t('last_run', lang())}: {get_last_run_label()}")

with top_right:
    de_active = "**DE**" if lang() == "de" else "DE"
    en_active = "**EN**" if lang() == "en" else "EN"
    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        if st.button(de_active, key="btn_de", use_container_width=True):
            st.session_state["lang"] = "de"
            st.rerun()
    with btn_col2:
        if st.button(en_active, key="btn_en", use_container_width=True):
            st.session_state["lang"] = "en"
            st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown(f"### {t('nav_individual', lang())}")

    if st.button(
        t("nav_swimmer", lang()),
        key="nav_swimmer",
        use_container_width=True,
        type="primary" if st.session_state["active_view"] == "swimmer" else "secondary",
    ):
        st.session_state["active_view"] = "swimmer"
        st.rerun()

    st.markdown(f"### {t('nav_team', lang())}")

    for view_key, nav_key in [
        ("overview",    "nav_overview"),
        ("leaderboard", "nav_leaderboard"),
        ("recent",      "nav_recent"),
    ]:
        is_active = st.session_state["active_view"] == view_key
        if st.button(
            t(nav_key, lang()),
            key=f"nav_{view_key}",
            use_container_width=True,
            type="primary" if is_active else "secondary",
        ):
            st.session_state["active_view"] = view_key
            st.rerun()

# Set default view
if st.session_state["active_view"] is None:
    st.session_state["active_view"] = "swimmer"

# ---------------------------------------------------------------------------
# View routing
# ---------------------------------------------------------------------------
active = st.session_state["active_view"]

if active == "swimmer":
    view_swimmer.render(lang())
elif active == "overview":
    view_team.render(lang())
elif active == "leaderboard":
    view_leaderboard.render(lang())
elif active == "recent":
    view_recent.render(lang())
