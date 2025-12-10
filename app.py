# app.py
# ---- only full file provided so you can replace current app.py ----
import os
import time
from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Dict
import requests
import pandas as pd
import streamlit as st

# -------- CONFIG --------
YT_SEARCH = "https://www.googleapis.com/youtube/v3/search"
YT_VIDEOS = "https://www.googleapis.com/youtube/v3/videos"
YT_CHANNELS = "https://www.googleapis.com/youtube/v3/channels"
CACHE_TTL_SECONDS = 24 * 60 * 60
SAFETY_MAX_IDS = 500

# (COUNTRIES, ALL_COUNTRIES_LIST, helpers, etc. remain identical to previous version)
COUNTRIES = {
    "AF":"Afghanistan","AL":"Albania","DZ":"Algeria","AS":"American Samoa","AD":"Andorra",
    "AO":"Angola","AG":"Antigua and Barbuda","AR":"Argentina","AM":"Armenia","AU":"Australia",
    "AT":"Austria","AZ":"Azerbaijan","BS":"Bahamas","BH":"Bahrain","BD":"Bangladesh",
    "BB":"Barbados","BY":"Belarus","BE":"Belgium","BZ":"Belize","BJ":"Benin",
    "BT":"Bhutan","BO":"Bolivia","BA":"Bosnia and Herzegovina","BW":"Botswana","BR":"Brazil",
    "BN":"Brunei","BG":"Bulgaria","BF":"Burkina Faso","BI":"Burundi","KH":"Cambodia",
    "CM":"Cameroon","CA":"Canada","CV":"Cabo Verde","KY":"Cayman Islands","CF":"Central African Republic",
    "TD":"Chad","CL":"Chile","CN":"China","CO":"Colombia","KM":"Comoros",
    "CG":"Congo - Brazzaville","CD":"Congo - Kinshasa","CR":"Costa Rica","CI":"Côte d’Ivoire","HR":"Croatia",
    "CU":"Cuba","CY":"Cyprus","CZ":"Czechia","DK":"Denmark","DJ":"Djibouti",
    "DM":"Dominica","DO":"Dominican Republic","EC":"Ecuador","EG":"Egypt","SV":"El Salvador",
    "GQ":"Equatorial Guinea","ER":"Eritrea","EE":"Estonia","SZ":"Eswatini","ET":"Ethiopia",
    "FJ":"Fiji","FI":"Finland","FR":"France","GA":"Gabon","GM":"Gambia",
    "GE":"Georgia","DE":"Germany","GH":"Ghana","GR":"Greece","GD":"Grenada",
    "GT":"Guatemala","GN":"Guinea","GW":"Guinea-Bissau","GY":"Guyana","HT":"Haiti",
    "HN":"Honduras","HK":"Hong Kong","HU":"Hungary","IS":"Iceland","IN":"India",
    "ID":"Indonesia","IR":"Iran","IQ":"Iraq","IE":"Ireland","IL":"Israel",
    "IT":"Italy","JM":"Jamaica","JP":"Japan","JO":"Jordan","KZ":"Kazakhstan",
    "KE":"Kenya","KI":"Kiribati","KP":"North Korea","KR":"South Korea","KW":"Kuwait",
    "KG":"Kyrgyzstan","LA":"Laos","LV":"Latvia","LB":"Lebanon","LS":"Lesotho",
    "LR":"Liberia","LY":"Libya","LI":"Liechtenstein","LT":"Lithuania","LU":"Luxembourg",
    "MO":"Macao","MG":"Madagascar","MW":"Malawi","MY":"Malaysia","MV":"Maldives",
    "ML":"Mali","MT":"Malta","MH":"Marshall Islands","MR":"Mauritania","MU":"Mauritius",
    "MX":"Mexico","FM":"Micronesia","MD":"Moldova","MC":"Monaco","MN":"Mongolia",
    "ME":"Montenegro","MA":"Morocco","MZ":"Mozambique","MM":"Myanmar","NA":"Namibia",
    "NR":"Nauru","NP":"Nepal","NL":"Netherlands","NZ":"New Zealand","NI":"Nicaragua",
    "NE":"Niger","NG":"Nigeria","MK":"North Macedonia","NO":"Norway","OM":"Oman",
    "PK":"Pakistan","PW":"Palau","PA":"Panama","PG":"Papua New Guinea","PY":"Paraguay",
    "PE":"Peru","PH":"Philippines","PL":"Poland","PT":"Portugal","QA":"Qatar",
    "RO":"Romania","RU":"Russia","RW":"Rwanda","KN":"St Kitts & Nevis","LC":"St Lucia",
    "VC":"St Vincent & Grenadines","WS":"Samoa","SM":"San Marino","ST":"Sao Tome & Principe","SA":"Saudi Arabia",
    "SN":"Senegal","RS":"Serbia","SC":"Seychelles","SL":"Sierra Leone","SG":"Singapore",
    "SK":"Slovakia","SI":"Slovenia","SB":"Solomon Islands","SO":"Somalia","ZA":"South Africa",
    "ES":"Spain","LK":"Sri Lanka","SD":"Sudan","SR":"Suriname","SE":"Sweden",
    "CH":"Switzerland","SY":"Syria","TW":"Taiwan","TJ":"Tajikistan","TZ":"Tanzania",
    "TH":"Thailand","TL":"Timor-Leste","TG":"Togo","TO":"Tonga","TT":"Trinidad and Tobago",
    "TN":"Tunisia","TR":"Turkey","TM":"Turkmenistan","TV":"Tuvalu","UG":"Uganda",
    "UA":"Ukraine","AE":"United Arab Emirates","GB":"United Kingdom","US":"United States",
    "UY":"Uruguay","UZ":"Uzbekistan","VU":"Vanuatu","VA":"Vatican City","VE":"Venezuela",
    "VN":"Vietnam","YE":"Yemen","ZM":"Zambia","ZW":"Zimbabwe"
}
ALL_COUNTRIES_LIST = [f"{code} - {name}" for code, name in sorted(COUNTRIES.items(), key=lambda x: x[1])]

