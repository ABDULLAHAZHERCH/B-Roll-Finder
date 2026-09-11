import os
import json
import re
import requests
import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

load_dotenv()

# --- PAGE SETUP ---
st.set_page_config(page_title="AI B-Roll Auto-Director", layout="wide", page_icon="🎬")

# --- SIDEBAR CONFIGURATION ---
st.sidebar.title("⚙️ Engine Configuration")

pexels_key = st.sidebar.text_input(
    "Pexels API Key",
    value=os.getenv("PEXELS_API_KEY", ""),
    type="password",
)
pixabay_key = st.sidebar.text_input(
    "Pixabay API Key",
    value=os.getenv("PIXABAY_API_KEY", ""),
    type="password",
)
gemini_key = st.sidebar.text_input(
    "Gemini API Key (optional)",
    value=os.getenv("GEMINI_API_KEY", ""),
    type="password",
    help="Optional: use one Gemini request for the whole script to improve search terms.",
)
use_gemini = st.sidebar.checkbox(
    "Use Gemini for better search terms",
    value=False,
    disabled=not gemini_key,
    help="Disabled by default for maximum speed. When enabled, Gemini makes one request per script, not one per line.",
)
clips_per_line = st.sidebar.slider("Clips per line", min_value=1, max_value=12, value=2)
aspect_ratio = st.sidebar.selectbox(
    "Aspect ratio",
    ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "9:21"],
    help="Used to choose the closest orientation when searching Pexels.",
)
api_orientation = {
    "16:9": "landscape",
    "9:16": "portrait",
    "1:1": "square",
    "4:3": "landscape",
    "3:4": "portrait",
    "21:9": "landscape",
    "9:21": "portrait",
}[aspect_ratio]
download_dir = st.sidebar.text_input("Local Download Folder", value="downloaded_broll")

# --- CORE PROCESSING ENGINES ---

def split_script_into_scenes(script: str) -> list[str]:
    """Split narration at sentence punctuation or explicit line breaks."""
    return [
        scene.strip()
        for scene in re.split(r"(?<=[.!?])\s*|\r?\n+", script.strip())
        if scene.strip()
    ]


SEARCH_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "by", "for", "from",
    "in", "into", "is", "it", "of", "on", "or", "that", "the", "their", "this",
    "to", "was", "were", "with",
}


def build_visual_query(sentence: str) -> str:
    """Create one short stock-search query locally without an AI request."""
    cleaned = re.sub(r"[^a-zA-Z0-9\s-]", " ", sentence.lower())
    words = [word for word in cleaned.split() if len(word) > 1 and word not in SEARCH_STOP_WORDS]
    return " ".join(words[:8]) or "stock footage"


def normalize_gemini_query(query: str) -> str:
    """Keep an AI-generated search term short and compatible with stock APIs."""
    return build_visual_query(query)


@st.cache_data(ttl=3600, max_entries=20)
def generate_gemini_queries(scenes: tuple[str, ...], api_key: str) -> tuple[str, ...]:
    """Generate one query per scene with a single optional Gemini request."""
    if not api_key or not scenes:
        return ()

    prompt = (
        "Create one concise stock-video search query for each numbered script scene. "
        "Return only a JSON array of strings in the same order, with exactly one string per scene. "
        "Use 3 to 8 concrete lowercase words describing visible subjects, actions, or places. "
        "Do not explain anything and do not merge or omit scenes.\n\n"
        + "\n".join(f"{index}: {scene}" for index, scene in enumerate(scenes, start=1))
    )
    client = None
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=max(256, len(scenes) * 24),
                response_mime_type="application/json",
            ),
        )
        raw_response = re.sub(r"^```(?:json)?\s*|\s*```$", "", response.text.strip(), flags=re.IGNORECASE)
        payload = json.loads(raw_response)
        if not isinstance(payload, list) or len(payload) != len(scenes):
            return ()
        return tuple(normalize_gemini_query(str(query)) for query in payload)
    except Exception:
        return ()
    finally:
        if client is not None:
            client.close()

