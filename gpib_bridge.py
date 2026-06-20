#!/usr/bin/env python3
"""
NI GPIB-USB-HS -> Prologix Protocol TCP Bridge
System tray application with scrollable log window.
Automatic GPIB board and HP 3458A detection on startup.

Listens on all interfaces (0.0.0.0). Use 127.0.0.1 when TestController
runs on the same machine, or the server's LAN IP for remote access.

TestController setup (GPIB interfaces -> Add):
  Type:       PrologixEthernet
  Connection: Socket  ->  <server IP> : 1234
  Address:    0
"""

import socket
import threading
import ctypes
import sys
import tkinter as tk
from tkinter import scrolledtext
import pystray
from PIL import Image, ImageDraw
import queue
import time

LISTEN_HOST   = '0.0.0.0'
LISTEN_PORT   = 1234
NI4882_DLL    = r"C:\Windows\System32\ni4882.dll"
T100s         = 15   # ~100s timeout  (1000 NPLC / 50 Hz / AZ ON = 40 s)
T10s          = 13   # ~10s timeout
T300ms        = 10   # ~300ms timeout
T100ms        = 9    # ~100ms timeout
ERR           = 0x8000
MAX_LOG_LINES = 300
AUTO_SCAN     = True

# Automatikusan felismert értékek (scan_gpib() tölti ki)
detected_board = 0
detected_addr  = 22

log_queue = queue.Queue()

def log(msg: str):
    ts = time.strftime("%H:%M:%S")
    log_queue.put(f"[{ts}] {msg}")


# ─────────────────────────────────────────────
#  NI-488.2 betöltése
# ─────────────────────────────────────────────
try:
    _lib = ctypes.WinDLL(NI4882_DLL)
except OSError as exc:
    _lib = None
    _lib_error = str(exc)
else:
    _lib_error = None
    _lib.ibdev.restype  = ctypes.c_int
    _lib.ibdev.argtypes = [ctypes.c_int] * 6
    _lib.ibwrt.restype  = ctypes.c_int
    _lib.ibwrt.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_long]
    _lib.ibrd.restype   = ctypes.c_int
    _lib.ibrd.argtypes  = [ctypes.c_int, ctypes.c_char_p, ctypes.c_long]
    _lib.ibclr.restype  = ctypes.c_int
    _lib.ibclr.argtypes = [ctypes.c_int]
    _lib.ibonl.restype  = ctypes.c_int
    _lib.ibonl.argtypes = [ctypes.c_int, ctypes.c_int]
    _lib.ibloc.restype  = ctypes.c_int
    _lib.ibloc.argtypes = [ctypes.c_int]
    _lib.ibsic.restype  = ctypes.c_int
    _lib.ibsic.argtypes = [ctypes.c_int]
    _lib.ibtrg.restype  = ctypes.c_int
    _lib.ibtrg.argtypes = [ctypes.c_int]


# ─────────────────────────────────────────────
#  NI-488.2 hibakód nevek + segédfüggvények
# ─────────────────────────────────────────────
_iberr_sym = {
    0: 'EDVR', 1: 'ECIC',  2: 'ENOP',  3: 'EADR',  4: 'EARG',
    5: 'ENOL', 6: 'EBUS',  7: 'ECAP',  8: 'EFSO',  9: 'EABO',
   10: 'ENEB', 11: 'EDMA', 12: 'EOIP', 14: 'ETAB', 17: 'ELCK', 21: 'EARM',
}

def get_iberr():
    """Visszaadja az NI-488.2 iberr globális hibakódot.
    Modern ni4882.dll-ben a thread-local szimbolum neve ThreadIberr."""
    for sym in ("ThreadIberr", "Iberr"):
        try:
            code = ctypes.c_int.in_dll(_lib, sym).value
            return _iberr_sym.get(code, code)
        except OSError:
            pass
    return "?"

