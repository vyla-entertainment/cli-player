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
import random
from dotenv import load_dotenv

os.system("")
load_dotenv()

TMDB_KEY = os.getenv("TMDB_KEY")
BASE_URL = os.getenv("BASE_URL")
VYLA_API_KEY = os.getenv("VYLA_API_KEY")
ASCII_CHARSET = os.getenv("CHARS", " `.-':_,^=;><+!rc*/z?sLTv)J7(|Fi{C}fI31tlu[neoZ5Yxjya]2ESwqkP6h9d4VpOGbUAKXHm8RD#$Bg0MNWQ%&@")

FFMPEG_CANDIDATES = ["ffmpeg", r"C:\ffmpeg\bin\ffmpeg.exe", r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"]
FFPLAY_CANDIDATES = ["ffplay", r"C:\ffmpeg\bin\ffplay.exe", r"C:\Program Files\ffmpeg\bin\ffplay.exe"]

def find_bin(candidates):
    for path in candidates:
        try:
            subprocess.run([path, "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            return path
        except: pass
    return None

def terminal_size():
    s = shutil.get_terminal_size((120, 40))
    return s.columns, s.lines

def search_tmdb(q):
    r = requests.get("https://api.themoviedb.org/3/search/multi", params={"query": q, "api_key": TMDB_KEY}).json()
    return [x for x in r.get("results", []) if x.get("media_type") != "person"]

def pick(items):
    idx = 0
    while True:
        sys.stdout.write("\033[H\033[J")
        for j, it in enumerate(items[:20]):
            name = it.get("title") or it.get("name")
            year = (it.get("release_date") or it.get("first_air_date") or "")[:4]
            tag = "MOVIE" if it.get("media_type") == "movie" else "  TV "
            mark = "> " if j == idx else "  "
            sys.stdout.write(f"  {mark}[{tag}]  {name}  {year}\n")
        sys.stdout.flush()
        k = msvcrt.getch()
        if k in (b'\x00', b'\xe0'):
            k = msvcrt.getch()
            if k == b'H': idx = max(0, idx - 1)
            elif k == b'P': idx = min(min(len(items), 20) - 1, idx + 1)
        elif k == b'\r': return items[idx]

def spin(stop, msg_box):
    for c in itertools.cycle("|/-\\"):
        if stop.is_set(): break
        sys.stdout.write(f"\r  {c}  {msg_box[0]}  ")
        sys.stdout.flush()
        time.sleep(0.1)
    sys.stdout.write("\r" + " " * 80 + "\r")
    sys.stdout.flush()

def check_stream(url, ffmpeg):
    cmd = [ffmpeg, "-loglevel", "error", "-i", url, "-t", "1", "-f", "null", "-"]
    try:
        p = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=10)
        return p.returncode == 0
    except: return False

def fetch_stream(tid, mtype, s, e, ffmpeg):
    stop = threading.Event()
    msg_box = ["authenticating..."]
    threading.Thread(target=spin, args=(stop, msg_box), daemon=True).start()

    headers = {"User-Agent": "Mozilla/5.0"}
    if VYLA_API_KEY:
        headers["X-API-Key"] = VYLA_API_KEY
    else:
        try:
            r = requests.post(
                f"{BASE_URL}/api/auth",
                headers={"Authorization": f"Bearer {VYLA_API_KEY}"},
                timeout=5
            ).json()
            if "token" in r:
                headers["X-Session-Token"] = r["token"]
        except:
            pass

    try:
        msg_box[0] = "fetching sources..."
        meta = requests.get(f"{BASE_URL}/api?sources_meta=1", headers=headers, timeout=10).json()
        keys = [src["key"] for src in meta.get("sources", [])]
        random.shuffle(keys)
    except:
        stop.set()
        return None

    for k in keys:
        msg_box[0] = f"testing {k}..."
        params = {"source": k}
        if mtype == "tv":
            params["season"] = s
            params["episode"] = e

        try:
            test_url = f"{BASE_URL}/api/test/{tid}"
            res = requests.get(test_url, params=params, headers=headers, timeout=30).json()
            if res.get("ok") and res.get("url"):
                if check_stream(res["url"], ffmpeg):
                    stop.set()
                    return {"url": res["url"], "provider": k}
        except:
            pass

    stop.set()
    return None

def to_ascii(frame, w, h, color):
    frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray)
    idx = (gray.astype(np.float32) / 255 * (len(ASCII_CHARSET)-1)).astype(np.int32)
    if not color: return "\n".join("".join(ASCII_CHARSET[idx[y, x]] for x in range(w)) for y in range(h))
    r, g, b = frame[:,:,2], frame[:,:,1], frame[:,:,0]
    lines = []
    for y in range(h):
        row = []
        for x in range(w):
            c = ASCII_CHARSET[idx[y, x]]
            if c == ' ': row.append(' ')
            else: row.append(f"\033[38;2;{r[y,x]};{g[y,x]};{b[y,x]}m{c}")
        lines.append("".join(row))
    return "\n".join(lines) + "\033[0m"

def play(stream_url, ffmpeg, ffplay):
    buf, paused, quit_flag = queue.Queue(maxsize=4), threading.Event(), [False]
    seek, volume, cur_t, audio_p, color = [0], [100], [0.0], [None], [True]
    def start_a(p, v):
        if audio_p[0]:
            try: audio_p[0].kill()
            except: pass
        cmd = [ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", "-ss", str(p), "-volume", str(v), stream_url]
        audio_p[0] = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    def decode():
        off = [0.0]
        while not quit_flag[0]:
            s_off = off[0]
            start_a(s_off, volume[0])
            cmd = [ffmpeg] + (["-ss", str(s_off)] if s_off > 0 else []) + ["-i", stream_url, "-vf", "fps=24,scale=1280:720", "-f", "rawvideo", "-pix_fmt", "bgr24", "-an", "-"]
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            f_count = 0
            try:
                while not quit_flag[0]:
                    if paused.is_set():
                        time.sleep(0.05)
                        continue
                    if seek[0] != 0:
                        off[0] = max(0, s_off + f_count/24 + seek[0])
                        seek[0] = 0
                        p.kill()
                        break
                    raw = p.stdout.read(1280*720*3)
                    if not raw: break
                    cur_t[0] = s_off + f_count/24
                    try: buf.put((np.frombuffer(raw, np.uint8).reshape((720, 1280, 3)), cur_t[0]), timeout=1)
                    except: pass
                    f_count += 1
            finally:
                try: p.kill()
                except: pass
    threading.Thread(target=decode, daemon=True).start()
    def input_l():
        while not quit_flag[0]:
            if msvcrt.kbhit():
                k = msvcrt.getch()
                if k in (b'\x00', b'\xe0'):
                    k = msvcrt.getch()
                    if k == b'M': seek[0] = 10
                    elif k == b'K': seek[0] = -10
                    elif k == b'H': volume[0] = min(100, volume[0]+10); start_a(cur_t[0], volume[0])
                    elif k == b'P': volume[0] = max(0, volume[0]-10); start_a(cur_t[0], volume[0])
                    while not buf.empty():
                        try: buf.get_nowait()
                        except: break
                elif k == b' ':
                    if paused.is_set(): paused.clear(); start_a(cur_t[0], volume[0])
                    else: paused.set(); audio_p[0].kill() if audio_p[0] else None
                elif k in (b'c', b'C'): color[0] = not color[0]
                elif k in (b'q', b'Q'): quit_flag[0] = True
            time.sleep(0.05)
    threading.Thread(target=input_l, daemon=True).start()
    sys.stdout.write("\033[?25l")
    t0 = time.perf_counter()
    try:
        while not quit_flag[0]:
            try: item = buf.get(timeout=1)
            except queue.Empty: continue
            f, elap = item
            if paused.is_set():
                t0 = time.perf_counter() - elap
                continue
            wait = (t0 + elap) - time.perf_counter()
            if wait > 0: time.sleep(wait)
            elif wait < -0.2: t0 = time.perf_counter() - elap
            tw, th = terminal_size()
            sys.stdout.write("\033[H" + to_ascii(f, tw, th-1, color[0]) + "\033[J")
            sys.stdout.flush()
    finally:
        quit_flag[0] = True
        sys.stdout.write("\033[?25h\033[0m\n")
        if audio_p[0]: audio_p[0].kill()

def main():
    ffmpeg, ffplay = find_bin(FFMPEG_CANDIDATES), find_bin(FFPLAY_CANDIDATES)
    if not ffmpeg or not ffplay: return print("ffmpeg/ffplay not found.")
    q = input("Search: ").strip()
    if not q: return
    res = search_tmdb(q)
    if not res: return print("No results.")
    it = pick(res)
    tid, mtype = it["id"], it["media_type"]
    s, e = None, None
    if mtype == "tv":
        s, e = input("Season: "), input("Episode: ")
    sd = fetch_stream(tid, mtype, s, e, ffmpeg)
    if not sd: return print("\nNo working stream found.")
    play(sd["url"], ffmpeg, ffplay)

if __name__ == "__main__": main()