@st.cache_data(ttl=600, max_entries=200)
def search_pexels(query: str, count: int, orientation: str, api_key: str):
    """Pexels Video API Search."""
    if not api_key:
        return []
    url = "https://api.pexels.com/videos/search"
    headers = {"Authorization": api_key}
    try:
        res = requests.get(
            url,
            headers=headers,
            params={"query": query, "per_page": count, "orientation": orientation},
            timeout=8,
        ).json()
        clips = []
        for video in res.get("videos", []):
            files = [f for f in video.get("video_files", []) if f.get("file_type") == "video/mp4"]
            if files:
                # Target HD (1080p / 720p) first, else fallback to first link
                best_file = next((f for f in files if f.get("height") in [1080, 720]), files[0])
                clips.append({
                    "source": "Pexels",
                    "id": f"pexels_{video['id']}",
                    "download_url": best_file["link"],
                    "preview_image": video["image"]
                })
        return clips
    except Exception:
        return []

@st.cache_data(ttl=600, max_entries=200)
def search_pixabay(query: str, count: int, api_key: str):
    """Pixabay Video API Search."""
    if not api_key:
        return []
    url = "https://pixabay.com/api/videos/"
    try:
        res = requests.get(
            url,
            params={"key": api_key, "q": query, "per_page": count},
            timeout=8,
        ).json()
        clips = []
        for hit in res.get("hits", []):
            videos = hit.get("videos", {})
            target = videos.get("medium") or videos.get("large") or videos.get("small")
            if target and target.get("url"):
                clips.append({
                    "source": "Pixabay",
                    "id": f"pixabay_{hit['id']}",
                    "download_url": target["url"],
                    "preview_image": f"https://i.vimeocdn.com/video/{hit.get('picture_id')}_640x360.jpg"
                })
        return clips
    except Exception:
        return []


def search_scene_clips(queries: list[dict], orientation: str, pexels_key: str, pixabay_key: str) -> list[dict]:
    """Search every scene query across all configured providers and deduplicate clips."""
    clips = []
    seen = set()
    jobs = []
    for query_item in queries:
        query = query_item["query"]
        count = query_item["clip_count"]
        jobs.extend([
            (
                "Pexels",
                query,
                lambda query=query, count=count: search_pexels(
                    query, count, orientation, pexels_key
                ),
            ),
            (
                "Pixabay",
                query,
                lambda query=query, count=count: search_pixabay(query, count, pixabay_key),
            ),
        ])

    with ThreadPoolExecutor(max_workers=min(8, len(jobs) or 1)) as executor:
        futures = [(source, query, executor.submit(search)) for source, query, search in jobs]
        for source, query, future in futures:
            results = future.result()
            for clip in results:
                clip_key = (clip["source"], clip["id"], clip["download_url"])
                if clip_key not in seen:
                    seen.add(clip_key)
                    clip["search_query"] = query
                    clips.append(clip)
    return clips


def download_file_stream(url: str, destination: Path):
    """Stream the original provider video directly to disk."""
    with requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
        stream=True,
        timeout=60,
    ) as response:
        response.raise_for_status()
        with destination.open("wb") as file:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if chunk:
                    file.write(chunk)

    if not destination.exists() or destination.stat().st_size < 1000:
        raise RuntimeError("The provider returned an empty or invalid video file.")


def next_download_folder(download_dir: str) -> Path:
    """Create the next numbered folder for a complete script run."""
    root = Path(download_dir)
    root.mkdir(parents=True, exist_ok=True)
    existing_numbers = [
        int(folder.name)
        for folder in root.iterdir()
        if folder.is_dir() and folder.name.isdigit()
    ]
    run_folder = root / str(max(existing_numbers, default=0) + 1)
    run_folder.mkdir()
    return run_folder


def download_all_clips(results: list[dict], download_dir: str) -> None:
    """Download one script run into its own numbered folder."""
    download_path = next_download_folder(download_dir)

    d_status = st.empty()
    d_progress = st.progress(0)
    download_jobs = []
    for result in results:
        for idx, clip in enumerate(result["clips"], start=1):
            file_dest = download_path / (
                f"line_{result['line_idx']:02d}_clip_{idx}_{clip['id']}.mp4"
            )
            download_jobs.append((clip, file_dest))

    total_clips = len(download_jobs)
    completed = 0
    failures = []
    with ThreadPoolExecutor(max_workers=min(4, total_clips or 1)) as executor:
        futures = {
            executor.submit(download_file_stream, clip["download_url"], file_dest): clip
            for clip, file_dest in download_jobs
        }
        for future, clip in futures.items():
            d_status.text(f"Downloading {clip['source']} clip {clip['id']}...")
            try:
                future.result()
            except Exception as error:
                failures.append(f"{clip['id']}: {error}")
            completed += 1
            if total_clips:
                d_progress.progress(completed / total_clips)

    if failures:
        for failure in failures:
            st.warning(f"Download failed: {failure}")
        d_status.warning(
            f"Downloaded {total_clips - len(failures)}/{total_clips} clips to "
            f"`{download_path.resolve()}`"
        )
    else:
        d_status.success(f"All {total_clips} clips downloaded to `{download_path.resolve()}`")

