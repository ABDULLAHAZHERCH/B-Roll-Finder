# Instant B-Roll Engine

Turn a voiceover script into organized B-roll searches and downloadable stock-video assets from a local Streamlit app.

The engine uses Gemini to understand each complete sentence semantically, generate one or more concrete visual searches, search Pexels and Pixabay, preview the results, and optionally download the original MP4 files into scene-specific folders.

## Features

- Sentence-aware scene parsing using `.`, `?`, and `!`
- Gemini semantic analysis for each scene
- Automatic discovery of the strongest compatible Gemini text model
- Multiple AI-generated visual searches for scenes with multiple visual beats
- Searches both Pexels and Pixabay for every query
- Deduplicated provider results with source labels
- Pexels orientation support for landscape, portrait, and square workflows
- Aspect-ratio presets:
  - `16:9`
  - `9:16`
  - `1:1`
  - `4:3`
  - `3:4`
  - `21:9`
  - `9:21`
- Up to 12 clips per scene
- In-browser video previews and direct MP4 links
- Optional automatic downloading
- Manual download-all action
- Parallel provider searches and downloads
- Short-lived caching to reduce repeated API calls and improve rerun speed
- Local `.env` support for persistent API-key configuration
- No FFmpeg required: downloads save original provider videos without transcoding

## Requirements

- Python 3.10 or newer
- A Gemini API key
- At least one stock-video API key:
  - [Pexels API key](https://www.pexels.com/api/)
  - [Pixabay API key](https://pixabay.com/api/docs/)

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, run the app with the environment's Python directly:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

## Configuration

Create a local `.env` file from the example:

```powershell
Copy-Item .env.example .env
```

Add your keys:

```env
GEMINI_API_KEY=your_gemini_key
PEXELS_API_KEY=your_pexels_key
PIXABAY_API_KEY=your_pixabay_key
```

The `.env` file is ignored by Git. Never commit real API keys.

You can also enter keys directly in the sidebar for a temporary session override.

## Run

```powershell
streamlit run app.py
```

Open the local URL shown by Streamlit, usually `http://localhost:8501`.

## Workflow

1. Paste a script into the editor.
2. Scenes are created from sentence-ending punctuation, not newline breaks.
3. Enter or load the Gemini, Pexels, and/or Pixabay keys.
4. Choose an aspect ratio and maximum clips per scene.
5. Click **Match B-roll clips**.
6. Review Gemini's semantic interpretation, generated searches, provider labels, and previews.
7. Enable **Auto-download matched clips** before matching, or use **Download all found clips** afterward.

Downloaded files are stored under the configured folder:

```text
downloaded_broll/
  line_01_visual_search/
    clip_1_pexels_12345.mp4
    clip_2_pixabay_67890.mp4
```

The app intentionally saves original provider videos. It does not trim, transcode, or re-encode clips because FFmpeg is not required by this project.

## Gemini reliability

The app uses the supported `google-genai` SDK and the recommended chat API. It:

- Requests structured JSON semantic analysis.
- Retries temporary capacity, rate-limit, timeout, and connection errors.
- Tries the next compatible Gemini model when a stronger model is temporarily unavailable.
- Reports malformed or incomplete model output clearly.

## Security notes

- Keep `.env` local and private.
- Do not paste API keys into source files.
- Do not commit downloaded media or generated caches.
- API keys are loaded locally and are not stored in browser cookies.

## Related project

The architecture was informed by [RotoDraft Suite](https://github.com/AliRash3ed/Rotodraft-Suite-AI-Automated-Broll-and-AI-Assets-Collector-Engine), particularly its structured AI keyword workflow, provider fallback ideas, parallel downloads, and local-first organization. This project remains a smaller Streamlit implementation focused on Pexels, Pixabay, Gemini, and direct MP4 downloads.

## License

Add the license that matches how you intend to distribute this project before publishing it publicly.