# -------- HELPERS --------
def iso_after_days(days: int) -> str:
    return (datetime.utcnow().replace(tzinfo=timezone.utc) - timedelta(days=days)).isoformat()

def chunk_list(lst: List[str], n: int):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

def code_from_option(opt: str) -> str:
    if not opt or " - " not in opt:
        return ""
    return opt.split(" - ")[0].strip().upper()

def format_count(n):
    try:
        n = int(n)
    except Exception:
        return str(n) if n is not None else "-"
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.1f}B".rstrip('0').rstrip('.')
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M".rstrip('0').rstrip('.')
    if n >= 1_000:
        return f"{n/1_000:.1f}k".rstrip('0').rstrip('.')
    return str(n)

def relative_time(published_at_iso: str) -> str:
    try:
        dt = datetime.fromisoformat(published_at_iso.replace("Z", "+00:00"))
    except Exception:
        try:
            dt = datetime.strptime(published_at_iso, "%Y-%m-%dT%H:%M:%S%z")
        except Exception:
            return published_at_iso
    now = datetime.now(timezone.utc)
    diff = now - dt.astimezone(timezone.utc)
    days = diff.days
    if days < 1:
        hours = diff.seconds // 3600
        if hours < 1:
            mins = diff.seconds // 60
            return f"{mins}m ago" if mins > 0 else "just now"
        return f"{hours}h ago"
    if days < 30:
        return f"{days} days ago" if days < 7 else f"{days//7}w ago"
    if days < 365:
        return f"{days//30}mo ago"
    return f"{days//365}y ago"

def parse_iso8601_duration(duration_str: str) -> str:
    """
    Convert ISO 8601 duration like 'PT18M57S' or 'PT1H2M3S' into human readable H:MM:SS or M:SS.
    """
    if not duration_str:
        return ""
    s = duration_str.upper().replace("PT", "")
    hours = mins = secs = 0
    num = ""
    for ch in s:
        if ch.isdigit():
            num += ch
        else:
            if ch == "H":
                hours = int(num) if num else 0
            elif ch == "M":
                mins = int(num) if num else 0
            elif ch == "S":
                secs = int(num) if num else 0
            num = ""
    # format
    if hours > 0:
        return f"{hours}:{mins:02d}:{secs:02d}"
    return f"{mins}:{secs:02d}"

# -------- UI SETUP --------
st.set_page_config(layout="wide", page_title="YTBNICHES- Your Personalized data Extractor")
st.title("YTBNICHES- Your Personalized data Extractor")

# API key retrieval (unchanged)
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

