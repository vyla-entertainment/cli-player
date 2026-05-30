import requests
import json
import msvcrt
import threading
import itertools
import sys
import time
import subprocess
import numpy as np
import cv2
import queue
import shutil
import os
from dotenv import load_dotenv

os.system("")

load_dotenv()

TMDB_KEY = os.getenv("TMDB_KEY")
BASE_URL = os.getenv("BASE_URL")
ASCII_CHARSET = " `.-':_,^=;><+!rc*/z?sLTv)J7(|Fi{C}fI31tlu[neoZ5Yxjya]2ESwqkP6h9d4VpOGbUAKXHm8RD#$Bg0MNWQ%&@"

if not TMDB_KEY:
    raise RuntimeError("Missing TMDB_KEY in .env")

FFMPEG_CANDIDATES = [
    "ffmpeg",
    r"C:\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    os.path.expanduser(r"~\ffmpeg\bin\ffmpeg.exe"),
]
FFPLAY_CANDIDATES = [
    "ffplay",
    r"C:\ffmpeg\bin\ffplay.exe",
    r"C:\Program Files\ffmpeg\bin\ffplay.exe",
    os.path.expanduser(r"~\ffmpeg\bin\ffplay.exe"),
]

def find_bin(candidates):
    for path in candidates:
        try:
            subprocess.run([path, "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            return path
        except:
            pass
    return None

def terminal_size():
    s = shutil.get_terminal_size((120, 40))
    return s.columns, s.lines

def search_tmdb(q):
    r = requests.get(
        "https://api.themoviedb.org/3/search/multi",
        params={"query": q, "api_key": TMDB_KEY}
    ).json()
    return [x for x in r.get("results", []) if x.get("media_type") != "person"]

def pick(items):
    idx = 0
    while True:
        sys.stdout.write("\033[H\033[J")
        for j, it in enumerate(items[:20]):
            name = it.get("title") or it.get("name")
            year = (it.get("release_date") or it.get("first_air_date") or "")[:4]
            tag  = "MOVIE" if it.get("media_type") == "movie" else "  TV "
            mark = "> " if j == idx else "  "
            sys.stdout.write(f"  {mark}[{tag}]  {name}  {year}\n")
        sys.stdout.flush()
        k = msvcrt.getch()
        if k in (b'\x00', b'\xe0'):
            k = msvcrt.getch()
            if k == b'H': idx = max(0, idx - 1)
            elif k == b'P': idx = min(min(len(items), 20) - 1, idx + 1)
        elif k == b'\r':
            return items[idx]

def spin(stop, msg_box):
    for c in itertools.cycle("|/-\\"):
        if stop.is_set(): break
        sys.stdout.write(f"\r  {c}  {msg_box[0]}  ")
        sys.stdout.flush()
        time.sleep(0.1)
    sys.stdout.write("\r" + " " * 50 + "\r")
    sys.stdout.flush()

def check_stream(url, headers_dict, ffmpeg):
    header_args = []
    if headers_dict:
        h_str = "".join(f"{k}: {v}\r\n" for k, v in headers_dict.items())
        header_args = ["-headers", h_str]
    cmd = [ffmpeg] + header_args + [
        "-i", url,
        "-vframes", "1",
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-"
    ]
    try:
        p = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        return p.returncode == 0
    except:
        return False

def fetch_stream(api_url, ffmpeg):
    stop = threading.Event()
    msg_box = ["resolving stream..."]
    threading.Thread(target=spin, args=(stop, msg_box), daemon=True).start()
    try:
        with requests.get(api_url, stream=True, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/event-stream"}) as r:
            for line in r.iter_lines():
                if not line: continue
                line = line.decode()
                if not line.startswith("data:"): continue
                try:
                    obj = json.loads(line[5:].strip())
                    if obj["type"] == "source":
                        src = obj["source"]
                        msg_box[0] = "testing provider stream..."
                        if check_stream(src["url"], src.get("headers", {}), ffmpeg):
                            stop.set()
                            time.sleep(0.15)
                            return src
                        msg_box[0] = "resolving stream..."
                    if obj["type"] == "done":
                        stop.set()
                        return None
                except:
                    pass
    finally:
        stop.set()
    return None

def to_ascii(frame, w, h, color):
    frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(4, 4))
    gray = clahe.apply(gray)
    blurred = cv2.GaussianBlur(gray, (0, 0), 0.4)
    gray = np.clip(cv2.addWeighted(gray, 2.5, blurred, -1.5, 0), 0, 255).astype(np.uint8)
    charset_len = len(ASCII_CHARSET) - 1
    idx = (gray.astype(np.float32) / 255 * charset_len).astype(np.int32)
    if not color:
        return "\n".join("".join(ASCII_CHARSET[idx[y, x]] for x in range(w)) for y in range(h))
    r = frame[:, :, 2]
    g = frame[:, :, 1]
    b_ch = frame[:, :, 0]
    lines = []
    for y in range(h):
        row = []
        for x in range(w):
            c = ASCII_CHARSET[idx[y, x]]
            if c == ' ':
                row.append(' ')
            else:
                row.append(f"\033[38;2;{r[y,x]};{g[y,x]};{b_ch[y,x]}m{c}")
        lines.append("".join(row))
    return "\n".join(lines) + "\033[0m"

def play(stream_url, headers_dict, ffmpeg, ffplay):
    header_args = []
    if headers_dict:
        h_str = "".join(f"{k}: {v}\r\n" for k, v in headers_dict.items())
        header_args = ["-headers", h_str]

    buf = queue.Queue(maxsize=4)
    paused = threading.Event()
    seek_delta = [0]
    volume = [100]
    quit_flag = [False]
    current_time = [0.0]
    audio_proc = [None]
    color_mode = [True]
    term_size = [terminal_size()]

    def size_watcher():
        while not quit_flag[0]:
            term_size[0] = terminal_size()
            time.sleep(0.5)

    threading.Thread(target=size_watcher, daemon=True).start()

    def start_audio(pos, vol):
        if audio_proc[0]:
            try: audio_proc[0].kill()
            except: pass
        cmd = [ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", "-ss", str(pos), "-volume", str(vol)]
        if header_args: cmd += header_args
        cmd += [stream_url]
        audio_proc[0] = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def decode():
        offset = [0.0]
        fsize = 1920 * 1080 * 3
        while not quit_flag[0]:
            start_offset = offset[0]
            start_audio(start_offset, volume[0])
            cmd = [ffmpeg]
            if start_offset > 0:
                cmd += ["-ss", str(start_offset)]
            if header_args:
                cmd += header_args
            cmd += [
                "-i", stream_url,
                "-vf", "fps=24,scale=1920:1080",
                "-f", "rawvideo", "-pix_fmt", "bgr24",
                "-an", "-"
            ]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            frames_decoded = [0]
            try:
                while not quit_flag[0]:
                    if paused.is_set():
                        time.sleep(0.05)
                        continue
                    if seek_delta[0] != 0:
                        offset[0] = max(0, start_offset + frames_decoded[0] / 24 + seek_delta[0])
                        seek_delta[0] = 0
                        proc.kill()
                        break
                    raw = proc.stdout.read(fsize)
                    if len(raw) != fsize:
                        buf.put(None)
                        return
                    frame = np.frombuffer(raw, np.uint8).reshape((1080, 1920, 3))
                    cur = start_offset + frames_decoded[0] / 24
                    current_time[0] = cur
                    try:
                        buf.put((frame, cur), timeout=1)
                    except queue.Full:
                        pass
                    frames_decoded[0] += 1
            finally:
                try: proc.kill()
                except: pass
        buf.put(None)

    threading.Thread(target=decode, daemon=True).start()

    def input_loop():
        while not quit_flag[0]:
            k = msvcrt.getch()
            if k in (b'\x00', b'\xe0'):
                k = msvcrt.getch()
                if k == b'M':
                    seek_delta[0] = 10
                    while not buf.empty():
                        try: buf.get_nowait()
                        except: break
                elif k == b'K':
                    seek_delta[0] = -10
                    while not buf.empty():
                        try: buf.get_nowait()
                        except: break
                elif k == b'H':
                    volume[0] = min(100, volume[0] + 10)
                    start_audio(current_time[0], volume[0])
                elif k == b'P':
                    volume[0] = max(0, volume[0] - 10)
                    start_audio(current_time[0], volume[0])
            elif k == b' ':
                if paused.is_set():
                    paused.clear()
                    start_audio(current_time[0], volume[0])
                else:
                    paused.set()
                    if audio_proc[0]:
                        try: audio_proc[0].kill()
                        except: pass
            elif k in (b'c', b'C'):
                color_mode[0] = not color_mode[0]
            elif k in (b'q', b'Q'):
                quit_flag[0] = True
                buf.put(None)

    threading.Thread(target=input_loop, daemon=True).start()

    sys.stdout.write("\033[2J\033[H\033[?25l")
    sys.stdout.flush()

    t0 = time.perf_counter()
    last_tw, last_th = 0, 0
    frame_str = ""

    try:
        while True:
            item = buf.get(timeout=12)
            if item is None:
                break
            frame, elapsed = item

            if paused.is_set():
                t0 = time.perf_counter() - elapsed
                time.sleep(0.04)
                try: buf.put((frame, elapsed), block=False)
                except: pass
                continue

            target_time = t0 + elapsed
            wait = target_time - time.perf_counter()
            if wait > 0:
                time.sleep(wait)
            elif wait < -0.15:
                t0 = time.perf_counter() - elapsed

            tw, th = term_size[0]
            vw = tw
            vh = max(1, th - 1)

            if tw != last_tw or th != last_th:
                last_tw, last_th = tw, th
                sys.stdout.write("\033[2J\033[H")
                sys.stdout.flush()

            frame_str = to_ascii(frame, vw, vh, color_mode[0])
            sys.stdout.write("\033[H" + frame_str + "\033[J")
            sys.stdout.flush()

    except:
        pass
    finally:
        quit_flag[0] = True
        sys.stdout.write("\033[?25h\033[0m\n")
        sys.stdout.flush()
        if audio_proc[0]:
            try: audio_proc[0].kill()
            except: pass

def main():
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()
    print("\n  Vyla CLI Player\n")
    ffmpeg = find_bin(FFMPEG_CANDIDATES)
    ffplay = find_bin(FFPLAY_CANDIDATES)
    if not ffmpeg or not ffplay:
        missing = []
        if not ffmpeg: missing.append("ffmpeg")
        if not ffplay: missing.append("ffplay")
        print(f"  ERROR: could not find {' and '.join(missing)}.\n")
        print("  Install from https://ffmpeg.org/download.html")
        print("  Then add to PATH or place at C:\\ffmpeg\\bin\\")
        input("\n  Press Enter to exit.")
        return
    q = input("  Search: ").strip()
    if not q: return
    results = search_tmdb(q)
    if not results:
        print("  No results found.")
        return
    item = pick(results)
    tid = item["id"]
    mtype = item["media_type"]
    if mtype == "tv":
        sys.stdout.write("\033[2J\033[H\n")
        sys.stdout.flush()
        s = input("  Season: ").strip()
        e = input("  Episode: ").strip()
        url = f"{BASE_URL}/tv?id={tid}&season={s}&episode={e}"
    else:
        url = f"{BASE_URL}/movie?id={tid}"
    
    stream_data = fetch_stream(url, ffmpeg)
    if not stream_data:
        print("\n  No working stream found.")
        return
        
    stream_url = stream_data.get("url")
    headers_dict = stream_data.get("headers", {})
    
    play(stream_url, headers_dict, ffmpeg, ffplay)

if __name__ == "__main__":
    main()