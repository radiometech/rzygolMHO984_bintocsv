#!/usr/bin/env python3
"""
MHO984 / RG03 .bin -> CSV / wykres  |  GUI (tkinter)
Format: RG03 (Micsig MHO984), float32, N kanalow
"""

import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext
import threading
import struct
import numpy as np
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from pathlib import Path
import sys, os

# ── szukaj .bin obok skryptu ─────────────────────────────────────
def find_default_bin() -> str:
    here = Path(__file__).parent
    bins = sorted(here.glob('*.bin'))
    return str(bins[0]) if bins else ''


# ── parsowanie naglowka RG03 ─────────────────────────────────────
RG03_MAGIC       = b'RG03'
GLOBAL_HDR_SIZE  = 0x80        # 128 B
CH_HDR_SIZE      = 0x8C        # 140 B  (pole @ 0x10)

def parse_rg03(path: Path) -> dict:
    """Czyta naglowek MHO984 RG03, zwraca parametry konwersji."""
    with open(path, 'rb') as f:
        hdr = f.read(GLOBAL_HDR_SIZE + 4 * CH_HDR_SIZE)

    if hdr[:4] != RG03_MAGIC:
        raise ValueError(f"Nieznany format pliku (oczekiwano RG03, jest {hdr[:4]})")

    num_ch_hdrs = struct.unpack_from('<I', hdr, 0x0C)[0]   # liczba naglowkow kanalow
    ch_hdr_sz   = struct.unpack_from('<I', hdr, 0x10)[0]   # rozmiar naglowka kanalu
    sample_rate = struct.unpack_from('<Q', hdr, 0x1C)[0]   # Sa/s
    date        = hdr[0x48:0x58].decode('ascii', 'replace').rstrip('\x00').strip()
    time_str    = hdr[0x58:0x60].decode('ascii', 'replace').rstrip('\x00').strip()
    model       = hdr[0x68:0x80].decode('ascii', 'replace').rstrip('\x00').strip()

    data_offset = GLOBAL_HDR_SIZE + num_ch_hdrs * ch_hdr_sz
    file_size   = path.stat().st_size
    data_bytes  = file_size - data_offset
    total_f32   = data_bytes // 4   # liczba probek float32 lacznie

    # wykryj liczbe aktywnych kanalow na podstawie rozmiaru danych
    # dane sa rownomiernie podzielone miedzy kanaly
    detected_ch = 4   # domyslnie 4
    for n in [4, 3, 2, 1]:
        if total_f32 % n == 0:
            detected_ch = n
            break

    # nazwy kanalow z naglowkow
    ch_names = []
    for i in range(num_ch_hdrs):
        base = GLOBAL_HDR_SIZE + i * ch_hdr_sz
        if base + 8 <= len(hdr):
            name = hdr[base:base+8].decode('ascii', 'replace').rstrip('\x00').strip()
            if name.isprintable() and name.startswith('CH'):
                ch_names.append(name)

    return {
        'model':       model,
        'date':        f'{date} {time_str}',
        'sample_rate': sample_rate,
        'data_offset': data_offset,
        'data_bytes':  data_bytes,
        'total_f32':   total_f32,
        'num_ch':      detected_ch,
        'ch_names':    ch_names or [f'CH{i+1}' for i in range(detected_ch)],
        'layout':      'sequential',   # sequential lub interleaved
    }