# Controls (unchanged; added strict region checkbox)
mode = st.selectbox("Mode", ["Select", "Keyword search (last N days)", "Trending (region)"], index=0)
is_trending = (mode == "Trending (region)")
is_select = (mode == "Select")

col1, col2, col3, col4 = st.columns([2,2,1,1])
with col1:
    selected_opt = st.selectbox("🔍 Region (code - country)", [""] + ALL_COUNTRIES_LIST, format_func=lambda x: x or "#SELECT COUNTRY", index=0, key="region_select")
    selected_region_code = code_from_option(selected_opt) if selected_opt else ""
with col2:
    DAYS_OPTIONS = ["Select", 7, 10, 30, 90]
    days_choice = st.selectbox("Days", DAYS_OPTIONS, index=0, disabled=is_trending, key="days_select")
with col3:
    max_results = st.slider("Max results per keyword / trending list", 1, 5, 2, key="max_results")
with col4:
    force_refresh = st.checkbox("Force refresh (ignore cache)", key="force_refresh")

keywords_input = st.text_input("Keywords", value="", placeholder="#TYPE YOUR KEYWORDS", disabled=is_trending, key="keywords_input")
min_views = st.number_input("Minimum total views filter (0 to skip)", min_value=0, value=0, step=100, key="min_views")
display_mode = st.selectbox("View mode", ["Table", "Card per Video", "Card per Channel"], index=0)

# New: strict region checkbox
strict_region = st.checkbox("Strict region filter (drop videos whose channel country ≠ selected region).", value=False)

st.caption("Cache will save results for 24 hours.")

# Cache clear on force refresh
if force_refresh:
    try:
        cached_search_ids.clear()
        cached_video_stats.clear()
    except Exception:
        pass

# -------- CACHED API CALLS (thumbnail + channelId included) --------
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
            ths = snip.get("thumbnails", {}) or {}
            thumb = None
            if ths.get("medium"):
                thumb = ths["medium"].get("url")
            elif ths.get("high"):
                thumb = ths["high"].get("url")
            elif ths.get("default"):
                thumb = ths["default"].get("url")
            results.append({
                "videoId": it["id"],
                "title": snip.get("title"),
                "channel": snip.get("channelTitle"),
                "channelId": snip.get("channelId"),
                "publishedAt": snip.get("publishedAt"),
                "views": int(stats.get("viewCount", 0)) if stats.get("viewCount") else 0,
                "likes": int(stats.get("likeCount", 0)) if stats.get("likeCount") else None,
                "duration_iso": cd.get("duration"),
                "duration": parse_iso8601_duration(cd.get("duration")),
                "url": f"https://www.youtube.com/watch?v={it['id']}",
                "thumbnail": thumb
            })
        time.sleep(0.12)
    return results

# -------- New cached channels fetch ----------
@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def cached_channels_info(channel_ids: List[str], api_key: str) -> Dict[str, Dict]:
    """
    Fetch channel snippet info (including country if present) for a list of channel ids.
    Returns dict: channelId -> snippet dict (may include 'country' if set).
    """
    out = {}
    unique = list(dict.fromkeys(channel_ids))[:500]  # safety cap
    for chunk in chunk_list(unique, 50):
        params = {"part":"snippet,brandingSettings","id":",".join(chunk),"maxResults":len(chunk),"key":api_key}
        r = requests.get(YT_CHANNELS, params=params, timeout=20)
        r.raise_for_status()
        for it in r.json().get("items", []):
            cid = it.get("id")
            snip = it.get("snippet", {}) or {}
            branding = it.get("brandingSettings", {}) or {}
            # country may be stored in snippet.get('country') depending on channel settings
            country = snip.get("country")
            out[cid] = {"snippet": snip, "branding": branding, "country": country}
        time.sleep(0.12)
    return out

# -------- Fetch functions (unchanged) --------
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