def get_count():
    """Visszaadja az utolsó ibrd által ténylegesen olvasott bájtszámot."""
    for sym in ("ThreadIbcntl", "Ibcntl"):
        try:
            return ctypes.c_long.in_dll(_lib, sym).value
        except OSError:
            pass
    return -1

def ms_to_tmo(ms):
    """Milliszekundum értéket NI-488.2 timeout konstansra képez le."""
    for limit, tmo in [(1,1),(3,2),(10,3),(30,4),(100,5),(300,6),
                       (1000,7),(3000,8),(10000,9),(30000,10),(100000,11)]:
        if ms <= limit:
            return tmo
    return 13


# ─────────────────────────────────────────────
#  NI-488.2 wrapper
# ─────────────────────────────────────────────
def ni_open(board, addr, tmo=T100s):
    ud = _lib.ibdev(board, addr, 0, tmo, 1, 0)
    if ud < 0:
        raise OSError(f"ibdev hiba (board={board}, addr={addr}, ud={ud})")
    return ud

def ni_write(ud, cmd):
    if not cmd.endswith('\n'):
        cmd += '\n'
    data = cmd.encode('ascii')
    sta = _lib.ibwrt(ud, data, len(data))
    if sta & ERR:
        raise OSError(f"ibwrt hiba (sta=0x{sta:04X}, iberr={get_iberr()})")

def ni_read(ud, max_bytes=4096):
    buf = ctypes.create_string_buffer(max_bytes)
    sta = _lib.ibrd(ud, buf, max_bytes)
    if sta & ERR:
        raise OSError(f"ibrd hiba (sta=0x{sta:04X}, iberr={get_iberr()})")
    n = get_count()
    data = buf.raw[:n] if n > 0 else buf.raw.rstrip(b'\x00')
    return data.decode('ascii', errors='replace').strip()

def ni_clear(ud):
    sta = _lib.ibclr(ud)
    if sta & ERR:
        raise OSError(f"  ibclr hiba (sta=0x{sta:04X}, iberr={get_iberr()})")

def ni_close(ud):
    sta = _lib.ibonl(ud, 0)
    if sta & ERR:
        raise OSError(f"  ibonl hiba (sta=0x{sta:04X}, iberr={get_iberr()})")

def ni_local(ud):
    sta = _lib.ibloc(ud)
    if sta & ERR:
        raise OSError(f"  ibloc hiba (sta=0x{sta:04X}, iberr={get_iberr()})")

def ni_ifc(board):
    sta = _lib.ibsic(board)
    if sta & ERR:
        raise OSError(f"  ibsic hiba (sta=0x{sta:04X}, iberr={get_iberr()})")

def ni_trigger(ud):
    sta = _lib.ibtrg(ud)
    if sta & ERR:
        raise OSError(f"  ibtrg hiba (sta=0x{sta:04X}, iberr={get_iberr()})")

def ni_flush_buffer(board, addr, max_reads=200):
    """Rövid timeout-os handle-lel kiüríti az eszköz output bufferét."""
    try:
        ud_f = _lib.ibdev(board, addr, 0, T300ms, 1, 0)
        if ud_f < 0:
            log(f"  flush: ibdev sikertelen (board={board}, addr={addr})")
            return
        count = 0
        for _ in range(max_reads):
            buf = ctypes.create_string_buffer(4096)
            sta = _lib.ibrd(ud_f, buf, 4096)
            if sta & ERR:
                break
            val = buf.raw.rstrip(b'\x00').decode('ascii', errors='replace').strip()
            log(f"  flush eldobva: {val!r}")
            count += 1
        _lib.ibonl(ud_f, 0)
        log(f"  flush kesz: {count} elem torolve")
    except Exception as e:
        log(f"  flush hiba: {e}")


