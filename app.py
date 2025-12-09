# app.py
import os
import time
from datetime import datetime, timedelta
from typing import List
import requests
import pandas as pd
import streamlit as st

# ---------------- CONFIG ----------------
YT_SEARCH = "https://www.googleapis.com/youtube/v3/search"
YT_VIDEOS = "https://www.googleapis.com/youtube/v3/videos"
CACHE_TTL_SECONDS = 24 * 60 * 60     # 24 hours (user requested)
SAFETY_MAX_IDS = 500                 # safety cap

# ---------------- HELPERS ----------------
def iso_after_days(days: int) -> str:
    return (datetime.utcnow() - timedelta(days=days)).isoformat("T") + "Z"

def chunk_list(lst: List[str], n: int):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

# ---------------- UI ----------------
st.set_page_config(layout="wide", page_title="YTBNICHES- Your Personalized data Extractor")
st.title("YTBNICHES- Your Personalized data Extractor")

# API key: prefer Streamlit secrets, then env var, then input
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

# Mode dropdown: default "Select"
mode = st.selectbox("Mode", ["Select", "Keyword search (last N days)", "Trending (region)"], index=0)

# Layout inputs
col1, col2, col3, col4 = st.columns([2,2,1,1])

# Region input: placeholder "#SELECT COUNTRY"
with col1:
    region = st.text_input("Region code (e.g. US, IN)", value="", placeholder="#SELECT COUNTRY")

# Days select (renamed) with default "Select" option
DAYS_OPTIONS = ["Select", 7, 10, 30, 90]
with col2:
    days_choice = st.selectbox("Days", DAYS_OPTIONS, index=0)

# Max results per keyword/trending (1 to 5)
with col3:
    max_results = st.slider("Max results per keyword / trending list", 1, 5, 2)

# Force refresh
with col4:
    force_refresh = st.checkbox("Force refresh (ignore cache)")

# Keywords input with placeholder "#TYPE YOUR KEYWORDS"
keywords_default = ""
keywords_input = st.text_input("Keywords", value=keywords_default, placeholder="#TYPE YOUR KEYWORDS")

# Minimum views
min_views = st.number_input("Minimum total views filter (0 to skip)", min_value=0, value=0, step=100)

# Note about cache
st.caption("Cache will save results for 24 hours. Keep keywords and max results small to save quota.")

# ---------------- Behaviour: enable/disable fields based on mode ----------------
# If mode is Trending, disable keywords and days (not relevant)
is_trending = (mode == "Trending (region)")
is_select_mode = (mode == "Select")

# Disable controls visually by re-rendering disabled widgets if needed.
# Streamlit doesn't allow toggling 'disabled' after creation easily, so we replicate disabled UI:
if is_trending:
    # show disabled Days and Keywords as non-editable text/info
    st.info("Trending mode selected: Keywords and Days are disabled because they are not used in Trending mode.")
    # indicate what region will be used
    # (region input remains editable because trending uses it)
else:
    # for keyword mode, ensure Days is chosen (not "Select")
    pass

# ---------------- CACHING WRAPPERS ----------------
@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def cached_search_ids(keyword: str, published_after: str, max_results:int, region:str, api_key:str):
    params = {
        "part":"snippet",
        "q": keyword,
        "type":"video",
        "publishedAfter": published_after,
        "maxResults": max_results,
        "order":"viewCount",
        "regionCode": region.upper(),
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

# Clear caches if user forces refresh
if force_refresh:
    cached_search_ids.clear()
    cached_video_stats.clear()

# ---------------- FETCH FUNCTIONS ----------------
def fetch_trending(region_code: str, max_r: int, api_key: str):
    params = {
        "part":"id,snippet,statistics,contentDetails",
        "chart":"mostPopular",
        "regionCode": region_code.upper(),
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

# ---------------- RUN on ENTER ----------------
enter_clicked = st.button("ENTER")

if enter_clicked:
    # Basic validation
    if is_select_mode:
        st.error("Select a mode from the Mode dropdown before pressing ENTER.")
    elif not region or region.strip() == "":
        st.error("Enter a region code (e.g. IN, US).")
    else:
        try:
            if is_trending:
                # Trending path (keywords/days ignored)
                with st.spinner("Fetching trending videos for region..."):
                    rows = fetch_trending(region, max_results, api_key)
            else:
                # Keyword mode: ensure user selected Days value
                if days_choice == "Select":
                    st.error("Choose Days (7/10/30/90) before ENTER.")
                    rows = []
                else:
                    keywords = [k.strip() for k in keywords_input.split(",") if k.strip()]
                    if not keywords:
                        st.error("Enter at least one keyword (comma separated).")
                        rows = []
                    else:
                        with st.spinner("Searching for keyword videos..."):
                            rows = fetch_keywords(keywords, int(days_choice), region, min(max_results, 25), api_key)
            # Show results
            if not rows:
                st.info("No results found for the chosen parameters.")
            else:
                df = pd.DataFrame(rows)
                df["publishedAt"] = pd.to_datetime(df["publishedAt"])
                if min_views > 0:
                    df = df[df["views"] >= int(min_views)]
                df = df.sort_values("views", ascending=False).reset_index(drop=True)
                st.write(f"Found {len(df)} videos. Showing top results (capped at 100 display).")
                st.dataframe(df[["title","channel","publishedAt","views","likes","duration","url"]].head(100))
                if not df.empty:
                    st.bar_chart(df.head(10).set_index("title")["views"])
                csv = df.to_csv(index=False).encode("utf-8")
                st.download_button("Download CSV", csv, file_name="yt_results.csv", mime="text/csv")
        except requests.HTTPError as e:
            st.error(f"API error: {e}")
        except Exception as e:
            st.error(f"Unexpected error: {e}")