# -------- Run on ENTER (main flow) --------
if st.button("ENTER"):
    if is_select:
        st.error("Select a mode first.")
    else:
        if not selected_region_code:
            st.error("Select a country from the Region dropdown (type to search).")
        else:
            region_code = selected_region_code
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
                    df["publishedAt"] = pd.to_datetime(df["publishedAt"], errors="coerce")
                    if min_views > 0:
                        df = df[df["views"] >= int(min_views)]
                    df = df.sort_values("views", ascending=False).reset_index(drop=True)

                    # If strict_region enabled -> fetch channel info and filter
                    if strict_region:
                        # gather unique channel ids
                        channel_ids = df["channelId"].dropna().unique().tolist()
                        if channel_ids:
                            with st.spinner("Applying strict region filter (extra API calls)..."):
                                chinfo = cached_channels_info(channel_ids, api_key)
                                # build map channelId -> country (upper)
                                ch_country = {cid: (chinfo[cid].get("country") or "").upper() for cid in chinfo.keys()}
                                # filter df where channel country matches selected_region_code
                                before = len(df)
                                # only keep rows where channelId maps and equals region_code
                                df = df[df["channelId"].apply(lambda cid: (cid in ch_country) and (ch_country.get(cid,"") == region_code.upper()))]
                                after = len(df)
                                st.info(f"Strict region filter removed {before - after} videos. {after} left.")
                        else:
                            st.info("No channel IDs found to apply strict filter.")

                    # DISPLAY modes
                    if display_mode == "Table":
                        st.write(f"Found {len(df)} videos. Showing top results.")
                        st.dataframe(df[["title","channel","publishedAt","views","likes","duration","url"]].head(200))
                        if not df.empty:
                            st.bar_chart(df.head(10).set_index("title")["views"])

                    elif display_mode == "Card per Video":
                        st.write(f"Found {len(df)} videos. Showing as cards.")
                        n_cols = 3
                        items = df.to_dict(orient="records")
                        for i in range(0, len(items), n_cols):
                            cols = st.columns(n_cols)
                            row_items = items[i:i+n_cols]
                            for col, item in zip(cols, row_items):
                                with col:
                                    thumb = item.get("thumbnail")
                                    if thumb:
                                        try:
                                            st.image(thumb, use_column_width=True)
                                        except Exception:
                                            pass
                                    st.markdown(f"**[{item.get('title')}]({item.get('url')})**")
                                    st.write(f"_{item.get('channel')}_")
                                    views_str = format_count(item.get("views", 0))
                                    likes_str = format_count(item.get("likes")) if item.get("likes") is not None else "-"
                                    pub_str = relative_time(item.get("publishedAt").isoformat()) if pd.notnull(item.get("publishedAt")) else ""
                                    duration = item.get("duration") or ""
                                    st.markdown(f"**Views:** {views_str} &nbsp;&nbsp; **Likes:** {likes_str}")
                                    st.markdown(f"**Published:** {pub_str} &nbsp;&nbsp; **Duration:** {duration}")
                                    st.markdown("---")

                    else:  # Card per Channel
                        st.write(f"Found content from {df['channel'].nunique()} channels. Showing channel cards.")
                        grouped = df.groupby(["channel","channelId"], as_index=False).agg(
                            total_views = pd.NamedAgg(column="views", aggfunc="sum"),
                            avg_views = pd.NamedAgg(column="views", aggfunc="mean"),
                            videos = pd.NamedAgg(column="title", aggfunc=lambda s: list(s)[:3]),
                            sample_thumb = pd.NamedAgg(column="thumbnail", aggfunc=lambda s: next((x for x in s if x), None))
                        )
                        grouped = grouped.sort_values("total_views", ascending=False).to_dict(orient="records")
                        n_cols = 2
                        for i in range(0, len(grouped), n_cols):
                            cols = st.columns(n_cols)
                            row = grouped[i:i+n_cols]
                            for col, ch in zip(cols, row):
                                with col:
                                    thumb = ch.get("sample_thumb")
                                    if thumb:
                                        try:
                                            st.image(thumb, width=240)
                                        except Exception:
                                            pass
                                    st.markdown(f"### {ch.get('channel')}")
                                    tv = format_count(int(ch.get("total_views",0)))
                                    av = format_count(int(round(ch.get("avg_views",0))))
                                    st.markdown(f"**Total views (sample):** {tv} &nbsp;&nbsp; **Avg/views:** {av}")
                                    vids = ch.get("videos") or []
                                    for v in vids:
                                        st.write(f"- {v}")
                                    st.markdown("---")

                    csv = df.to_csv(index=False).encode("utf-8")
                    st.download_button("Download CSV", csv, file_name="yt_results.csv", mime="text/csv")
            except requests.HTTPError as e:
                st.error(f"API error: {e}")
            except Exception as e:
                st.error(f"Unexpected error: {e}")
