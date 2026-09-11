# Instant B-Roll Engine

Turn a voiceover script into organized B-roll searches and downloadable stock-video assets from a local Streamlit app.

The engine turns each sentence or line into a stock-video search, searches Pexels and Pixabay, previews the results, and optionally downloads the original MP4 files into scene-specific folders. Gemini can optionally improve all search terms in one request per script.

## Features

- Sentence- and line-aware scene parsing
- Local keyword extraction with no AI calls by default
- Optional Gemini query improvement using one request for the whole script
- One search query per scene for faster processing
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
- Optional Gemini API key for improved search terms
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
PEXELS_API_KEY=your_pexels_key
PIXABAY_API_KEY=your_pixabay_key
GEMINI_API_KEY=your_gemini_key
```

The `.env` file is ignored by Git. Never commit real API keys.

You can also enter keys directly in the sidebar for a temporary session override.

## Run

```powershell
streamlit run app.py
```

Open the local URL shown by Streamlit, usually `http://localhost:8501`.

## Share with a friend on Windows

### Python-required bundle

If your friend already has Python 3.10 or newer, build the smaller package instead:

```powershell
.\build_python_bundle.ps1
```

Send `Broll_Python_Bundle.zip`. Your friend extracts it and double-clicks **Start B-Roll Engine (Python).bat**. The first launch creates a private app environment and downloads the dependencies; later launches are immediate. An internet connection is required for the first launch.

## Workflow

1. Paste a script into the editor.
2. Scenes are created from sentence-ending punctuation or newline breaks.
3. Enter or load the Pexels and/or Pixabay keys. Gemini is optional.
4. Choose an aspect ratio and maximum clips per scene.
5. Optionally enable **Use Gemini for better search terms**.
6. Click **Match B-roll clips**.
7. Review the generated search terms, provider labels, and previews.
8. Enable **Auto-download matched clips** before matching, or use **Download all found clips** afterward.

Downloaded files are stored under the configured folder:

```text
downloaded_broll/
  1/
    line_01_clip_1_pexels_12345.mp4
    line_01_clip_2_pixabay_67890.mp4
  2/
    line_01_clip_1_pexels_98765.mp4
```

The app intentionally saves original provider videos. It does not trim, transcode, or re-encode clips because FFmpeg is not required by this project.

## Security notes

- Keep `.env` local and private.
- Do not paste API keys into source files.
- Do not commit downloaded media or generated caches.
- API keys are loaded locally and are not stored in browser cookies.

## Related project

The architecture was informed by [RotoDraft Suite](https://github.com/AliRash3ed/Rotodraft-Suite-AI-Automated-Broll-and-AI-Assets-Collector-Engine), particularly its provider fallback ideas, parallel downloads, and local-first organization. This project remains a smaller Streamlit implementation focused on Pexels, Pixabay, and direct MP4 downloads.

## License

Add the license that matches how you intend to distribute this project before publishing it publicly.