# --- UI WORKFLOW ---

st.title("🎬 Instant B-Roll Engine")
st.caption("Match every script scene with fast local keywords or one optional Gemini pass.")

script_text = st.text_area(
    "Paste your video script below (sentences become scenes):",
    height=180,
    placeholder="The world's financial markets spiraled downward this morning. Deep inside underground research bunkers, new AI models came online! Crowds flooded Times Square to witness the announcement?"
)

if "results" not in st.session_state:
    st.session_state.results = []
st.session_state.setdefault("auto_download_pending", False)

col1, col2 = st.columns([1, 4])
with col1:
    search_button = st.button("Match B-roll clips", type="primary", width="stretch")
with col2:
    auto_download = st.checkbox(
        "Auto-download matched clips",
        value=False,
        help="Download clips into the configured scene folders immediately after matching.",
    )

# 1. Matching & Querying Loop
if search_button and script_text.strip():
    if not pexels_key and not pixabay_key:
        st.error("Please provide at least a Pexels or Pixabay API key in the sidebar.")
        st.stop()

    lines = split_script_into_scenes(script_text)
    st.session_state.results = []
    progress_bar = st.progress(0)
    status = st.empty()
    gemini_queries = generate_gemini_queries(tuple(lines), gemini_key) if use_gemini else ()
    if use_gemini and not gemini_queries:
        st.warning("Gemini was unavailable for this script, so local keyword matching is being used.")

    for i, line in enumerate(lines):
        status.text(f"Processing line {i+1}/{len(lines)}...")
        query = gemini_queries[i] if i < len(gemini_queries) else build_visual_query(line)
        queries = [{"query": query, "clip_count": clips_per_line}]
        clips = search_scene_clips(
            queries,
            api_orientation,
            pexels_key,
            pixabay_key,
        )

        st.session_state.results.append({
            "line_idx": i + 1,
            "line_text": line,
            "meaning": "Gemini query matching" if gemini_queries else "Local keyword matching",
            "queries": queries,
            "visual_term": query,
            "clips": clips[:clips_per_line]
        })
        progress_bar.progress((i + 1) / len(lines))

    if auto_download:
        st.session_state.auto_download_pending = True
    status.success("All B-roll matches retrieved!")

# 2. Results Display & Video Previews
if st.session_state.results:
    st.divider()
    st.subheader("Match Results & Previews")
    st.caption(
        "Downloaded files are the original provider videos; no local video transcoding is used."
    )

    for item in st.session_state.results:
        with st.expander(f"Line {item['line_idx']}: \"{item['line_text']}\"", expanded=True):
            st.markdown(f"**Matching method:** {item['meaning']}")
            st.markdown(
                "**Visual searches:** "
                + ", ".join(
                    f"`{query['query']}` ({query['clip_count']} clip(s))"
                    for query in item["queries"]
                )
            )
            
            if not item["clips"]:
                st.warning("No stock footage found for this query.")
                continue

            cols = st.columns(len(item["clips"]))
            for idx, clip in enumerate(item["clips"]):
                with cols[idx]:
                    st.caption(f"Source: {clip['source']}")
                    st.video(clip["download_url"])
                    st.markdown(f"[Direct MP4 Link]({clip['download_url']})")

    # 3. Auto-Download to Local Disk
    st.divider()
    if st.button("Download all found clips", type="secondary"):
        download_all_clips(st.session_state.results, download_dir)

    if st.session_state.auto_download_pending:
        st.session_state.auto_download_pending = False
        st.info("Auto-download enabled: saving original provider videos...")
        download_all_clips(st.session_state.results, download_dir)