# ─────────────────────────────────────────────
#  Automatikus GPIB felismerés
# ─────────────────────────────────────────────
def scan_gpib():
    """Megkeresi a GPIB boardot és az azon lévő HP 3458A-t."""
    global detected_board, detected_addr

    if _lib is None:
        log(f"SCAN HIBA: ni4882.dll nem tolthetö be: {_lib_error}")
        return

    log("Muszerkeres folyamatban...")

    for board in range(4):
        ud_test = _lib.ibdev(board, 30, 0, T100ms, 1, 0)
        if ud_test < 0:
            continue
        _lib.ibonl(ud_test, 0)
        _lib.ibsic(board)

        for addr in range(1, 31):
            try:
                ud = _lib.ibdev(board, addr, 0, T100ms, 1, 0)
                if ud < 0:
                    continue

                data = b"ID?\n"
                sta_w = _lib.ibwrt(ud, data, len(data))
                if sta_w & ERR:
                    _lib.ibonl(ud, 0)
                    continue

                buf = ctypes.create_string_buffer(256)
                sta_r = _lib.ibrd(ud, buf, 256)
                _lib.ibonl(ud, 0)

                if sta_r & ERR:
                    continue

                resp = buf.raw.rstrip(b'\x00').decode('ascii', errors='replace').strip()

                if 'HP3458A' in resp or '3458A' in resp:
                    log(f"Muszerkeres kesz: GPIB{board} addr={addr}  ({resp})")
                    detected_board = board
                    detected_addr  = addr
                    return

            except Exception:
                continue

    log(f"Muszerkeres: HP 3458A nem talalhato, alapertelmezett GPIB{detected_board} addr={detected_addr}")


