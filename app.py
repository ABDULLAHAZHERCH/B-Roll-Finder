import os
import json
import re
import time
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
    "Gemini API Key (Required)",
    value=os.getenv("GEMINI_API_KEY", ""),
    type="password",
    help="Required: Gemini generates the visual search query for every scene.",
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

MODEL_PRIORITY = {
    "gemini-3": 500,
    "gemini-2.5-pro": 400,
    "gemini-2.5-flash": 300,
    "gemini-2.0": 200,
    "gemini-1.5-pro": 100,
    "gemini-1.5-flash": 50,
}

def split_script_into_scenes(script: str) -> list[str]:
    """Split narration into scenes at sentence-ending punctuation, not newlines."""
    normalized = re.sub(r"\s+", " ", script).strip()
    if not normalized:
        return []

    matches = list(re.finditer(r"[^.!?]+[.!?]+", normalized))
    scenes = [match.group(0).strip() for match in matches]
    trailing_text = normalized[matches[-1].end():].strip() if matches else normalized
    if trailing_text:
        scenes.append(trailing_text)
    return scenes


def normalize_visual_query(query: str) -> str:
    """Keep model output usable as a short stock-footage search query."""
    cleaned = re.sub(r"```[\w-]*|```", "", query or "")
    cleaned = re.sub(r"^(?:keywords?|query|search terms?)\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[^a-zA-Z0-9\s-]", " ", cleaned.lower())
    words = [word for word in cleaned.split() if len(word) > 1]
    return " ".join(words[:6])


def model_priority(model_name: str) -> int:
    """Rank compatible Gemini text models, preferring quality over latency."""
    normalized = model_name.lower().replace("models/", "")
    if any(term in normalized for term in ("embedding", "image", "audio", "tts", "live", "robotics")):
        return -1
    return max(
        (score for prefix, score in MODEL_PRIORITY.items() if normalized.startswith(prefix)),
        default=0,
    )


@st.cache_data(ttl=3600, max_entries=20)
def discover_gemini_models(api_key: str) -> tuple[str, ...]:
    """Find compatible Gemini text models in strongest-first order."""
    if not api_key:
        raise ValueError("Gemini API key is required for AI keyword generation.")
    client = None
    try:
        client = genai.Client(api_key=api_key)
        models = [
            model for model in client.models.list()
            if "generateContent" in getattr(model, "supported_actions", [])
            and model_priority(model.name) > 0
        ]
        if not models:
            raise RuntimeError("This Gemini API key has no compatible text-generation model.")
        return tuple(
            model.name.replace("models/", "")
            for model in sorted(models, key=lambda item: model_priority(item.name), reverse=True)
        )
    except Exception as error:
        raise RuntimeError(f"Gemini model discovery failed: {error}") from error
    finally:
        if client is not None:
            client.close()


def discover_best_gemini_model(api_key: str) -> str:
    """Return the strongest compatible model for display and diagnostics."""
    return discover_gemini_models(api_key)[0]


def is_transient_gemini_error(error: Exception) -> bool:
    """Identify temporary capacity, rate-limit, and transport failures."""
    message = str(error).lower()
    return any(
        marker in message
        for marker in (
            "503",
            "unavailable",
            "high demand",
            "429",
            "resource_exhausted",
            "temporarily",
            "timeout",
            "connection reset",
        )
    )


def parse_scene_analysis(raw_response: str, max_clips: int) -> dict:
    """Validate Gemini's structured semantic analysis and normalize its queries."""
    cleaned_response = (raw_response or "").strip()
    if cleaned_response.startswith("```"):
        cleaned_response = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned_response, flags=re.IGNORECASE)
    try:
        payload = json.loads(cleaned_response)
    except json.JSONDecodeError as error:
        if "Unterminated string" in error.msg or "Expecting" in error.msg:
            raise ValueError(
                "Gemini returned incomplete JSON. The response may have been truncated; "
                "try fewer clips per line or run the scene again."
            ) from error
        raise ValueError(f"Gemini returned invalid JSON: {error}") from error

    if not isinstance(payload, dict):
        raise ValueError("Gemini response must be a JSON object.")
    meaning = str(payload.get("meaning", "")).strip()
    raw_queries = payload.get("queries")
    if not meaning or not isinstance(raw_queries, list):
        raise ValueError("Gemini response must include meaning and queries.")

    queries = []
    remaining_clips = max_clips
    for item in raw_queries:
        if not isinstance(item, dict) or remaining_clips <= 0:
            continue
        query = normalize_visual_query(str(item.get("query", "")))
        if not query:
            continue
        try:
            requested_clips = int(item.get("clip_count", 1))
        except (TypeError, ValueError):
            requested_clips = 1
        clip_count = min(max(requested_clips, 1), remaining_clips)
        queries.append({"query": query, "clip_count": clip_count})
        remaining_clips -= clip_count

    if not queries:
        raise ValueError("Gemini returned no usable stock-footage queries.")
    return {"meaning": meaning, "queries": queries}


