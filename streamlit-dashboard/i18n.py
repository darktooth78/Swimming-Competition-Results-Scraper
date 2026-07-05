"""
i18n.py
=======
All UI strings in German (default) and English.
Add new keys to both 'de' and 'en' dicts.
"""

STRINGS = {
    "de": {
        # App title & nav
        "app_title":            "SU MöDLING — Schwimmergebnisse",
        "last_run":             "Letzte Aktualisierung",
        "nav_individual":       "Individuelle Ergebnisse",
        "nav_swimmer":          "Schwimmer suchen",
        "nav_team":             "Mannschaft",
        "nav_overview":         "Mannschaftsübersicht",
        "nav_leaderboard":      "Bestzeiten",
        "nav_recent":           "Letzte Ergebnisse",

        # Swimmer search (View 1)
        "hero_title":           "Ergebnisse deines Kindes finden",
        "search_placeholder":   "z.B. Vincent Blobner",
        "search_button":        "Suchen",
        "select_swimmer":       "Schwimmer auswählen",
        "no_results":           "Keine Ergebnisse gefunden.",
        "swimmer_info_year":    "Jahrgang",
        "swimmer_info_club":    "Verein",
        "disciplines_label":    "Disziplinen",
        "competitions_label":   "Wettkämpfe",
        "personal_bests_label": "Bestzeiten",
        "chart_title":          "Zeitverlauf",
        "filter_discipline":    "Disziplin",
        "filter_competition":   "Wettkampf",
        "filter_period":        "Zeitraum",
        "filter_location":      "Ort",
        "filter_birth_year":    "Jahrgang",
        "filter_name":          "Name",
        "apply":                "Anwenden",
        "reset":                "Zurücksetzen",
        "col_date":             "Datum",
        "col_competition":      "Wettkampf",
        "col_location":         "Ort",
        "col_time":             "Zeit",
        "col_name":             "Name",
        "col_year":             "Jg.",
        "col_best_time":        "Bestzeit",
        "col_rank":             "#",
        "pb_badge":             "🏅",
        "all_disciplines":      "Alle Disziplinen",
        "all_competitions":     "Alle Wettkämpfe",
        "all_years":            "Alle Jahrgänge",
        "view_toggle_cards":    "Karten",
        "view_toggle_table":    "Tabelle",
        "no_swimmer_selected":  "Bitte Schwimmer suchen und auswählen.",
        "recent_scraper_run":   "🕐 Letzte Scraper-Ausführung",
        "unknown":              "Unbekannt",
    },
    "en": {
        # App title & nav
        "app_title":            "SU MöDLING — Swimming Results",
        "last_run":             "Last updated",
        "nav_individual":       "Individual Results",
        "nav_swimmer":          "Find Swimmer",
        "nav_team":             "Team",
        "nav_overview":         "Team Overview",
        "nav_leaderboard":      "Personal Bests",
        "nav_recent":           "Recent Results",

        # Swimmer search (View 1)
        "hero_title":           "Find your child's results",
        "search_placeholder":   "e.g. Vincent Blobner",
        "search_button":        "Search",
        "select_swimmer":       "Select swimmer",
        "no_results":           "No results found.",
        "swimmer_info_year":    "Born",
        "swimmer_info_club":    "Club",
        "disciplines_label":    "Disciplines",
        "competitions_label":   "Competitions",
        "personal_bests_label": "Personal Bests",
        "chart_title":          "Progress",
        "filter_discipline":    "Discipline",
        "filter_competition":   "Competition",
        "filter_period":        "Period",
        "filter_location":      "Location",
        "filter_birth_year":    "Birth year",
        "filter_name":          "Name",
        "apply":                "Apply",
        "reset":                "Reset",
        "col_date":             "Date",
        "col_competition":      "Competition",
        "col_location":         "Location",
        "col_time":             "Time",
        "col_name":             "Name",
        "col_year":             "Year",
        "col_best_time":        "Best Time",
        "col_rank":             "#",
        "pb_badge":             "🏅",
        "all_disciplines":      "All disciplines",
        "all_competitions":     "All competitions",
        "all_years":            "All years",
        "view_toggle_cards":    "Cards",
        "view_toggle_table":    "Table",
        "no_swimmer_selected":  "Please search for a swimmer and select one.",
        "recent_scraper_run":   "🕐 Last scraper run",
        "unknown":              "Unknown",
    }
}


def t(key: str, lang: str) -> str:
    """Return the translated string for key in lang ('de' or 'en')."""
    return STRINGS.get(lang, STRINGS["de"]).get(key, key)