# ─────────────────────────────────────────────
#  Kliens szál
# ─────────────────────────────────────────────
class ClientHandler(threading.Thread):
    def __init__(self, conn, addr):
        super().__init__(daemon=True)
        self.conn       = conn
        self.addr       = addr
        self.gpib_addr  = detected_addr
        self.auto_read  = 0
        self.read_tmo   = T100s
        self._read_buf  = []

    def _send(self, text):
        if not text.endswith('\n'):
            text += '\n'
        self.conn.sendall(text.encode('ascii', errors='replace'))

    def _do_hp3458_init(self):
        """HP 3458A inicializálása: CLR + buffer flush. Csak ++hp3458_init hívja."""
        log(f"HP3458 INIT: GPIB{detected_board} addr={self.gpib_addr}")
        try:
            log("  ibclr (Device Clear) kuldese...")
            ud = ni_open(detected_board, self.gpib_addr)
            ni_clear(ud)
            ni_close(ud)
            log("  Buffer flush indul...")
            ni_flush_buffer(detected_board, self.gpib_addr)
            log("  HP3458 INIT KESZ")
        except Exception as e:
            log(f"HP3458 INIT HIBA: {e}")

    def _handle_prologix(self, cmd):
        parts = cmd[2:].strip().split(None, 1)
        pcmd  = parts[0].lower() if parts else ''
        parg  = parts[1].strip() if len(parts) > 1 else ''

        if pcmd == 'addr':
            if parg:
                new_addr = int(parg.split()[0])
                log(f"++addr {new_addr} (volt: {self.gpib_addr})")
                self.gpib_addr = new_addr
            else:
                self._send(str(self.gpib_addr))

        elif pcmd == 'read':
            if self._read_buf:
                resp = self._read_buf.pop(0)
                log(f"++read <- buffered: {resp!r}")
                self._send(resp)
            else:
                log(f"++read -> ibrd (GPIB{detected_board} addr={self.gpib_addr})")
                try:
                    ud = ni_open(detected_board, self.gpib_addr, self.read_tmo)
                    resp = ni_read(ud)
                    ni_close(ud)
                    log(f"  <- {resp!r}")
                    self._send(resp)
                except Exception as e:
                    log(f"  ++read HIBA: {e}")
                    self._send('ERR')

        elif pcmd == 'clr':
            log("++clr -> ibclr")
            try:
                ud = ni_open(detected_board, self.gpib_addr)
                ni_clear(ud)
                ni_close(ud)
                log("  CLR kesz")
            except Exception as e:
                log(f"  ++clr HIBA: {e}")

        elif pcmd == 'ifc':
            log("++ifc -> ibsic")
            try:
                ni_ifc(detected_board)
                log("  IFC kesz")
            except Exception as e:
                log(f"  ++ifc HIBA: {e}")

        elif pcmd == 'loc':
            log("++loc -> ibloc")
            try:
                ud = ni_open(detected_board, self.gpib_addr)
                ni_local(ud)
                ni_close(ud)
                log("  LOC kesz")
            except Exception as e:
                log(f"  ++loc HIBA: {e}")

        elif pcmd == 'trg':
            log("++trg -> ibtrg")
            try:
                ud = ni_open(detected_board, self.gpib_addr)
                ni_trigger(ud)
                ni_close(ud)
                log("  TRG kesz")
            except Exception as e:
                log(f"  ++trg HIBA: {e}")

        elif pcmd == 'hp3458_init':
            self._do_hp3458_init()

        elif pcmd == 'scan':
            scan_gpib()

        elif pcmd == 'ver':
            self._send("Prologix GPIB-ETHERNET Controller version 1.05")

        elif pcmd in ('mode', 'eos', 'eoi', 'savecfg',
                      'eot_enable', 'eot_char', 'status', 'spoll'):
            pass

        elif pcmd == 'auto':
            if parg:
                self.auto_read = int(parg)
                log(f"++auto {self.auto_read}")

        elif pcmd == 'read_tmo_ms':
            if parg:
                ms = int(parg)
                ni_tmo = ms_to_tmo(ms)
                self.read_tmo = ni_tmo
                log(f"++read_tmo_ms {ms} -> ni_tmo={ni_tmo}")

    def _handle_write(self, cmd):
        log(f"-> TX: {cmd!r}  (GPIB{detected_board} addr={self.gpib_addr})")
        try:
            ud = ni_open(detected_board, self.gpib_addr, self.read_tmo)
            if cmd == 'MREAD':
                try:
                    resp = ni_read(ud)
                    log(f"   <- RX: {resp!r}")
                    self._read_buf.append(resp)
                except Exception as e:
                    log(f"   read HIBA: {e}")
                    self._read_buf.append('ERR')
                ni_close(ud)
            else:
                ni_write(ud, cmd)
                if self.auto_read:
                    try:
                        resp = ni_read(ud)
                        log(f"   <- RX: {resp!r}")
                        self._send(resp)
                    except Exception as e:
                        log(f"   read HIBA: {e}")
                ni_close(ud)
        except Exception as e:
            log(f"   TX HIBA: {e}")

    def run(self):
        log(f"Kapcsolodott: {self.addr[0]}:{self.addr[1]}")
        buf = ""
        try:
            while True:
                data = self.conn.recv(4096)
                if not data:
                    break
                buf += data.decode('ascii', errors='replace')
                while '\n' in buf:
                    line, buf = buf.split('\n', 1)
                    cmd = line.strip()
                    if not cmd:
                        continue
                    if cmd.startswith('++'):
                        self._handle_prologix(cmd)
                    else:
                        self._handle_write(cmd)
        except Exception as e:
            log(f"Kliens hiba: {e}")
        finally:
            self.conn.close()
            log(f"Lecsatlakozott: {self.addr[0]}:{self.addr[1]}")


# ─────────────────────────────────────────────
#  TCP szerver szál
# ─────────────────────────────────────────────
_server_socket = None

