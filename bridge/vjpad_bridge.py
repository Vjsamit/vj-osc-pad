"""
VJ Pad Bridge  -  Phone (VJ OSC Pad app)  <->  Resolume, same PC par chalta hai.

Phone app isse apne aap dhoondh leta hai (Wi-Fi broadcast), IP type nahi karna.
  phone  --OSC-->  bridge :7010  --> Resolume 127.0.0.1:7000   (Resolume OSC Input)
  Resolume OSC Output 127.0.0.1:7001  --> bridge --> sabhi jude phones
"""
import json, os, socket, struct, sys, threading, time, queue, ctypes

APP = "VJ Pad Bridge"
DISC_PORT = 7099
CFG_PATH = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "VJPadBridge.json")
DEF = {"phone_port": 7010, "res_ip": "127.0.0.1", "res_port": 7000, "fb_port": 7001, "name": socket.gethostname()}


def load_cfg():
    c = dict(DEF)
    try:
        with open(CFG_PATH) as f: c.update(json.load(f))
    except Exception: pass
    return c


def save_cfg(c):
    try:
        with open(CFG_PATH, "w") as f: json.dump(c, f)
    except Exception: pass


def _pad(b): return b + b"\0" * (4 - len(b) % 4)


def osc(addr, *args):
    tags, data = ",", b""
    for a in args:
        if isinstance(a, int): tags += "i"; data += struct.pack(">i", a)
        elif isinstance(a, float): tags += "f"; data += struct.pack(">f", a)
        else: tags += "s"; data += _pad(str(a).encode())
    return _pad(addr.encode()) + _pad(tags.encode()) + data


def osc_addr(b):
    try: return b[:b.index(b"\0")].decode(errors="replace")
    except ValueError: return ""


def osc_first_int(b):
    try:
        i = (b.index(b"\0") + 4) & ~3
        j = b.index(b"\0", i); tags = b[i + 1:j].decode()
        k = (j + 4) & ~3
        if tags[:1] == "i": return struct.unpack(">i", b[k:k + 4])[0]
    except Exception: pass
    return None


def osc_first_num(b):
    try:
        i = (b.index(b"\0") + 4) & ~3
        j = b.index(b"\0", i); tags = b[i + 1:j].decode()
        k = (j + 4) & ~3
        if tags[:1] == "i": return struct.unpack(">i", b[k:k + 4])[0], True
        if tags[:1] == "f": return struct.unpack(">f", b[k:k + 4])[0], False
        if tags[:1] == "T": return 1, True
        if tags[:1] == "F": return 0, True
    except Exception: pass
    return None, False