@st.cache_data(ttl=3600, max_entries=200)
def analyze_scene_llm(sentence: str, api_key: str, max_clips: int) -> dict:
    """Use strongest-first Gemini models with bounded retry and fallback."""
    model_names = discover_gemini_models(api_key)
    client = None
    failures = []
    prompt = (
        "Act as a senior documentary B-roll director and semantic video analyst. "
        "Understand the complete meaning of the narration before choosing visuals. "
        f"Analyze this one scene and allocate at most {max_clips} total clips across multiple distinct searches. "
        'Return only valid JSON: {"meaning":"brief visual summary",'
        '"queries":[{"query":"3 to 6 lowercase stock search words","clip_count":1}]}. '
        "Create 1 to 4 queries only when the scene contains multiple visual beats. "
        "Use concrete subjects, actions, settings, or environments visible on camera. "
        "Do not use abstract concepts, metaphors, advice, emotions, hashtags, or explanations. "
        "Clip counts must be positive integers and their total must not exceed the limit.\n"
        f"Scene: {sentence}"
    )
    try:
        client = genai.Client(api_key=api_key)
        for model_name in model_names:
            for attempt in range(2):
                try:
                    chat = client.chats.create(
                        model=model_name,
                        config=types.GenerateContentConfig(
                            temperature=0.2,
                            max_output_tokens=1024,
                            response_mime_type="application/json",
                        ),
                    )
                    response = chat.send_message(message=prompt)
                    return parse_scene_analysis(response.text, max_clips)
                except (ValueError, RuntimeError) as error:
                    if not is_transient_gemini_error(error):
                        raise
                    failures.append(f"{model_name}: {error}")
                except Exception as error:
                    if not is_transient_gemini_error(error):
                        raise RuntimeError(
                            f"Gemini semantic analysis failed using {model_name}: {error}"
                        ) from error
                    failures.append(f"{model_name}: {error}")
                if attempt == 0:
                    time.sleep(2)
    finally:
        if client is not None:
            client.close()

    tried = ", ".join(model_names)
    raise RuntimeError(
        "Gemini models were temporarily unavailable after retries. "
        f"Tried: {tried}. Please retry in a moment. Details: {'; '.join(failures[-3:])}"
    )

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


def download_all_clips(results: list[dict], download_dir: str) -> None:
    """Download all matched clips into their scene-specific folders."""
    download_path = Path(download_dir)
    download_path.mkdir(parents=True, exist_ok=True)

    d_status = st.empty()
    d_progress = st.progress(0)
    download_jobs = []
    for result in results:
        line_folder = download_path / (
            f"line_{result['line_idx']:02d}_"
            f"{re.sub(r'[^a-zA-Z0-9]', '_', result['visual_term'][:20])}"
        )
        line_folder.mkdir(parents=True, exist_ok=True)

        for idx, clip in enumerate(result["clips"], start=1):
            file_dest = line_folder / f"clip_{idx}_{clip['id']}.mp4"
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
st.caption("Semantically analyze each scene with Gemini, generate multiple visual searches, and fetch clips from Pexels & Pixabay.")

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

    for i, line in enumerate(lines):
        status.text(f"Processing line {i+1}/{len(lines)}...")
        
        # Understand the full scene and generate one or more visual searches.
        try:
            analysis = analyze_scene_llm(line, gemini_key, clips_per_line)
        except (ValueError, RuntimeError) as error:
            status.error(str(error))
            st.stop()
        
        clips = search_scene_clips(
            analysis["queries"],
            api_orientation,
            pexels_key,
            pixabay_key,
        )
        allocated_clip_limit = sum(item["clip_count"] for item in analysis["queries"])
        visual_term = ", ".join(item["query"] for item in analysis["queries"])

        st.session_state.results.append({
            "line_idx": i + 1,
            "line_text": line,
            "meaning": analysis["meaning"],
            "queries": analysis["queries"],
            "visual_term": visual_term,
            "clips": clips[:allocated_clip_limit]
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
            st.markdown(f"**Semantic analysis:** {item['meaning']}")
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