# app.py
import os
import time
from datetime import datetime, timedelta
from typing import List
import requests
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

# Load local .env if present (useful for local testing)
load_dotenv()

# Constants
YT_SEARCH = "https://www.googleapis.com/youtube/v3/search"
YT_VIDEOS = "https://www.googleapis.com/youtube/v3/videos"
CACHE_TTL_SECONDS = 12 * 60 * 60  # 12 hours
SAFETY_MAX_IDS = 500  # safety cap to avoid huge requests

# Helpers
def iso_after_days(days: int) -> str:
    return (datetime.utcnow() - timedelta(days=days)).isoformat("T") + "Z"

def chunk_list(lst: List[str], n: int):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

# UI setup
st.set_page_config(layout="wide", page_title="YT Quick Explorer (quota-friendly)")
st.title("YT Quick Explorer — quota-friendly")

# API key sources: Streamlit secrets > env var > input field
api_key = None
try:
    api_key = st.secrets.get("YT_API_KEY")  # Streamlit Cloud secrets
except Exception:
    api_key = None

if not api_key:
    api_key = os.environ.get("YT_API_KEY")

# If still no key, let user paste it (masked)
if not api_key:
    key_input = st.text_input("YouTube API key (or set as Streamlit secret YT_API_KEY)", type="password")
    if key_input:
        api_key = key_input.strip()

if not api_key:
    st.warning("Provide an API key via Streamlit secrets, environment variable YT_API_KEY, or paste it above.")
    st.stop()

# Controls
mode = st.selectbox("Mode", ["Trending (region)", "Keyword search (last N days)"])
col1, col2, col3, col4 = st.columns([2,2,1,1])
with col1:
    region = st.text_input("Region code (ISO, e.g. US, IN)", "US")
with col2:
    days = st.selectbox("Days window (keyword mode only)", [7,10,30,90], index=1)
with col3:
    max_results = st.slider("Max results per keyword / trending list", 5, 50, 20)
with col4:
    force_refresh = st.checkbox("Force refresh (ignore cache)", value=False)

keywords_default = "science explained, how it works, physics explained"
keywords_input = st.text_input("Keywords (comma separated) — used in Keyword mode", keywords_default)
min_views = st.number_input("Minimum total views filter (0 to skip)", min_value=0, value=0, step=100)
st.markdown("Cache TTL = 12 hours. Keep keywords and max results small to save quota.")

# Cached functions
@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def cached_search_ids_for_keyword(keyword: str, published_after: str, max_results:int, region:str, api_key:str):
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
    items = r.json().get("items", [])
    return [it["id"]["videoId"] for it in items if it.get("id")]

@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def cached_get_videos_stats(ids: List[str], api_key: str):
    results = []
    for chunk in chunk_list(ids, 50):
        params = {"part":"snippet,statistics,contentDetails","id":",".join(chunk),"maxResults":len(chunk),"key":api_key}
        r = requests.get(YT_VIDEOS, params=params, timeout=20)
        r.raise_for_status()
        for it in r.json().get("items", []):
            stats = it.get("statistics", {})
            snip = it.get("snippet", {})
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
        time.sleep(0.2)
    return results

# Bypass cache if forced
if force_refresh:
    cached_search_ids_for_keyword.clear()
    cached_get_videos_stats.clear()

# Fetching logic
def fetch_trending(region_code: str, max_results: int, api_key: str):
    params = {"part":"id,snippet,statistics,contentDetails","chart":"mostPopular","regionCode":region_code.upper(),"maxResults":max_results,"key":api_key}
    r = requests.get(YT_VIDEOS, params=params, timeout=15)
    r.raise_for_status()
    items = r.json().get("items", [])
    ids = [it["id"] for it in items]
    return cached_get_videos_stats(ids, api_key)

def fetch_by_keywords(keywords: List[str], days: int, region: str, per_kw_max:int, api_key:str):
    published_after = iso_after_days(days)
    ids_ordered = []
    for kw in keywords:
        try:
            ids = cached_search_ids_for_keyword(kw, published_after, per_kw_max, region, api_key)
            ids_ordered.extend(ids)
        except requests.HTTPError as e:
            st.error(f"Search API error for '{kw}': {e}")
        except Exception as e:
            st.error(f"Search error for '{kw}': {e}")
    # dedupe while preserving order
    seen = set()
    unique_ids = []
    for vid in ids_ordered:
        if vid not in seen:
            seen.add(vid)
            unique_ids.append(vid)
    if not unique_ids:
        return []
    unique_ids = unique_ids[:SAFETY_MAX_IDS]
    return cached_get_videos_stats(unique_ids, api_key)

# Run on click
if st.button("Fetch"):
    with st.spinner("Fetching (quota-efficient)..."):
        all_rows = []
        try:
            if mode == "Trending (region)":
                all_rows = fetch_trending(region, max_results, api_key)
            else:
                keywords = [k.strip() for k in keywords_input.split(",") if k.strip()]
                if not keywords:
                    st.warning("Add at least one keyword.")
                    st.stop()
                per_kw_max = min(max_results, 25)
                all_rows = fetch_by_keywords(keywords, days, region, per_kw_max, api_key)
        except requests.HTTPError as e:
            st.error(f"API error: {e}")
            st.stop()
        except Exception as e:
            st.error(f"Unexpected error: {e}")
            st.stop()

        if not all_rows:
            st.info("No results returned.")
            st.stop()

        df = pd.DataFrame(all_rows)
        df['publishedAt'] = pd.to_datetime(df['publishedAt'])
        if min_views > 0:
            df = df[df['views'] >= int(min_views)]
        df = df.sort_values(by="views", ascending=False).reset_index(drop=True)

        st.write(f"Found {len(df)} videos. Showing top 100 by views.")
        st.dataframe(df.head(100)[["title","channel","publishedAt","views","likes","duration","url"]])

        if not df.empty:
            top10 = df.head(10).set_index("title")["views"]
            st.bar_chart(top10)

        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button("Download CSV", csv, file_name="yt_results.csv", mime="text/csv")
