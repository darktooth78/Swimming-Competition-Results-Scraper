#!/usr/bin/env python3
"""
Scrapes all SUM (Schwimm Union Mödling, Club 6614) results from myresults.eu
for the period 01/01/2025 to 31/08/2026.
Outputs full results and medal-winners reports to CSV.
"""

import sys
import os
import re
import csv
import datetime
import urllib.request
import concurrent.futures
from typing import List, Dict, Any, Optional, Tuple

START_DATE = datetime.date(2025, 1, 1)
END_DATE = datetime.date(2026, 8, 31)
CLUB_ID = 6614
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def parse_date_str(d_str: str) -> Optional[datetime.date]:
    """Parse date from string like '23.-24.05.2026' or '04.05.2025'."""
    m = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})$', d_str.strip())
    if m:
        try:
            return datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None

def fetch_url(url: str, timeout: int = 12) -> Optional[str]:
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode('utf-8', errors='ignore')
        except Exception:
            pass
    return None

def scan_club_page(event_id: int) -> Tuple[int, List[Tuple[int, str]], Dict[str, str]]:
    """
    Returns (event_id, [(participant_id, name)], event_meta)
    event_meta has 'name', 'date', 'location', 'date_obj'
    """
    url = f"https://myresults.eu/de-AT/Meets/Recent/{event_id}/Club/{CLUB_ID}"
    html = fetch_url(url)
    if not html:
        return event_id, [], {}
    
    # Metadata
    meet_m = re.search(r'<p class="myresults_meetname2">([^<]+)</p>', html)
    if not meet_m:
        meet_m = re.search(r'<ul class="myresults_nav3a[^"]*"><p[^>]*>([^<]+)</p>', html)
    
    raw_meet = meet_m.group(1).strip() if meet_m else ""
    m_meta = re.match(r'^(.*?)\s*\((.*?)\)\s*-\s*(.*)$', raw_meet)
    if m_meta:
        e_name = m_meta.group(1).strip()
        e_date = m_meta.group(2).strip()
        e_loc = m_meta.group(3).strip()
    else:
        e_name = raw_meet
        e_date = ""
        e_loc = ""
    
    d_obj = parse_date_str(e_date)
    meta = {
        'name': e_name,
        'date': e_date,
        'location': e_loc,
        'date_obj': d_obj
    }
    
    # Check participants
    # Format: /Recent/{event_id}/Participant/(\d+)">([^<]+)<
    p_pattern = re.compile(rf'/Recent/{event_id}/Participant/(\d+)"[^>]*>([^<]+)<')
    p_matches = p_pattern.findall(html)
    unique_p = []
    seen = set()
    for pid_str, pname in p_matches:
        pid = int(pid_str)
        if pid not in seen:
            seen.add(pid)
            unique_p.append((pid, pname.strip()))
    
    return event_id, unique_p, meta