def run_server():
    global _server_socket
    if _lib is None:
        log(f"HIBA: ni4882.dll nem tolthetö be: {_lib_error}")
        return

    if AUTO_SCAN:
        scan_gpib()
    else:
        log(f"AUTO_SCAN kikapcsolva, alapertelmezett: GPIB{detected_board} addr={detected_addr}")

    try:
        _server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _server_socket.bind((LISTEN_HOST, LISTEN_PORT))
        _server_socket.listen(5)
        log(f"Bridge indul: {LISTEN_HOST}:{LISTEN_PORT}")
        log(f"Aktiv: GPIB{detected_board}  addr={detected_addr}")
        log(f"TestController: PrologixEthernet, socket <server-IP>:{LISTEN_PORT}, addr 0")
        while True:
            conn, addr = _server_socket.accept()
            ClientHandler(conn, addr).start()
    except Exception as e:
        log(f"Szerver hiba: {e}")


# ─────────────────────────────────────────────
#  Tálca ikon
# ─────────────────────────────────────────────
def make_icon(color):
    img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([4, 4, 60, 60], fill=color)
    return img


# ─────────────────────────────────────────────
#  Log ablak (tkinter)
# ─────────────────────────────────────────────
class LogWindow:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("GPIB Bridge")
        self.root.geometry("620x380")
        self.root.resizable(True, True)
        self.root.protocol("WM_DELETE_WINDOW", self._hide)

        hdr = tk.Frame(self.root, bg="#1e1e1e")
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="NI GPIB-USB-HS -> Prologix Bridge",
                 bg="#1e1e1e", fg="#ffffff",
                 font=("Consolas", 10, "bold")).pack(side=tk.LEFT, padx=8, pady=4)
        self._status = tk.Label(hdr, text="● Fut", bg="#1e1e1e",
                                fg="#4ec94e", font=("Consolas", 10))
        self._status.pack(side=tk.RIGHT, padx=8)

        self.txt = scrolledtext.ScrolledText(
            self.root, state='disabled', bg="#1e1e1e", fg="#d4d4d4",
            font=("Consolas", 9), wrap=tk.NONE, relief=tk.FLAT)
        self.txt.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self._info_var = tk.StringVar(value=f"  {LISTEN_HOST}:{LISTEN_PORT}  |  Indul...")
        info = tk.Frame(self.root, bg="#252526")
        info.pack(fill=tk.X)
        tk.Label(info, textvariable=self._info_var,
                 bg="#252526", fg="#858585", font=("Consolas", 8)).pack(side=tk.LEFT, pady=2)

        self.root.withdraw()
        self._poll()

    def _poll(self):
        try:
            while True:
                msg = log_queue.get_nowait()
                self.txt.configure(state='normal')
                self.txt.insert(tk.END, msg + "\n")
                lines = int(self.txt.index('end-1c').split('.')[0])
                if lines > MAX_LOG_LINES:
                    self.txt.delete('1.0', f'{lines - MAX_LOG_LINES}.0')
                self.txt.configure(state='disabled')
                self.txt.see(tk.END)
        except queue.Empty:
            pass
        self._info_var.set(
            f"  {LISTEN_HOST}:{LISTEN_PORT}  |  GPIB{detected_board}  |  addr={detected_addr}"
        )
        self.root.after(100, self._poll)

    def show(self):
        self.root.deiconify()
        self.root.lift()

    def _hide(self):
        self.root.withdraw()


# ─────────────────────────────────────────────
#  Főprogram
# ─────────────────────────────────────────────
def main():
    t = threading.Thread(target=run_server, daemon=True)
    t.start()

    win = LogWindow()
    win.root.after(500, win.show)

    def on_show(icon, item):
        win.root.after(0, win.show)

    def on_quit(icon, item):
        icon.stop()
        win.root.after(0, win.root.destroy)

    menu = pystray.Menu(
        pystray.MenuItem("Log megnyitasa", on_show, default=True, visible=False),
        pystray.MenuItem("Kilepes", on_quit),
    )

    icon = pystray.Icon("gpib_bridge", make_icon("#4ec94e"), "GPIB Bridge - fut", menu)
    icon_thread = threading.Thread(target=icon.run, daemon=True)
    icon_thread.start()

    win.root.mainloop()


if __name__ == '__main__':
    main()
