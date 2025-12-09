# app.py
import os
import time
from datetime import datetime, timedelta
from typing import List, Tuple
import requests
import pandas as pd
import streamlit as st

# -------- CONFIG --------
YT_SEARCH = "https://www.googleapis.com/youtube/v3/search"
YT_VIDEOS = "https://www.googleapis.com/youtube/v3/videos"
CACHE_TTL_SECONDS = 24 * 60 * 60
SAFETY_MAX_IDS = 500

# -------- COUNTRIES (ISO -> Name) --------
COUNTRIES = {
    "IN": "India", "ID": "Indonesia", "IR": "Iran", "IE": "Ireland", "IS": "Iceland",
    "IT": "Italy", "IL": "Israel", "IQ": "Iraq", "US": "United States", "GB": "United Kingdom",
    "AU": "Australia", "CA": "Canada", "DE": "Germany", "FR": "France", "JP": "Japan",
    "KR": "South Korea", "BR": "Brazil", "RU": "Russia", "MX": "Mexico", "ES": "Spain",
    "NL": "Netherlands", "SE": "Sweden", "CH": "Switzerland", "SG": "Singapore", "PH": "Philippines",
    "PK": "Pakistan", "BD": "Bangladesh", "NG": "Nigeria", "EG": "Egypt", "ZA": "South Africa"
}

# -------- HELPERS --------
def iso_after_days(days: int) -> str:
    return (datetime.utcnow() - timedelta(days=days)).isoformat("T") + "Z"

def chunk_list(lst: List[str], n: int):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

def get_country_suggestions(q: str) -> List[Tuple[str,str]]:
    q = (q or "").strip().lower()
    if not q:
        return []
    out = []
    for code, name in COUNTRIES.items():
        if code.lower().startswith(q) or name.lower().startswith(q):
            out.append((code, name))
    out.sort(key=lambda x: (x[0], x[1]))
    return out

# -------- UI --------
st.set_page_config(layout="wide", page_title="YTBNICHES- Your Personalized data Extractor")
st.title("YTBNICHES- Your Personalized data Extractor")

# API key
api_key = None
try:
    api_key = st.secrets.get("YT_API_KEY")
except Exception:
    api_key = None
if not api_key:
    api_key = os.environ.get("YT_API_KEY")
if not api_key:
    key_input = st.text_input("YouTube API key (or set Streamlit secret YT_API_KEY)", type="password")
    if key_input:
        api_key = key_input.strip()
if not api_key:
    st.warning("Add your API key in Streamlit Secrets or paste it above.")
    st.stop()

# Mode
mode = st.selectbox("Mode", ["Select", "Keyword search (last N days)", "Trending (region)"], index=0)
is_trending = (mode == "Trending (region)")
is_select = (mode == "Select")

col1, col2, col3, col4 = st.columns([2,2,1,1])

# REGION: single input; suggestions will appear inline as clickable buttons
with col1:
    # keep the same key 'region_input' so session_state persists
    default_region_value = st.session_state.get("region_input", "")
    region_query = st.text_input("Type country code or name", value=default_region_value, placeholder="#SELECT COUNTRY", key="region_input")
    # show inline suggestion buttons after 1 character
    suggestions = get_country_suggestions(region_query) if (region_query and len(region_query.strip()) >= 1) else []
    if suggestions:
        # limit to first 10 suggestions to avoid huge button rows
        suggestions = suggestions[:10]
        # display suggestions as buttons in rows of up to 5
        per_row = 5
        for i in range(0, len(suggestions), per_row):
            row = suggestions[i:i+per_row]
            cols = st.columns(len(row))
            for cidx, (code, name) in enumerate(row):
                label = f"{code} - {name}"
                if cols[cidx].button(label):
                    # set the same input value to ISO code and rerun
                    st.session_state["region_input"] = code
                    st.experimental_rerun()

# DAYS (disabled when trending)
with col2:
    DAYS_OPTIONS = ["Select", 7, 10, 30, 90]
    days_choice = st.selectbox("Days", DAYS_OPTIONS, index=0, disabled=is_trending, key="days_select")

# MAX RESULTS (1-5)
with col3:
    max_results = st.slider("Max results per keyword / trending list", 1, 5, 2, key="max_results")

# FORCE REFRESH
with col4:
    force_refresh = st.checkbox("Force refresh (ignore cache)", key="force_refresh")

# KEYWORDS (disabled when trending)
keywords_input = st.text_input("Keywords", value="", placeholder="#TYPE YOUR KEYWORDS", disabled=is_trending, key="keywords_input")

min_views = st.number_input("Minimum total views filter (0 to skip)", min_value=0, value=0, step=100, key="min_views")
st.caption("Cache will save results for 24 hours. Keep keywords and max results small to save quota.")

if is_trending:
    st.info("Trending mode: Days and Keywords are disabled. Use Region input above to choose a country (type 1 character to get suggestions).")

