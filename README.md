# Youtube-Skraper
A python script to download youtube videos, properly.
# YouTube Scraper & Segment Downloader

A simple interactive Python CLI for downloading YouTube videos or audio with `yt-dlp`, extracting timestamped segments, and saving useful video metadata.

### Features

* Download YouTube videos or audio-only files
* Choose video quality: 1080p, 720p, 480p, or best available
* Choose MP4/MKV video output
* Choose MP3/M4A for audio-only downloads
* Optionally download subtitles
* Extract audio, video, or both from custom timestamp ranges
* Automatically organise downloads into folders
* Save the video's description and download statistics
* Automatically download a portable FFmpeg build on Windows if FFmpeg isn't already available

### Installation

The only Python dependency you need to install manually is `yt-dlp`:

```bash
pip install yt-dlp
```

That's it. The script handles FFmpeg automatically on Windows if it isn't already installed.

### Usage

Run the script:

```bash
python yt_scraper_segments_cli.py
```

Enter a YouTube URL and follow the interactive prompts.

For example, timestamp ranges can be entered as:

```text
00:01:23-00:02:34, 90-150
```

Downloaded files and generated segments are stored in a `scrapes` folder next to the script.

> **Note:** FFmpeg is required for merging, audio extraction, and segment processing. On Windows, the script automatically downloads and manages a local FFmpeg copy when needed.