def parse_participant_page(event_id: int, pid: int, default_meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    url = f"https://myresults.eu/de-AT/Meets/Recent/{event_id}/Participant/{pid}"
    html = fetch_url(url)
    if not html:
        return []
    
    # Athlete Name
    name_m = re.search(r'<td class="myresults_personendetails_header"[^>]*>([^<]+)</td>', html)
    swimmer_name = name_m.group(1).strip() if name_m else ""
    
    # Event metadata (refine if needed)
    meet_m = re.search(r'<p class="myresults_meetname2">([^<]+)</p>', html)
    raw_meet = meet_m.group(1).strip() if meet_m else ""
    m_meta = re.match(r'^(.*?)\s*\((.*?)\)\s*-\s*(.*)$', raw_meet)
    if m_meta:
        e_name = m_meta.group(1).strip()
        e_date = m_meta.group(2).strip()
        e_loc = m_meta.group(3).strip()
    else:
        e_name = default_meta.get('name', '')
        e_date = default_meta.get('date', '')
        e_loc = default_meta.get('location', '')
    
    # Results section
    ergebnisse_idx = html.find('Ergebnisse</div>')
    if ergebnisse_idx == -1:
        # try case-insensitive
        m_erg = re.search(r'Ergebnisse\s*</div>', html, re.IGNORECASE)
        if m_erg:
            ergebnisse_idx = m_erg.start()
        else:
            return []
    
    results_part = html[ergebnisse_idx:]
    row_splits = re.split(r'(?=<div[^>]*class="row myresults_content_divtablerow\s+myresults_content_divtablerow_(?:odd|even))', results_part)
    
    records = []
    for chunk in row_splits[1:]:
        # Anchor with discipline
        anchor_m = re.search(r'<a[^>]*href="[^"]*Results/[^"]*"[^>]*>(.*?)<', chunk)
        if not anchor_m:
            continue
        disc = anchor_m.group(1).strip()
        # Clean tags if any
        disc = re.sub(r'<[^>]+>', '', disc).strip()
        if not disc or disc == "Das Unternehmen":
            continue
        
        # Place
        place_m = re.search(r'<span class="msecm-place[^"]*">([^<]+)</span>', chunk)
        place = place_m.group(1).strip() if place_m else ""
        
        # Altersklasse / Jahrgang
        ak_m = re.search(r'<span class="myresults_content_divtable_details_black">([^<]+)</span>', chunk)
        ak = ak_m.group(1).strip() if ak_m else ""
        
        # Time
        time_m = re.search(r'<div class="hidden-xs\s+col-sm-2\s+col-md-1\s+text-right\s+myresults_content_divtable_right">([^<]+)</div>', chunk)
        if not time_m:
            time_m = re.search(r'<div class="[^"]*myresults_content_divtable_right[^"]*">([^<]+)</div>', chunk)
        time_str = time_m.group(1).strip() if time_m else ""
        
        # Check medal status
        is_medal = False
        medal_type = ""
        if 'msecm-place-gold' in chunk or place == '1.':
            is_medal = True
            medal_type = "Gold"
        elif 'msecm-place-silver' in chunk or place == '2.':
            is_medal = True
            medal_type = "Silber"
        elif 'msecm-place-bronze' in chunk or place == '3.':
            is_medal = True
            medal_type = "Bronze"
        
        rec = {
            'event_id': event_id,
            'swimmer_id': pid,
            'event_date': e_date,
            'event_name': e_name,
            'event_location': e_loc,
            'swimmer_name': swimmer_name,
            'discipline': disc,
            'time': time_str,
            'place': place,
            'age_group': ak,
            'is_medal': is_medal,
            'medal_type': medal_type
        }
        records.append(rec)
        
    return records

def main():
    print("=" * 60)
    print("Starting SUM (Club 6614) Results Scraper")
    print(f"Target timeframe: {START_DATE.strftime('%d.%m.%Y')} - {END_DATE.strftime('%d.%m.%Y')}")
    print("=" * 60)
    
    # Scan event IDs
    event_range = list(range(2000, 2460))
    print(f"Scanning {len(event_range)} events for SUM participation...")
    
    valid_sum_events = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
        future_to_eid = {executor.submit(scan_club_page, eid): eid for eid in event_range}
        for future in concurrent.futures.as_completed(future_to_eid):
            eid, participants, meta = future.result()
            if participants and meta.get('date_obj'):
                d_obj = meta['date_obj']
                if START_DATE <= d_obj <= END_DATE:
                    valid_sum_events.append((eid, participants, meta))
            elif participants and not meta.get('date_obj'):
                # In case date could not be parsed immediately, keep for inspection
                valid_sum_events.append((eid, participants, meta))
                
    valid_sum_events.sort(key=lambda x: x[2].get('date_obj') or datetime.date(1970, 1, 1), reverse=True)
    print(f"\nFound {len(valid_sum_events)} relevant events with SUM participants in date range.")
    
    total_participants = sum(len(p) for _, p, _ in valid_sum_events)
    print(f"Total swimmer-event tasks to fetch: {total_participants}")
    
    # Prepare participant scraping tasks
    all_results = []
    tasks = []
    for eid, participants, meta in valid_sum_events:
        for pid, _ in participants:
            tasks.append((eid, pid, meta))
            
    print("\nFetching participant results...")
    done_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
        future_to_task = {executor.submit(parse_participant_page, eid, pid, meta): (eid, pid) for eid, pid, meta in tasks}
        for future in concurrent.futures.as_completed(future_to_task):
            res_list = future.result()
            all_results.extend(res_list)
            done_count += 1
            if done_count % 100 == 0 or done_count == len(tasks):
                print(f"Progress: {done_count}/{len(tasks)} participant pages processed ({len(all_results)} result rows extracted)...")
                
    print(f"\nFinished extracting {len(all_results)} individual results.")
    
    # Sort all results: Date descending, Event, Swimmer name, Discipline
    all_results.sort(key=lambda r: (r['event_date'], r['event_name'], r['swimmer_name'], r['discipline']))
    
    # Save Full CSV
    full_csv_path = "SUM_Ergebnisse_2025_2026_Alle.csv"
    with open(full_csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow([
            "event_id",
            "swimmer_id",
            "Veranstaltungsdatum",
            "Veranstaltung",
            "Veranstaltungsort",
            "Name Athlet:in",
            "Bewerb",
            "Zeit",
            "Platzierung",
            "Altersklasse"
        ])
        for r in all_results:
            writer.writerow([
                r['event_id'],
                r['swimmer_id'],
                r['event_date'],
                r['event_name'],
                r['event_location'],
                r['swimmer_name'],
                r['discipline'],
                r['time'],
                r['place'],
                r['age_group']
            ])
            
    print(f"Saved complete dataset to: {full_csv_path} ({len(all_results)} rows)")
    
    # Filter Medals (Platzierung 1., 2., 3. or is_medal)
    medal_results = [r for r in all_results if r['is_medal'] or r['place'] in ['1.', '2.', '3.']]
    medal_csv_path = "SUM_Medaillen_2025_2026.csv"
    with open(medal_csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow([
            "Veranstaltungsdatum",
            "Veranstaltung",
            "Veranstaltungsort",
            "Name Athlet:in",
            "Bewerb",
            "Zeit",
            "Platzierung",
            "Medaille",
            "Altersklasse"
        ])
        for r in medal_results:
            writer.writerow([
                r['event_date'],
                r['event_name'],
                r['event_location'],
                r['swimmer_name'],
                r['discipline'],
                r['time'],
                r['place'],
                r['medal_type'],
                r['age_group']
            ])
            
    print(f"Saved medal dataset to: {medal_csv_path} ({len(medal_results)} rows)")
    
    # Print summary statistics
    gold_count = sum(1 for r in medal_results if r['medal_type'] == 'Gold' or r['place'] == '1.')
    silver_count = sum(1 for r in medal_results if r['medal_type'] == 'Silber' or r['place'] == '2.')
    bronze_count = sum(1 for r in medal_results if r['medal_type'] == 'Bronze' or r['place'] == '3.')
    
    unique_athletes = len(set(r['swimmer_name'] for r in all_results if r['swimmer_name']))
    medal_athletes = len(set(r['swimmer_name'] for r in medal_results if r['swimmer_name']))
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Events analyzed:        {len(valid_sum_events)}")
    print(f"SUM Athletes:           {unique_athletes}")
    print(f"Total Results/Starts:   {len(all_results)}")
    print(f"Total Medals:           {len(medal_results)} (Gold: {gold_count}, Silber: {silver_count}, Bronze: {bronze_count})")
    print(f"Medal-winning Athletes: {medal_athletes}")
    print("=" * 60)

if __name__ == "__main__":
    main()
