#!/usr/bin/env python3
"""
yt_scraper_segments_cli.py

Improvements:
- If audio-only is chosen, video CLI options are hidden.
- User can pick an existing folder (by index) OR create a new folder.
  - If creating new, you may optionally provide a folder name; leave blank to use sanitized video title.
"""

import os
import time
import datetime
import glob
import re
import subprocess
import shutil
import sys
import platform
import urllib.request
import zipfile
import tarfile
from yt_dlp.utils import sanitize_filename

try:
    import yt_dlp
except ImportError:
    print("Error: yt-dlp not installed. Install with: pip install yt-dlp")
    raise SystemExit(1)


def format_duration(seconds):
    return str(datetime.timedelta(seconds=int(seconds)))


def get_file_size(path):
    if not os.path.exists(path):
        return "N/A"
    size_bytes = os.path.getsize(path)
    return f"{size_bytes / 1024 / 1024:.2f} MB"


def parse_time(timestr):
    timestr = timestr.strip()
    if not timestr:
        return 0.0
    if re.match(r'^\d+(\.\d+)?$', timestr):
        return float(timestr)
    parts = timestr.split(':')
    parts = [float(p) for p in parts]
    if len(parts) == 1:
        return parts[0]
    elif len(parts) == 2:
        return parts[0] * 60 + parts[1]
    elif len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    else:
        raise ValueError(f"Unrecognized time format: {timestr}")


def parse_ranges(ranges_str):
    results = []
    ranges_str = ranges_str.strip()
    if not ranges_str:
        return results
    for part in ranges_str.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            a, b = part.split('-', 1)
            start = parse_time(a)
            end = parse_time(b)
            if end <= start:
                raise ValueError(f"Range end must be > start: {part}")
            results.append((start, end))
        else:
            raise ValueError(f"Please supply ranges with '-' (e.g. 00:01:23-00:02:34). Got: {part}")
    return results


def format_time_for_filename(t):
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    elif m:
        return f"{m}m{s:02d}s"
    else:
        return f"{s}s"