# ── eksport CSV — wszystkie kanaly w jednym pliku ─────────────────
def export_csv_all(path: Path, out: Path, p: dict,
                   decimate: int, log, progress_cb):
    """
    Zapisuje wszystkie kanaly do jednego CSV:
    Time (s), CH1 (V), CH2 (V), ...
    Dziala strumieniowo — pliki 1GB+ nie zapychaja RAM.
    """
    sr  = p['sample_rate']
    off = p['data_offset']
    n   = p['num_ch']
    spc = p['total_f32'] // n   # samples per channel
    dt  = 1.0 / sr

    names = p['ch_names'] + [f'CH{i+1}' for i in range(len(p['ch_names']), n)]
    header_row = 'Time (s),' + ','.join(f'{nm} (V)' for nm in names[:n]) + '\n'

    log(f"Eksport wszystkich kanalow -> {out.name}")
    log(f"Probki/kanal: {spc:,}  |  czas: {spc*dt:.4f} s  |  SR: {sr/1e6:.3f} MSa/s  |  decymacja: {decimate}x")

    CHUNK = 200_000   # probek na raz (per kanal)
    written = 0

    with open(out, 'w', buffering=1 << 20) as fout:
        fout.write(header_row)

        if p['layout'] == 'sequential':
            # otworz osobny uchwyt dla kazdego kanalu
            handles = []
            for c in range(n):
                f = open(path, 'rb')
                f.seek(off + c * spc * 4)
                handles.append(f)

            sample_idx = 0
            try:
                while sample_idx < spc:
                    to_read = min(CHUNK * decimate, spc - sample_idx)
                    chunks = []
                    for f in handles:
                        raw = f.read(to_read * 4)
                        chunks.append(np.frombuffer(raw, dtype='<f4')[::decimate])
                    n_w   = len(chunks[0])
                    times = (np.arange(n_w) * decimate + sample_idx) * dt
                    cols  = np.column_stack(chunks)   # (n_w, n_ch)
                    lines = []
                    for i in range(n_w):
                        vals = ','.join(f'{v:.6g}' for v in cols[i])
                        lines.append(f'{times[i]:.10g},{vals}\n')
                    fout.write(''.join(lines))
                    sample_idx += to_read
                    written    += n_w
                    progress_cb(min(sample_idx / spc * 100, 100))
            finally:
                for f in handles:
                    f.close()

        else:   # interleaved
            with open(path, 'rb') as fin:
                fin.seek(off)
                sample_idx = 0
                while sample_idx < spc:
                    to_read = min(CHUNK * decimate, spc - sample_idx)
                    raw = fin.read(to_read * n * 4)
                    if not raw:
                        break
                    block = np.frombuffer(raw, dtype='<f4').reshape(-1, n)[::decimate]
                    n_w   = len(block)
                    times = (np.arange(n_w) * decimate + sample_idx) * dt
                    lines = []
                    for i in range(n_w):
                        vals = ','.join(f'{v:.6g}' for v in block[i])
                        lines.append(f'{times[i]:.10g},{vals}\n')
                    fout.write(''.join(lines))
                    sample_idx += to_read
                    written    += n_w
                    progress_cb(min(sample_idx / spc * 100, 100))

    log(f"Gotowe -> {out}  ({out.stat().st_size/1e6:.1f} MB, {written:,} wierszy)")

    log(f"Gotowe -> {out}  ({out.stat().st_size/1e6:.1f} MB, {written:,} wierszy)")


# ── wczytanie danych do wykresu (z decymacja) ────────────────────
MAX_PLOT_PTS = 300_000