# ------------------------------------------------------------------ virtual MIDI
class Midi:
    """Creates a virtual MIDI port 'VJ Pad Bridge' (needs loopMIDI's free driver installed),
    or falls back to an existing loopMIDI port whose name contains 'VJ Pad'."""
    NAME = "VJ Pad Bridge"

    def __init__(self, log, on_in):
        self.log, self.on_in = log, on_in
        self.mode, self.port_name = None, ""
        self._port = None; self._dll = None; self._out = None; self._cb = None

    def open(self):
        if os.name == "nt" and self._open_te(): return True
        if self._open_rtmidi(): return True
        self.log("MIDI: virtual port nahi bana. loopMIDI install karo (free): tobias-erichsen.de/software/loopmidi.html")
        return False

    def _open_te(self):
        for n in ("teVirtualMIDI64.dll", "teVirtualMIDI.dll", "teVirtualMIDI32.dll"):
            try:
                dll = ctypes.WinDLL(n); break
            except OSError:
                dll = None
        if dll is None: return False
        try:
            CB = ctypes.WINFUNCTYPE(None, ctypes.c_void_p, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_uint32, ctypes.c_void_p)
            def cb(port, data, length, inst):
                try:
                    if data and length: self.on_in(bytes(data[:length]))
                except Exception: pass
            self._cb = CB(cb)
            create = dll.virtualMIDICreatePortEx2
            create.restype = ctypes.c_void_p
            create.argtypes = [ctypes.c_wchar_p, CB, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
            port = create(self.NAME, self._cb, None, 65535, 1)   # TE_VM_FLAGS_PARSE_RX
            if not port:
                self.log(f"MIDI: driver mila par port nahi bana (error {ctypes.get_last_error() or ctypes.GetLastError()}). Kya '{self.NAME}' naam ka port pehle se khula hai?")
                return False
            dll.virtualMIDISendData.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_uint32]
            dll.virtualMIDISendData.restype = ctypes.c_bool
            self._dll, self._port = dll, port
            self.mode, self.port_name = "virtual", self.NAME
            self.log(f"MIDI: virtual port '{self.NAME}' ban gaya ✔  (Resolume → Preferences → MIDI me ON karo)")
            return True
        except Exception as e:
            self.log(f"MIDI: virtual port error: {e}")
            return False

    def _open_rtmidi(self):
        try:
            import rtmidi
        except Exception:
            return False
        try:
            out = rtmidi.MidiOut()
            ports = out.get_ports()
            idx = next((i for i, n in enumerate(ports) if "vj pad" in n.lower()), None)
            if idx is None:
                idx = next((i for i, n in enumerate(ports) if "loopmidi" in n.lower()), None)
            if idx is None: return False
            out.open_port(idx)
            self._out = out; self.mode, self.port_name = "loopmidi", ports[idx]
            self.log(f"MIDI: loopMIDI port '{ports[idx]}' use ho raha hai ✔ (Resolume me iska MIDI Output OFF rakho)")
            return True
        except Exception as e:
            self.log(f"MIDI: loopMIDI error: {e}")
            return False

    def send(self, msg):
        try:
            if self._port:
                arr = (ctypes.c_ubyte * len(msg))(*msg)
                return self._dll.virtualMIDISendData(self._port, arr, len(msg))
            if self._out:
                self._out.send_message(list(msg)); return True
        except Exception as e:
            self.log(f"MIDI send error: {e}")
        return False

    @staticmethod
    def from_osc(addr, val, is_int):
        # /midi/note/<ch>/<num>   /midi/cc/<ch>/<num>
        parts = addr.split("/")
        if len(parts) != 5: return None
        _, _, kind, ch, num = parts
        try: ch = max(1, min(16, int(ch))) - 1; num = max(0, min(127, int(num)))
        except ValueError: return None
        v = 0 if val is None else val
        if kind == "note":
            if v > 0:
                vel = 127 if (is_int or v >= 1) else max(1, min(127, round(v * 127)))
                return bytes([0x90 | ch, num, vel])
            return bytes([0x80 | ch, num, 0])
        if kind == "cc":
            cv = int(v) if (is_int and v > 1) else round(v * 127)
            return bytes([0xB0 | ch, num, max(0, min(127, cv))])
        return None

    @staticmethod
    def to_osc(msg):
        if len(msg) < 3: return None
        st, ch = msg[0] & 0xF0, (msg[0] & 0x0F) + 1
        if st == 0x90: return osc(f"/midi/note/{ch}/{msg[1]}", int(msg[2]))
        if st == 0x80: return osc(f"/midi/note/{ch}/{msg[1]}", 0)
        if st == 0xB0: return osc(f"/midi/cc/{ch}/{msg[1]}", float(msg[2] / 127.0))
        return None


def lan_ips():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("8.8.8.8", 80)); ips.add(s.getsockname()[0]); s.close()
    except OSError: pass
    try:
        for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET): ips.add(i[4][0])
    except OSError: pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