def find_downloaded_file(dirpath, base_name):
    candidates = []
    for p in glob.glob(os.path.join(dirpath, f"{base_name}.*")):
        if p.endswith(('-description.txt', '-stats.txt')):
            continue
        candidates.append((os.path.getsize(p), p))
    if not candidates:
        all_files = glob.glob(os.path.join(dirpath, "*"))
        if not all_files:
            return None
        candidates = [(os.path.getsize(p), p) for p in all_files if not p.endswith(('.txt', '.part'))]
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def get_ffmpeg_dir():
    """Return the directory where this script keeps its private FFmpeg binaries."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, "ffmpeg", "bin")


def get_ffmpeg_path():
    """Find FFmpeg in PATH or in the scraper's local ffmpeg/bin directory."""
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    local_ffmpeg = os.path.join(get_ffmpeg_dir(), "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if os.path.isfile(local_ffmpeg):
        return local_ffmpeg

    return None


def install_ffmpeg():
    """
    Automatically download a portable FFmpeg build into:
        <script directory>/ffmpeg/bin/

    No administrator privileges or PATH changes are required.
    """
    ffmpeg_dir = get_ffmpeg_dir()
    os.makedirs(ffmpeg_dir, exist_ok=True)

    if os.name == "nt":
        # BtbN provides Windows builds with ffmpeg.exe in the archive's bin folder.
        url = "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip"
        archive = os.path.join(os.path.dirname(ffmpeg_dir), "ffmpeg.zip")

        print("\nFFmpeg was not found.")
        print("Downloading a portable FFmpeg build automatically...")

        try:
            urllib.request.urlretrieve(url, archive)

            with zipfile.ZipFile(archive, "r") as z:
                z.extractall(os.path.dirname(ffmpeg_dir))

            # Locate the extracted bin directory and copy the binaries into our stable location.
            ffmpeg_exe = None
            ffprobe_exe = None

            search_root = os.path.dirname(ffmpeg_dir)
            for root, _, files in os.walk(search_root):
                if "ffmpeg.exe" in files:
                    ffmpeg_exe = os.path.join(root, "ffmpeg.exe")
                if "ffprobe.exe" in files:
                    ffprobe_exe = os.path.join(root, "ffprobe.exe")
                if ffmpeg_exe and ffprobe_exe:
                    break

            if not ffmpeg_exe:
                raise RuntimeError("Downloaded FFmpeg archive did not contain ffmpeg.exe.")

            shutil.copy2(ffmpeg_exe, os.path.join(ffmpeg_dir, "ffmpeg.exe"))
            if ffprobe_exe:
                shutil.copy2(ffprobe_exe, os.path.join(ffmpeg_dir, "ffprobe.exe"))

            # Clean up downloaded archive and extracted folders other than our stable folder.
            try:
                os.remove(archive)
            except OSError:
                pass

            # Remove extracted top-level build directories if present.
            stable_parent = os.path.dirname(ffmpeg_dir)
            for name in os.listdir(stable_parent):
                path = os.path.join(stable_parent, name)
                if name != "bin" and os.path.isdir(path):
                    try:
                        shutil.rmtree(path)
                    except OSError:
                        pass

        except Exception as e:
            try:
                if os.path.exists(archive):
                    os.remove(archive)
            except OSError:
                pass
            raise RuntimeError(
                "Could not automatically install FFmpeg. "
                f"Please check your internet connection and try again. Details: {e}"
            )

    else:
        raise RuntimeError(
            "FFmpeg was not found. Automatic installation is currently configured "
            "for Windows. Please install FFmpeg using your operating system's package manager."
        )

    ffmpeg_path = get_ffmpeg_path()
    if not ffmpeg_path:
        raise RuntimeError("FFmpeg installation completed, but ffmpeg could not be located.")

    print(f"FFmpeg ready: {ffmpeg_path}")
    return ffmpeg_path


def ensure_ffmpeg():
    """Get FFmpeg, installing a local copy automatically if necessary."""
    ffmpeg_path = get_ffmpeg_path()
    if ffmpeg_path:
        return ffmpeg_path
    return install_ffmpeg()


def ffmpeg_exists():
    return get_ffmpeg_path() is not None


def run_ffmpeg_trim(infile, outfile, start, end, reencode_audio=False, reencode_video=False, audio_only=False):
    ffmpeg_path = ensure_ffmpeg()

    start_arg = str(start)
    duration = end - start
    duration_arg = str(duration)

    cmd = [ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error", "-ss", start_arg, "-i", infile, "-t", duration_arg]

    if audio_only:
        if reencode_audio:
            cmd += ["-vn", "-acodec", "libmp3lame", "-q:a", "2", outfile]
        else:
            cmd += ["-vn", "-c", "copy", outfile]
    else:
        if reencode_video:
            cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", "23", "-c:a", "aac", outfile]
        else:
            cmd += ["-c", "copy", outfile]

    completed = subprocess.run(cmd, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "ffmpeg failed with unknown error")


def list_existing_dirs(base_output_dir):
    # returns list of directory names (not full paths) inside base_output_dir
    os.makedirs(base_output_dir, exist_ok=True)
    names = [d for d in sorted(os.listdir(base_output_dir)) if os.path.isdir(os.path.join(base_output_dir, d))]
    return names


def choose_folder_interactive(base_output_dir, deferred_generated_name_allowed=True):
    """
    Let user pick existing directory or create a new one.
    If creating new and user leaves name blank, the caller will be expected to use the generated sanitized_title later.
    Returns a dict describing the choice:
      { 'mode': 'existing', 'path': fullpath }
    or
      { 'mode': 'new', 'name_given': <string or '' (blank)>, 'path': None }  # path will be created later when we know the final folder name
    """
    print("\nFolder options:")
    existing = list_existing_dirs(base_output_dir)
    if existing:
        print("Existing folders:")
        for idx, name in enumerate(existing, start=1):
            print(f"  [{idx}] {name}")
    else:
        print("No existing folders found in", base_output_dir)

    print("  [0] Create a new folder")
    try:
        choice = int(input("Select index to use existing folder, or 0 to create new [0]: ") or "0")
    except ValueError:
        choice = 0

    if choice == 0:
        print("Creating a new folder.")
        user_name = input("Optional folder name (leave blank to use sanitized video title): ").strip()
        return {'mode': 'new', 'name_given': user_name, 'path': None}
    else:
        idx = choice - 1
        if 0 <= idx < len(existing):
            chosen_name = existing[idx]
            return {'mode': 'existing', 'path': os.path.join(base_output_dir, chosen_name)}
        else:
            print("Invalid index, defaulting to create new folder with sanitized title.")
            return {'mode': 'new', 'name_given': '', 'path': None}


def get_user_choices():
    print("\nDownload Options:")

    # Audio-only choice
    audio_only = input("Download audio-only? (y/n) [n]: ").lower() == 'y'

    # If audio-only, hide video-specific options
    sub_langs = []
    if not audio_only:
        subs = input("Include subtitles? (y/n) [n]: ").lower()
        if subs == 'y':
            sub_langs = input("Enter language codes (comma separated, e.g., en,es) [en]: ") or 'en'
            sub_langs = [lang.strip() for lang in sub_langs.split(',')]
    else:
        # for audio-only, subtitles don't make sense in the same way; skip
        sub_langs = []

    audio_format = None
    if audio_only:
        audio_format = input("Preferred audio format for full download (mp3/m4a) [mp3]: ").lower() or 'mp3'
        if audio_format not in ('mp3', 'm4a'):
            print("Invalid choice, defaulting to mp3")
            audio_format = 'mp3'

    # If not audio-only, ask video-related choices
    selected_format = 'bestvideo+bestaudio/best'
    merge_format = 'mkv'
    if not audio_only:
        res_choice = input("Choose resolution for video (1080p, 720p, 480p, best) [best]: ").lower() or 'best'
        format_map = {
            '1080p': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]',
            '720p': 'bestvideo[height<=720]+bestaudio/best[height<=720]',
            '480p': 'bestvideo[height<=480]+bestaudio/best[height<=480]',
            'best': 'bestvideo+bestaudio/best'
        }
        selected_format = format_map.get(res_choice, 'bestvideo+bestaudio/best')

        merge_format = input("Output container for video (mkv/mp4) [mkv]: ").lower() or 'mkv'
        if merge_format not in ['mkv', 'mp4']:
            print("Invalid format, defaulting to mkv")
            merge_format = 'mkv'

    return {
        'audio_only': audio_only,
        'audio_format': audio_format,
        'subtitles': sub_langs,
        'format': selected_format,
        'merge_format': merge_format
    }


def download_youtube_video():
    # Always create/use a "scrapes" folder beside this Python file.
    # All downloaded files, segments, descriptions, and stats are stored there.
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_output_dir = os.path.join(script_dir, "scrapes")
    os.makedirs(base_output_dir, exist_ok=True)

    video_url = input("Enter YouTube URL: ").strip()
    if not video_url:
        print("No URL given. Exiting.")
        return

    user_choices = get_user_choices()

    # Choose folder now (may defer actual creation if user wants sanitized title)
    folder_choice = choose_folder_interactive(base_output_dir)

    # Ask about segments (if audio-only, only allow audio segments)
    want_segments = input("Extract segments from timestamps after download? (y/n) [n]: ").lower() == 'y'
    ranges = []
    segment_type = "audio"
    if want_segments:
        ranges_input = input("Enter timestamp ranges (comma-separated). Examples:\n  00:01:23-00:02:34, 90-150\nRanges: ")
        try:
            ranges = parse_ranges(ranges_input)
        except Exception as e:
            print(f"Error parsing ranges: {e}")
            print("Aborting segmentation request.")
            want_segments = False
            ranges = []

        if want_segments:
            if user_choices['audio_only']:
                # force audio
                segment_type = 'audio'
                print("Audio-only download selected; segments will be audio only.")
            else:
                stype = input("Extract segments as audio, video, or both? (audio/video/both) [audio]: ").lower() or 'audio'
                if stype not in ('audio', 'video', 'both'):
                    print("Invalid choice, defaulting to audio")
                    stype = 'audio'
                segment_type = stype

    try:
        start_time = time.time()
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info_dict = ydl.extract_info(video_url, download=False)
            video_title = info_dict.get('title', 'video')
            sanitized_title = sanitize_filename(video_title)
            # decide actual folder path now based on folder_choice
            if folder_choice['mode'] == 'existing':
                video_dir = folder_choice['path']
            else:
                # new folder
                if folder_choice['name_given']:
                    folder_name = sanitize_filename(folder_choice['name_given'])
                else:
                    folder_name = sanitized_title
                video_dir = os.path.join(base_output_dir, folder_name)
            os.makedirs(video_dir, exist_ok=True)

        # If user wanted video segments but selected audio-only, override
        if want_segments and segment_type in ('video', 'both') and user_choices['audio_only']:
            print("You requested video segments but audio-only download was selected. Switching to download full video.")
            user_choices['audio_only'] = False

        # Make sure FFmpeg is available before yt-dlp starts any post-processing.
        ffmpeg_path = ensure_ffmpeg()
        ffmpeg_location = os.path.dirname(ffmpeg_path)

        # Prepare yt-dlp options
        ydl_opts = {
            'format': user_choices['format'] if not user_choices['audio_only'] else 'bestaudio/best',
            'outtmpl': os.path.join(video_dir, f'{sanitized_title}.%(ext)s'),
            'writesubtitles': bool(user_choices['subtitles']) and (not user_choices['audio_only']),
            'subtitleslangs': user_choices['subtitles'],
            'noplaylist': True,
            'quiet': False,
            'no_warnings': False,
            'postprocessor_args': ['-threads', '4'],
            'merge_output_format': user_choices['merge_format'],
            'ffmpeg_location': ffmpeg_location,
        }

        if user_choices['audio_only']:
            audio_format = user_choices.get('audio_format', 'mp3') or 'mp3'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': audio_format,
                'preferredquality': '192',
            }, {'key': 'FFmpegMetadata'}]
        else:
            ydl_opts['postprocessors'] = [
                {'key': 'FFmpegEmbedSubtitle'},
                {'key': 'FFmpegMetadata'}
            ]

        # Download
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print("\nStarting download...")
            ydl.download([video_url])
        end_time = time.time()

        downloaded_file = find_downloaded_file(video_dir, sanitized_title)
        if not downloaded_file:
            print("Downloaded file not found in expected location.")
        else:
            print(f"Downloaded file: {downloaded_file} ({get_file_size(downloaded_file)})")

        # Segmentation
        created_segments = []
        if want_segments and ranges:
            if not downloaded_file:
                print("Cannot create segments because downloaded file was not found.")
            else:
                for idx, (start, end) in enumerate(ranges, start=1):
                    start_label = format_time_for_filename(start)
                    end_label = format_time_for_filename(end)
                    base_segment_name = f"{sanitized_title}_segment{idx}_{start_label}_to_{end_label}"

                    # Audio segment
                    if segment_type in ('audio', 'both'):
                        main_ext = os.path.splitext(downloaded_file)[1].lower()
                        if main_ext in ('.mp3', '.m4a', '.wav', '.aac', '.ogg', '.opus'):
                            out_ext = main_ext
                            out_audio_file = os.path.join(video_dir, f"{base_segment_name}{out_ext}")
                            reencode = False
                        else:
                            out_ext = '.mp3'
                            out_audio_file = os.path.join(video_dir, f"{base_segment_name}{out_ext}")
                            reencode = True

                        print(f"Creating audio segment {idx}: {out_audio_file} ({start}s -> {end}s)")
                        try:
                            run_ffmpeg_trim(downloaded_file, out_audio_file, start, end, reencode_audio=reencode, audio_only=True)
                            created_segments.append(out_audio_file)
                        except Exception as e:
                            print(f"Failed to create audio segment {idx}: {e}")

                    # Video segment
                    if segment_type in ('video', 'both'):
                        main_ext = os.path.splitext(downloaded_file)[1].lower()
                        if main_ext in ('.mp4', '.mkv', '.webm', '.mov'):
                            out_ext = main_ext
                        else:
                            out_ext = f".{user_choices['merge_format']}"
                        out_video_file = os.path.join(video_dir, f"{base_segment_name}{out_ext}")

                        print(f"Creating video segment {idx}: {out_video_file} ({start}s -> {end}s)")
                        try:
                            run_ffmpeg_trim(downloaded_file, out_video_file, start, end, reencode_video=False, audio_only=False)
                            created_segments.append(out_video_file)
                        except Exception as e:
                            print(f"Direct copy failed for video segment {idx}: {e}")
                            print("Attempting re-encode for compatibility...")
                            try:
                                run_ffmpeg_trim(downloaded_file, out_video_file, start, end, reencode_video=True, audio_only=False)
                                created_segments.append(out_video_file)
                            except Exception as e2:
                                print(f"Failed to create video segment {idx} even after re-encode: {e2}")

        # Save description and stats
        description = info_dict.get('description', '')
        desc_path = os.path.join(video_dir, f'{sanitized_title}-description.txt')
        with open(desc_path, 'w', encoding='utf-8') as f:
            f.write(description)

        upload_date = info_dict.get('upload_date', None)
        upload_date_str = "N/A"
        if upload_date:
            try:
                upload_date_str = datetime.datetime.strptime(upload_date, '%Y%m%d').strftime('%B %d, %Y')
            except Exception:
                upload_date_str = upload_date

        stats_content = [
            "===Download Statistics===",
            f"Download format: {user_choices['format'] if not user_choices['audio_only'] else 'bestaudio'}",
            f"Subtitles included: {', '.join(user_choices['subtitles']) if user_choices['subtitles'] else 'No'}",
            f"Output container: {user_choices['merge_format'].upper()}",
            f"Audio-only download: {'Yes' if user_choices['audio_only'] else 'No'}",
            f"Time taken: {end_time - start_time:.2f} seconds",
            f"Completion time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "===Video Statistics===",
            f"Title: {info_dict.get('title', 'N/A')}",
            f"Duration: {format_duration(info_dict.get('duration', 0))}",
            f"Channel: {info_dict.get('uploader', 'N/A')}",
            f"Resolution: {info_dict.get('width', 'N/A')}x{info_dict.get('height', 'N/A')}",
            f"FPS: {info_dict.get('fps', 'N/A')}",
            f"Upload date: {upload_date_str}",
            f"View count: {info_dict.get('view_count', 'N/A'):,}",
            f"Video URL: {video_url}",
            "",
            "===Files Created===",
        ]

        if downloaded_file:
            stats_content.append(f"Downloaded: {downloaded_file} ({get_file_size(downloaded_file)})")
        if created_segments:
            for s in created_segments:
                stats_content.append(f"Segment: {s} ({get_file_size(s)})")
        else:
            stats_content.append("No additional segments created.")

        stats_path = os.path.join(video_dir, f'{sanitized_title}-stats.txt')
        with open(stats_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(stats_content))

        print("\nDownload complete!")
        print(f"Files saved to: {video_dir}")
        print("Created files:")
        to_show = [downloaded_file] + (created_segments or [])
        for p in to_show:
            if p:
                print(" -", p)

        input("\nPress Enter to Exit...")

    except Exception as e:
        print(f"\nError: {str(e)}")
        input("Press Enter to Exit...")


if __name__ == "__main__":
    download_youtube_video()
