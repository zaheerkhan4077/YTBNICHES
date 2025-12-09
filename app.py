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

# -------- COUNTRY LIST (ISO2 -> Name) --------
COUNTRIES = {
    "IN": "India", "US": "United States", "GB": "United Kingdom", "AU": "Australia", "CA": "Canada",
    "DE": "Germany", "FR": "France", "JP": "Japan", "KR": "South Korea", "BR": "Brazil",
    "RU": "Russia", "MX": "Mexico", "IT": "Italy", "ES": "Spain", "NL": "Netherlands",
    # (add more if you want; this is a usable subset)
}
# You can expand COUNTRIES as needed.

def iso_after_days(days: int) -> str:
    return (datetime.utcnow() - timedelta(days=days)).isoformat("T") + "Z"

def chunk_list(lst: List[str], n: int):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

def country_suggestions(query: str) -> List[Tuple[str,str]]:
    q = (query or "").strip().lower()
    out = []
    if not q:
        return out
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

# Layout columns
col1, col2, col3, col4 = st.columns([2,2,1,1])

# REGION: type-ahead input + suggestions selectbox
with col1:
    st.write("Region code (e.g. US, IN)")
    # If trending, inputs are disabled (user must select region before switching to Trending)
    region_query = st.text_input("Type country code or name", value="", placeholder="#SELECT COUNTRY", disabled=is_trending, key="region_query")
    suggestions = country_suggestions(region_query)
    if suggestions and not is_trending:
        options = ["-- choose --"] + [f"{c} - {n}" for c, n in suggestions]
        sel = st.selectbox("Suggestions", options, index=0, key="region_suggestions")
        if sel != "-- choose --":
            chosen_code = sel.split(" - ")[0]
            st.session_state["selected_region_code"] = chosen_code
    # show selected region code (readonly)
    sel_code = st.session_state.get("selected_region_code", "")
    st.text_input("Selected region code (used by app)", value=sel_code, disabled=True, key="selected_region_display")

# DAYS: renamed to Days; disabled for Trending
with col2:
    DAYS_OPTIONS = ["Select", 7, 10, 30, 90]
    days_choice = st.selectbox("Days", DAYS_OPTIONS, index=0, disabled=is_trending, key="days_select")

# MAX RESULTS (1-5)
with col3:
    max_results = st.slider("Max results per keyword / trending list", 1, 5, 2, key="max_results")

# FORCE REFRESH
with col4:
    force_refresh = st.checkbox("Force refresh (ignore cache)", key="force_refresh")

# KEYWORDS: disabled for Trending
keywords_input = st.text_input("Keywords", value="", placeholder="#TYPE YOUR KEYWORDS", disabled=is_trending, key="keywords_input")

min_views = st.number_input("Minimum total views filter (0 to skip)", min_value=0, value=0, step=100, key="min_views")
st.caption("Cache will save results for 24 hours. Keep keywords and max results small to save quota.")

# Inform user about disabled behavior
if is_trending:
    st.info("Trending mode selected. Keywords and Days are disabled. Use the 'Selected region code' above (choose it before switching to Trending).")

# -------- Cached API calls --------
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

# -------- Fetch functions --------
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
    # dedupe and cap
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
        # determine the region code to use
        selected_region = st.session_state.get("selected_region_code", "")
        # If user typed a two-letter code directly and didn't use suggestions, accept it (only if not trending-disabled)
        if not selected_region and region_query and len(region_query.strip()) == 2:
            selected_region = region_query.strip().upper()
        if not selected_region:
            st.error("No region selected. Use the suggestions box to choose a country (e.g., type 'IN' or 'India').")
        else:
            try:
                if is_trending:
                    with st.spinner("Fetching trending videos..."):
                        rows = fetch_trending(selected_region, max_results, api_key)
                else:
                    # read days value reliably
                    days_val = st.session_state.get("days_select", "Select")
                    # if session_state doesn't have it, fallback to widget variable
                    if days_val == "Select":
                        # try reading directly from selectbox key
                        days_val = st.session_state.get("days_select", "Select")
                    if days_val == "Select":
                        st.error("Choose Days (7/10/30/90) before ENTER.")
                        rows = []
                    else:
                        try:
                            days_int = int(days_val)
                        except Exception:
                            st.error("Invalid Days value.")
                            rows = []
                        else:
                            keywords = [k.strip() for k in keywords_input.split(",") if k.strip()]
                            if not keywords:
                                st.error("Enter at least one keyword.")
                                rows = []
                            else:
                                with st.spinner("Searching keywords..."):
                                    rows = fetch_keywords(keywords, days_int, selected_region, min(max_results, 25), api_key)

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