class Bridge:
    def __init__(self, cfg, log):
        self.cfg, self.log = cfg, log
        self.phones = {}          # ip -> {"port": fb, "last": t, "n": msgs}
        self.res_last = 0
        self.to_res = 0; self.to_phone = 0
        self.lock = threading.Lock()
        self.tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.ok = True
        self.to_midi = 0
        self.midi = Midi(log, self.midi_in)

    def _bind(self, port, bcast=False):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if bcast: s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.bind(("0.0.0.0", port))
        return s

    def start(self):
        for name, port, fn, bc in (("discovery", DISC_PORT, self.disc_loop, True),
                                   ("phone", self.cfg["phone_port"], self.phone_loop, False),
                                   ("resolume", self.cfg["fb_port"], self.res_loop, False)):
            try:
                s = self._bind(port, bc)
            except OSError as e:
                self.ok = False
                self.log(f"ERROR: port {port} ({name}) nahi khula: {e}. Koi aur program to use nahi kar raha?")
                continue
            threading.Thread(target=fn, args=(s,), daemon=True).start()
        threading.Thread(target=self.probe_loop, daemon=True).start()
        self.midi.open()
        self.log(f"Bridge chalu. PC: {self.cfg['name']}  IP: {', '.join(lan_ips()) or '?'}")

    def disc_loop(self, s):
        while True:
            try:
                b, (ip, port) = s.recvfrom(2048)
                if b.startswith(b"VJPAD_DISCOVER"):
                    s.sendto(f"VJPAD_BRIDGE|{self.cfg['name']}|{self.cfg['phone_port']}".encode(), (ip, port))
            except OSError: time.sleep(0.2)

    def phone_loop(self, s):
        res = (self.cfg["res_ip"], self.cfg["res_port"])
        while True:
            try:
                b, (ip, port) = s.recvfrom(65535)
            except OSError:
                time.sleep(0.05); continue
            a = osc_addr(b)
            now = time.time()
            with self.lock:
                new = ip not in self.phones
                p = self.phones.setdefault(ip, {"port": self.cfg["fb_port"], "last": now, "n": 0})
                p["last"] = now
            if new: self.log(f"Phone juda: {ip}")
            if a == "/vjpad/ping":
                fb = osc_first_int(b)
                if fb: p["port"] = fb
                try: self.tx.sendto(osc("/vjpad/pong", 1 if self.res_alive() else 0), (ip, p["port"]))
                except OSError: pass
                continue
            p["n"] += 1
            if a.startswith("/midi/"):
                v, is_int = osc_first_num(b)
                m = Midi.from_osc(a, v, is_int)
                if m and self.midi.send(m): self.to_midi += 1
                continue
            try:
                self.tx.sendto(b, res); self.to_res += 1
            except OSError as e:
                self.log(f"Resolume ko bhejne me error: {e}")

    def res_loop(self, s):
        while True:
            try:
                b, _ = s.recvfrom(65535)
            except OSError:
                time.sleep(0.05); continue
            self.res_last = time.time()
            with self.lock:
                targets = [(ip, p["port"]) for ip, p in self.phones.items() if time.time() - p["last"] < 15]
            for t in targets:
                try: self.tx.sendto(b, t); self.to_phone += 1
                except OSError: pass

    def midi_in(self, data):
        # Resolume MIDI feedback -> phones
        i, n = 0, len(data)
        while i < n:
            st = data[i]
            if st & 0x80 and (st & 0xF0) in (0x80, 0x90, 0xB0) and i + 2 < n:
                pkt = Midi.to_osc(data[i:i + 3])
                if pkt: self._to_phones(pkt)
                i += 3
            else:
                i += 1

    def _to_phones(self, pkt):
        with self.lock:
            targets = [(ip, p["port"]) for ip, p in self.phones.items() if time.time() - p["last"] < 15]
        for t in targets:
            try: self.tx.sendto(pkt, t)
            except OSError: pass

    def probe_loop(self):
        while True:
            try: self.tx.sendto(osc("/composition/master", "?"), (self.cfg["res_ip"], self.cfg["res_port"]))
            except OSError: pass
            with self.lock:
                for ip in [ip for ip, p in self.phones.items() if time.time() - p["last"] > 20]:
                    del self.phones[ip]; self.log(f"Phone hata: {ip}")
            time.sleep(2)

    def res_alive(self): return time.time() - self.res_last < 6

    def status(self):
        with self.lock:
            ph = [(ip, int(time.time() - p["last"])) for ip, p in self.phones.items()]
        return self.res_alive(), ph


# ------------------------------------------------------------------ Windows autostart
def autostart(enable=None):
    if os.name != "nt": return False
    import winreg
    key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    exe = sys.executable if getattr(sys, "frozen", False) else f'"{sys.executable}" "{os.path.abspath(__file__)}"'
    if getattr(sys, "frozen", False): exe = f'"{exe}" --min'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_ALL_ACCESS) as k:
        if enable is None:
            try: winreg.QueryValueEx(k, APP); return True
            except OSError: return False
        if enable: winreg.SetValueEx(k, APP, 0, winreg.REG_SZ, exe)
        else:
            try: winreg.DeleteValue(k, APP)
            except OSError: pass
        return enable


