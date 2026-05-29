# cli-player

ASCII stream player for movies and TV — runs entirely in your terminal.

Built for [vyla-entertainment](https://github.com/vyla-entertainment/).

## Images

![image](/public/assets/screenshots/search.png)
![image](/public/assets/screenshots/view.png)
![image](/public/assets/screenshots/play.png)

## Requirements

- **Python 3.9+**
  - `requests` — HTTP client for TMDB API
  - `numpy` — Array processing
  - `opencv-python` — Video frame processing
  - `python-dotenv` — Environment variable management
- **ffmpeg + ffplay** — [ffmpeg.org/download](https://ffmpeg.org/download.html)
  - Add to `PATH` or place at `C:\ffmpeg\bin\`
- A Windows terminal with UTF-8 support (Windows Terminal recommended)

## Install

```bash
git clone https://github.com/vyla-entertainment/cli-player.git
cd cli-player
pip install -r requirements.txt
```

## Usage

```bash
python src/main.py
```

Search for any movie or TV show. Use arrow keys to navigate results, Enter to select.