def load_for_plot(path: Path, p: dict, t_start=None, t_end=None):
    """Zwraca dict {ch_name: (times, volts)} z automatyczna decymacja."""
    sr  = p['sample_rate']
    off = p['data_offset']
    n   = p['num_ch']
    spc = p['total_f32'] // n   # samples per channel
    dt  = 1.0 / sr

    i0 = int(t_start * sr) if t_start is not None else 0
    i1 = int(t_end   * sr) if t_end   is not None else spc
    i0 = max(0, min(i0, spc - 1))
    i1 = max(i0 + 1, min(i1, spc))
    n_range  = i1 - i0
    decimate = max(1, n_range // MAX_PLOT_PTS)

    result = {}
    with open(path, 'rb') as f:
        for c in range(n):
            ch_name = p['ch_names'][c] if c < len(p['ch_names']) else f'CH{c+1}'
            if p['layout'] == 'sequential':
                byte_off = off + c * spc * 4 + i0 * 4
                f.seek(byte_off)
                raw = f.read(n_range * 4)
                data = np.frombuffer(raw, dtype='<f4')[::decimate]
            else:
                f.seek(off + i0 * n * 4)
                raw = f.read(n_range * n * 4)
                data = np.frombuffer(raw, dtype='<f4').reshape(-1, n)[::decimate, c]

            times = (np.arange(len(data)) * decimate + i0) * dt
            result[ch_name] = (times, data)

    return result


# ── kolory kanalow ────────────────────────────────────────────────
CH_COLORS = ['#FFD700', '#00BFFF', '#FF4500', '#7FFF00']


# ── glowne okno ───────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('MHO984  .bin -> CSV / Wykres')
        self.resizable(True, True)
        self.minsize(700, 520)
        self._params = None
        self._build_ui()
        default = find_default_bin()
        if default:
            self.var_file.set(default)
            self.after(100, self._auto_parse)

    # ── UI ────────────────────────────────────────────────────────
    def _build_ui(self):
        pad = dict(padx=8, pady=4)

        # plik
        frm = ttk.LabelFrame(self, text='Plik .bin')
        frm.pack(fill='x', **pad)
        self.var_file = tk.StringVar()
        ttk.Entry(frm, textvariable=self.var_file, width=65).pack(
            side='left', fill='x', expand=True, padx=(4, 2), pady=4)
        ttk.Button(frm, text='Przeglądaj…', command=self._pick).pack(
            side='left', padx=(0, 4), pady=4)
        ttk.Button(frm, text='Wczytaj', command=self._auto_parse).pack(
            side='left', padx=(0, 4), pady=4)

        # info o pliku
        self.frm_info = ttk.LabelFrame(self, text='Plik — info')
        self.frm_info.pack(fill='x', **pad)
        self.lbl_info = ttk.Label(self.frm_info, text='—', justify='left')
        self.lbl_info.pack(anchor='w', padx=6, pady=2)

        # opcje
        frm_o = ttk.LabelFrame(self, text='Opcje')
        frm_o.pack(fill='x', **pad)

        row = ttk.Frame(frm_o); row.pack(fill='x', padx=4, pady=3)
        ttk.Label(row, text='Kanały w danych:').pack(side='left')
        self.var_nch = tk.IntVar(value=4)
        ttk.Spinbox(row, from_=1, to=8, textvariable=self.var_nch, width=4).pack(
            side='left', padx=(2, 16))

        ttk.Label(row, text='Układ danych:').pack(side='left')
        self.var_layout = tk.StringVar(value='sequential')
        ttk.Radiobutton(row, text='sequential', variable=self.var_layout,
                        value='sequential').pack(side='left')
        ttk.Radiobutton(row, text='interleaved', variable=self.var_layout,
                        value='interleaved').pack(side='left', padx=(0, 16))

        ttk.Label(row, text='Decymacja CSV:').pack(side='left')
        self.var_dec = tk.IntVar(value=1)
        ttk.Spinbox(row, from_=1, to=100000, textvariable=self.var_dec, width=8).pack(
            side='left', padx=2)

        row2 = ttk.Frame(frm_o); row2.pack(fill='x', padx=4, pady=2)
        ttk.Label(row2, text='Zakres wykresu  t_start [s]:').pack(side='left')
        self.var_ts = tk.StringVar(value='')
        ttk.Entry(row2, textvariable=self.var_ts, width=10).pack(side='left', padx=(2, 10))
        ttk.Label(row2, text='t_end [s]:').pack(side='left')
        self.var_te = tk.StringVar(value='')
        ttk.Entry(row2, textvariable=self.var_te, width=10).pack(side='left', padx=2)
        ttk.Label(row2, text='(puste = caly plik)').pack(side='left', padx=(6, 0))

        # kanaly do CSV
        row3 = ttk.Frame(frm_o); row3.pack(fill='x', padx=4, pady=2)
        ttk.Label(row3, text='Eksport CSV — kanal:').pack(side='left')
        self.var_ch_csv = tk.IntVar(value=0)
        for i, lbl in enumerate(['CH1', 'CH2', 'CH3', 'CH4']):
            ttk.Radiobutton(row3, text=lbl, variable=self.var_ch_csv,
                            value=i).pack(side='left', padx=2)

        # przyciski
        frm_b = ttk.Frame(self); frm_b.pack(fill='x', **pad)
        ttk.Button(frm_b, text='Pokaż wykres',
                   command=self._run_plot).pack(side='left', padx=4)
        ttk.Button(frm_b, text='Eksport CSV (wszystkie kanały)',
                   command=self._run_csv_all).pack(side='left', padx=4)
        ttk.Button(frm_b, text='Zapisz PNG',
                   command=self._run_png).pack(side='left', padx=4)

        # pasek postepu
        self.progress = ttk.Progressbar(self, mode='determinate')
        self.progress.pack(fill='x', padx=8, pady=2)

        # log
        frm_l = ttk.LabelFrame(self, text='Log')
        frm_l.pack(fill='both', expand=True, **pad)
        self.log_box = scrolledtext.ScrolledText(
            frm_l, height=8, state='disabled', font=('Consolas', 9))
        self.log_box.pack(fill='both', expand=True, padx=4, pady=4)

    # ── helpers ──────────────────────────────────────────────────
    def _log(self, msg):
        self.log_box.config(state='normal')
        self.log_box.insert('end', msg + '\n')
        self.log_box.see('end')
        self.log_box.config(state='disabled')

    def _prog(self, v):
        self.progress['value'] = v
        self.update_idletasks()

    def _pick(self):
        p = filedialog.askopenfilename(
            title='Wybierz plik .bin',
            filetypes=[('Bin', '*.bin'), ('Wszystkie', '*.*')])
        if p:
            self.var_file.set(p)
            self._auto_parse()

    def _auto_parse(self):
        s = self.var_file.get().strip()
        if not s:
            return
        path = Path(s)
        if not path.exists():
            self._log(f'Plik nie istnieje: {path}')
            return
        try:
            p = parse_rg03(path)
            self._params = p
            self.var_nch.set(p['num_ch'])
            sr = p['sample_rate']
            spc = p['total_f32'] // p['num_ch']
            info = (f"Model: {p['model']}   Data: {p['date']}   "
                    f"SR: {sr/1e6:.3f} MSa/s   "
                    f"Kanały: {p['num_ch']}   "
                    f"Próbki/kanał: {spc:,}   "
                    f"Czas: {spc/sr:.4f} s   "
                    f"Dane od: 0x{p['data_offset']:X}")
            self.lbl_info.config(text=info)
            self._log(f'\n[{path.name}]  {info}')
        except Exception as e:
            self._log(f'Błąd parsowania: {e}')

    def _get_params(self):
        if not self._params:
            self._log('Najpierw wczytaj plik.')
            return None
        p = dict(self._params)
        p['num_ch']  = self.var_nch.get()
        p['layout']  = self.var_layout.get()
        return p

    def _get_path(self):
        s = self.var_file.get().strip()
        p = Path(s)
        return p if p.exists() else None

    def _t_range(self):
        def _f(v):
            s = v.get().strip()
            return float(s) if s else None
        return _f(self.var_ts), _f(self.var_te)

    # ── akcje ────────────────────────────────────────────────────
    def _run_plot(self, save_png: Path = None):
        path = self._get_path()
        p    = self._get_params()
        if not path or not p:
            return
        t0, t1 = self._t_range()
        self._log('Wczytywanie…')

        def worker():
            try:
                data = load_for_plot(path, p, t0, t1)

                def draw():
                    win = tk.Toplevel(self)
                    win.title(f'Wykres — {path.name}')
                    win.geometry('1200x600')

                    fig, axes = plt.subplots(
                        p['num_ch'], 1,
                        figsize=(12, 2.5 * p['num_ch']),
                        sharex=True, squeeze=False)

                    for idx, (ch_name, (times, volts)) in enumerate(data.items()):
                        ax = axes[idx][0]
                        ax.plot(times, volts, lw=0.6,
                                color=CH_COLORS[idx % len(CH_COLORS)])
                        ax.set_ylabel(f'{ch_name}\n(V)', fontsize=8)
                        ax.grid(True, alpha=0.25)
                        sr = p['sample_rate']
                        spc = p['total_f32'] // p['num_ch']
                        ax.set_title(
                            f'{ch_name}  |  SR={sr/1e6:.3f} MSa/s  |  '
                            f'{spc/sr*1e3:.2f} ms  |  {len(times):,} pkt',
                            fontsize=8)

                    axes[-1][0].set_xlabel('Czas (s)')
                    fig.tight_layout()

                    if save_png:
                        fig.savefig(save_png, dpi=150)
                        self.after(0, self._log, f'PNG zapisany -> {save_png}')
                        plt.close(fig)
                        win.destroy()
                        return

                    canvas = FigureCanvasTkAgg(fig, master=win)
                    canvas.draw()
                    toolbar = NavigationToolbar2Tk(canvas, win)
                    toolbar.update()
                    canvas.get_tk_widget().pack(fill='both', expand=True)

                self.after(0, draw)
                self.after(0, self._log, f'Wykres gotowy')
            except Exception as e:
                self.after(0, self._log, f'BŁĄD: {e}')
                import traceback; traceback.print_exc()

        threading.Thread(target=worker, daemon=True).start()

    def _run_csv_all(self):
        path = self._get_path()
        p    = self._get_params()
        if not path or not p:
            return
        out = filedialog.asksaveasfilename(
            defaultextension='.csv',
            initialfile=f'{path.stem}_all_channels.csv',
            filetypes=[('CSV', '*.csv')])
        if not out:
            return
        dec = max(1, self.var_dec.get())
        self._prog(0)

        def worker():
            try:
                export_csv_all(path, Path(out), p, dec,
                               log=lambda m: self.after(0, self._log, m),
                               progress_cb=lambda v: self.after(0, self._prog, v))
            except Exception as e:
                self.after(0, self._log, f'BŁĄD CSV: {e}')
                import traceback; traceback.print_exc()

        threading.Thread(target=worker, daemon=True).start()

    def _run_png(self):
        path = self._get_path()
        if not path:
            return
        out = filedialog.asksaveasfilename(
            defaultextension='.png',
            initialfile=path.stem + '.png',
            filetypes=[('PNG', '*.png')])
        if out:
            self._run_plot(save_png=Path(out))


if __name__ == '__main__':
    app = App()
    app.mainloop()