# -------- CACHED API CALLS --------
@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def cached_search_ids(keyword: str, published_after: str, max_results:int, region:str, api_key:str):
    params = {
        "part":"snippet",
        "q": keyword,
        "type":"video",
        "publishedAfter": published_after,
        "maxResults": max_results,
        "order":"viewCount",
        "regionCode": region.upper() if region else "",
        "key": api_key
    }
    r = requests.get(YT_SEARCH, params=params, timeout=15)
    r.raise_for_status()
    return [it["id"]["videoId"] for it in r.json().get("items", [])]

@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def cached_video_stats(ids: List[str], api_key: str):
    results = []
    for chunk in chunk_list(ids, 50):
        params = {"part":"snippet,statistics,contentDetails","id":",".join(chunk),"maxResults":len(chunk),"key":api_key}
        r = requests.get(YT_VIDEOS, params=params, timeout=20)
        r.raise_for_status()
        for it in r.json().get("items", []):
            snip = it.get("snippet", {})
            stats = it.get("statistics", {})
            cd = it.get("contentDetails", {})
            results.append({
                "videoId": it["id"],
                "title": snip.get("title"),
                "channel": snip.get("channelTitle"),
                "publishedAt": snip.get("publishedAt"),
                "views": int(stats.get("viewCount", 0)),
                "likes": int(stats.get("likeCount", 0)) if stats.get("likeCount") else None,
                "duration": cd.get("duration"),
                "url": f"https://www.youtube.com/watch?v={it['id']}"
            })
        time.sleep(0.15)
    return results

if force_refresh:
    cached_search_ids.clear()
    cached_video_stats.clear()

# -------- FETCH FUNCTIONS --------
def fetch_trending(region_code: str, max_r: int, api_key: str):
    params = {
        "part":"id,snippet,statistics,contentDetails",
        "chart":"mostPopular",
        "regionCode": region_code.upper() if region_code else "",
        "maxResults": max_r,
        "key": api_key
    }
    r = requests.get(YT_VIDEOS, params=params, timeout=15)
    r.raise_for_status()
    items = r.json().get("items", [])
    ids = [it["id"] for it in items]
    if not ids:
        return []
    return cached_video_stats(ids, api_key)

def fetch_keywords(keywords: List[str], days: int, region: str, per_kw_max: int, api_key: str):
    published_after = iso_after_days(days)
    ordered_ids = []
    for kw in keywords:
        try:
            ids = cached_search_ids(kw, published_after, per_kw_max, region, api_key)
            ordered_ids.extend(ids)
        except Exception as e:
            st.error(f"Search error for '{kw}': {e}")
    # dedupe-preserve order and cap
    seen = set()
    unique_ids = []
    for vid in ordered_ids:
        if vid not in seen:
            seen.add(vid)
            unique_ids.append(vid)
    unique_ids = unique_ids[:SAFETY_MAX_IDS]
    if not unique_ids:
        return []
    return cached_video_stats(unique_ids, api_key)

# -------- ENTER button --------
if st.button("ENTER"):
    if is_select:
        st.error("Select a mode first.")
    else:
        region_val = st.session_state.get("region_input", "")
        if region_val and len(region_val.strip()) == 2:
            region_code = region_val.strip().upper()
        else:
            st.error("No valid region selected. Type 1 character and click a suggestion (example: type 'I' then click 'IN - India').")
            region_code = None

        if region_code:
            try:
                if is_trending:
                    with st.spinner("Fetching trending videos..."):
                        rows = fetch_trending(region_code, max_results, api_key)
                else:
                    days_val = st.session_state.get("days_select", "Select")
                    if days_val == "Select":
                        st.error("Choose Days (7/10/30/90) before ENTER.")
                        rows = []
                    else:
                        days_int = int(days_val)
                        keywords = [k.strip() for k in keywords_input.split(",") if k.strip()]
                        if not keywords:
                            st.error("Enter at least one keyword.")
                            rows = []
                        else:
                            with st.spinner("Searching keywords..."):
                                rows = fetch_keywords(keywords, days_int, region_code, min(max_results, 25), api_key)

                if not rows:
                    st.info("No results found.")
                else:
                    df = pd.DataFrame(rows)
                    df["publishedAt"] = pd.to_datetime(df["publishedAt"])
                    if min_views > 0:
                        df = df[df["views"] >= int(min_views)]
                    df = df.sort_values("views", ascending=False).reset_index(drop=True)
                    st.write(f"Found {len(df)} videos. Showing top results.")
                    st.dataframe(df[["title","channel","publishedAt","views","likes","duration","url"]].head(100))
                    if not df.empty:
                        st.bar_chart(df.head(10).set_index("title")["views"])
                    csv = df.to_csv(index=False).encode("utf-8")
                    st.download_button("Download CSV", csv, file_name="yt_results.csv", mime="text/csv")
            except requests.HTTPError as e:
                st.error(f"API error: {e}")
            except Exception as e:
                st.error(f"Unexpected error: {e}")