# ------------------------------------------------------------------ GUI
def run_gui():
    import tkinter as tk
    from tkinter import ttk
    cfg = load_cfg()
    logq = queue.Queue()
    log = lambda m: logq.put(time.strftime("%H:%M:%S  ") + m)
    br = Bridge(cfg, log); br.start()

    BG, PN, TX, DIM, ACC, OK, BAD = "#0b0b12", "#15151f", "#ececf6", "#8a8aa6", "#ff2e88", "#2bff88", "#ff4060"
    root = tk.Tk(); root.title(APP); root.configure(bg=BG); root.geometry("540x680"); root.minsize(460, 480)
    try: root.iconbitmap(default=os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(__file__)), "icon.ico"))
    except Exception: pass
    F = ("Segoe UI", 10); FB = ("Segoe UI Semibold", 11); FH = ("Segoe UI Semibold", 16)

    tk.Label(root, text="VJ PAD BRIDGE", font=FH, fg=ACC, bg=BG).pack(anchor="w", padx=16, pady=(14, 0))
    tk.Label(root, text="Phone app ↔ Resolume.  Ye window chalu rakhein.", font=F, fg=DIM, bg=BG).pack(anchor="w", padx=16)

    def card(title):
        f = tk.Frame(root, bg=PN, highlightthickness=1, highlightbackground="#26263a"); f.pack(fill="x", padx=14, pady=6)
        tk.Label(f, text=title, font=("Segoe UI", 9), fg=DIM, bg=PN).pack(anchor="w", padx=10, pady=(6, 0))
        return f
    c1 = card("RESOLUME")
    res_l = tk.Label(c1, font=FB, bg=PN, fg=TX, anchor="w", justify="left"); res_l.pack(fill="x", padx=10, pady=(2, 8))
    c2 = card("PHONE")
    ph_l = tk.Label(c2, font=FB, bg=PN, fg=TX, anchor="w", justify="left"); ph_l.pack(fill="x", padx=10, pady=(2, 8))
    cm = card("MIDI  (Resolume → Shortcuts → Edit MIDI se map karo)")
    midi_l = tk.Label(cm, font=FB, bg=PN, fg=TX, anchor="w", justify="left"); midi_l.pack(fill="x", padx=10, pady=(2, 4))
    def get_loop():
        import webbrowser; webbrowser.open("https://www.tobias-erichsen.de/software/loopmidi.html")
    def retry():
        if not br.midi.mode: br.midi.open()
    mb = tk.Frame(cm, bg=PN); mb.pack(fill="x", padx=10, pady=(0, 8))
    lbtn = tk.Button(mb, text="loopMIDI download (ek baar install)", command=get_loop, bg="#2a1a00", fg=TX, relief="flat", font=F, activebackground="#3a2a10")
    rbtn = tk.Button(mb, text="Dobara try", command=retry, bg="#1b1b2a", fg=TX, relief="flat", font=F)
    c3 = card("IS PC KI JAANKARI")
    tk.Label(c3, text=f"Naam: {cfg['name']}     IP: {', '.join(lan_ips()) or '?'}", font=F, bg=PN, fg=TX).pack(anchor="w", padx=10)
    tk.Label(c3, text=f"Resolume → Preferences → OSC:\n   OSC Input  ON  port {cfg['res_port']}\n   OSC Output ON  IP 127.0.0.1  port {cfg['fb_port']}",
             font=("Consolas", 9), bg=PN, fg=DIM, justify="left").pack(anchor="w", padx=10, pady=(4, 8))

    opt = tk.Frame(root, bg=BG); opt.pack(fill="x", padx=14, pady=(2, 2))
    av = tk.BooleanVar(value=autostart() if os.name == "nt" else False)
    def tog(): autostart(av.get()); log("Windows ke saath start: " + ("ON" if av.get() else "OFF"))
    tk.Checkbutton(opt, text="Windows ke saath apne aap chalu ho", variable=av, command=tog, font=F, bg=BG, fg=TX,
                   selectcolor=PN, activebackground=BG, activeforeground=TX).pack(anchor="w")

    lg = tk.Text(root, height=8, bg="#08080d", fg=DIM, font=("Consolas", 9), relief="flat", highlightthickness=0)
    lg.pack(fill="both", expand=True, padx=14, pady=(6, 14))

    def tick():
        alive, ph = br.status()
        res_l.config(text=("●  Juda hua  (feedback aa raha hai)" if alive else "●  Feedback nahi aa raha – Resolume chalu hai? OSC Output = 127.0.0.1 : %d ?" % cfg["fb_port"]),
                     fg=OK if alive else BAD)
        ph_l.config(text=("●  " + "\n●  ".join(f"{ip}" for ip, _ in ph)) if ph else "●  Koi phone nahi – app kholo (same Wi-Fi), Auto mode",
                    fg=OK if ph else BAD)
        if br.midi.mode:
            midi_l.config(text=f"●  MIDI port: {br.midi.port_name}   ({br.to_midi} msgs)", fg=OK); lbtn.pack_forget(); rbtn.pack_forget()
        else:
            midi_l.config(text="●  MIDI port nahi – loopMIDI install karo, phir 'Dobara try'", fg=BAD)
            if not lbtn.winfo_ismapped(): lbtn.pack(side="left"); rbtn.pack(side="left", padx=6)
        while not logq.empty():
            lg.insert("end", logq.get() + "\n"); lg.see("end")
        root.after(700, tick)
    tick()
    if "--min" in sys.argv: root.iconify()
    root.mainloop()


if __name__ == "__main__":
    if "--nogui" in sys.argv:
        b = Bridge(load_cfg(), print); b.start()
        while True:
            time.sleep(5); print("resolume:", b.res_alive(), "phones:", b.status()[1], "->res", b.to_res, "->phone", b.to_phone)
    else:
        run_gui()
