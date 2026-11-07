"""
VJ Chaser Editor - opens the editor UI in an app window (Edge/Chrome) and handles files.
Data the Resolume plugin reads:  %APPDATA%\\VJChaser\\chaser.vjc
Project (editor state):          %APPDATA%\\VJChaser\\project.json
"""
import json, os, sys, threading, time, socket, subprocess, webbrowser, shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

APPDIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "VJChaser")
os.makedirs(APPDIR, exist_ok=True)
VJC = os.path.join(APPDIR, "chaser.vjc")
PROJ = os.path.join(APPDIR, "project.json")
HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
last_seen = time.time()


def docs_dir():
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)   # CSIDL_PERSONAL
            if buf.value: return buf.value
        except Exception: pass
    return os.path.join(os.path.expanduser("~"), "Documents")


def resolume_xml_candidates():
    d = docs_dir(); out = []
    for app in ("Resolume Arena", "Resolume Avenue"):
        p = os.path.join(d, app, "Preferences", "AdvancedOutput.xml")
        if os.path.exists(p): out.append(p)
        pre = os.path.join(d, app, "Presets", "Advanced Output")
        if os.path.isdir(pre):
            for f in sorted(os.listdir(pre)):
                if f.lower().endswith(".xml"): out.append(os.path.join(pre, f))
    return out


def write_vjc(proj):
    w, h = proj.get("comp", [1920, 1080])
    w = w or 1920; h = h or 1080
    lines = ["VJC 1", f"S {len(proj.get('slices', []))}"]
    for s in proj.get("slices", []):
        q = s["quad"]
        lines.append(" ".join(f"{(q[i] / w if i % 2 == 0 else q[i] / h):.6f}" for i in range(8)))
    seqs = proj.get("seqs", [])
    lines.append(f"Q {len(seqs)}")
    for sq in seqs:
        lines.append("N " + (sq.get("name") or "Sequence").replace("\n", " "))
        steps = sq.get("steps", [])
        lines.append(f"T {len(steps)}")
        for st in steps:
            lines.append(" ".join([str(len(st))] + [str(int(i)) for i in st]))
    tmp = VJC + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: f.write("\n".join(lines) + "\n")
    os.replace(tmp, VJC)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, str): body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        global last_seen
        last_seen = time.time()
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "editor.html"), "rb") as f: return self._send(200, f.read(), "text/html; charset=utf-8")
        if u.path == "/api/project":
            if os.path.exists(PROJ):
                with open(PROJ, "rb") as f: return self._send(200, f.read())
            return self._send(200, "null")
        if u.path == "/api/xmllist":
            return self._send(200, json.dumps(resolume_xml_candidates()))
        if u.path == "/api/xml":
            p = parse_qs(u.query).get("path", [""])[0]
            if p in resolume_xml_candidates():
                with open(p, "rb") as f: return self._send(200, f.read(), "text/xml")
            return self._send(404, "{}")
        if u.path == "/api/ping":
            return self._send(200, json.dumps({"vjc": VJC}))
        self._send(404, "{}")

    def do_POST(self):
        global last_seen
        last_seen = time.time()
        n = int(self.headers.get("Content-Length", "0") or 0)
        data = self.rfile.read(n)
        if self.path == "/api/save":
            try:
                proj = json.loads(data.decode("utf-8"))
                tmp = PROJ + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f: json.dump(proj, f)
                os.replace(tmp, PROJ)
                write_vjc(proj)
                return self._send(200, json.dumps({"ok": True, "path": VJC}))
            except Exception as e:
                return self._send(500, json.dumps({"ok": False, "error": str(e)}))
        self._send(404, "{}")


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def open_window(url):
    if os.name == "nt":
        cands = [os.path.join(os.environ.get(k, ""), *rel) for k, rel in (
            ("ProgramFiles(x86)", ("Microsoft", "Edge", "Application", "msedge.exe")),
            ("ProgramFiles", ("Microsoft", "Edge", "Application", "msedge.exe")),
            ("ProgramFiles", ("Google", "Chrome", "Application", "chrome.exe")),
            ("ProgramFiles(x86)", ("Google", "Chrome", "Application", "chrome.exe")),
            ("LOCALAPPDATA", ("Google", "Chrome", "Application", "chrome.exe")))]
        prof = os.path.join(APPDIR, "browser-profile")
        for c in cands:
            if c and os.path.exists(c):
                subprocess.Popen([c, f"--app={url}", f"--user-data-dir={prof}", "--window-size=1400,860", "--no-first-run"])
                return
    webbrowser.open(url)


def main():
    port = int(os.environ.get("VJCHASER_PORT", "0")) or free_port()
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"
    print("VJ Chaser Editor:", url)
    if "--no-window" not in sys.argv: open_window(url)
    # quit when the window has been closed for a while (page pings every 2 s)
    while True:
        time.sleep(3)
        if "--no-window" not in sys.argv and time.time() - last_seen > 20:
            break
    srv.shutdown()


if __name__ == "__main__":
    main()
