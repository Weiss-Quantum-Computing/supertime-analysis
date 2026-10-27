# -*- coding: utf-8 -*-
"""Supertime sequence editor: a Tkinter desktop app to view, edit, plot and compare .dt4 files.

Runs on Python 2.7 (Windows XP) and Python 3, standard library only.

    python -m supertime_editor.app [file.dt4]
"""
from __future__ import print_function, division
import os
import sys

try:                                    # Python 3
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, simpledialog
except ImportError:                     # Python 2.7
    import Tkinter as tk
    import ttk
    import tkFileDialog as filedialog
    import tkMessageBox as messagebox
    import tkSimpleDialog as simpledialog

from . import lvcore
from .model import (Sequence, K_NAME, K_CARD, K_CHAN, K_SIG, K_CONV, K_ANLG, K_DIG, K_TC, K_FUNC,
                    K_STEP, E_ABS, E_NAME, E_PARENT, E_REL, E_VARS, E_TYPE, V_NAME, V_VAL, step_us)
from .diff import Comparison, fmt_value

CELL_W = 46            # default column width; adjustable in the toolbar
CELL_H = 20
HDR_H = 110
ROW_HDR_W = 170
TXT = "#000000"        # explicit colours so the grid looks the same in dark mode
C_HDR = "#dfe3ee"
C_ROWHDR = "#ece9d8"
C_EMPTY = "#ffffff"
C_ANALOG = "#bcd4ff"
C_DIG1 = "#9fe09f"
C_DIG0 = "#f4a9a9"
C_RAMP = "#ffd27a"
C_GRIDLINE = "#b8b8b8"
C_SEL = "#e00000"
C_CONFLICT = "#ff40ff"
FUNC_ABBR = {u"": u"", u"Linear": u"L", u"Exponential": u"E", u"Cubic": u"C", u"Custom": u"K",
             u"Optical: 1/(1+t)^2": u"O", u"Optical with offset": u"O+", u"Depth lin freq const": u"D"}
DISPLAY_MODES = [u"value + ramp", u"value + ramp + step", u"step size", u"time constant"]


def abbr_func(f):
    if f in FUNC_ABBR:
        return FUNC_ABBR[f]
    return (f or u"")[:2]


def fnum(v, digits=6):
    if isinstance(v, float):
        if lvcore.is_nan(v):
            return u""
        return (u"%.*g" % (digits, v))
    return u"%s" % (v,)


def fstep(st):
    """Step size in a compact form: 1 -> '1', 0.005 -> '5u', 0.04 -> '40u', 2.5 -> '2.5'."""
    us = st * 1000.0
    if abs(us - round(us)) < 1e-6 and us < 1000:
        return u"%du" % int(round(us))
    return fnum(st, 3)


# ======================================================================= grid widget
class SequenceGrid(tk.Frame):
    """Virtual grid: edges (time order) as columns, channels as rows; only visible cells drawn."""

    def __init__(self, master, app):
        tk.Frame.__init__(self, master)
        self.app = app
        self.seq = None
        self.order = []
        self.col0 = 0
        self.row0 = 0
        self.sel = set()            # selected (channel, edge) cells
        self.anchor = None          # for shift-click ranges
        self.conflicts = set()      # (channel, edge) cells flagged by the ramp check
        self.cell_w = CELL_W
        self.cell_h = CELL_H
        self.canvas = tk.Canvas(self, bg="white", highlightthickness=0)
        self.vbar = tk.Scrollbar(self, orient="vertical", command=self._yscroll)
        self.hbar = tk.Scrollbar(self, orient="horizontal", command=self._xscroll)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vbar.grid(row=0, column=1, sticky="ns")
        self.hbar.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<Shift-Button-1>", self._shift_click)
        self.canvas.bind("<Control-Button-1>", self._ctrl_click)
        self.canvas.bind("<Command-Button-1>", self._ctrl_click)
        self.canvas.bind("<Double-Button-1>", self._dblclick)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Shift-MouseWheel>", self._hwheel)
        self.canvas.bind("<Button-4>", lambda e: self._scroll_rows(-3))
        self.canvas.bind("<Button-5>", lambda e: self._scroll_rows(3))

    def set_sequence(self, seq):
        self.seq = seq
        self.col0 = self.row0 = 0
        self.sel = set()
        self.anchor = None
        self.conflicts = set()
        self.refresh_order()

    def refresh_order(self):
        self.order = self.seq.edge_order() if self.seq else []
        n = len(self.seq.edges) if self.seq else 0
        self.sel = set(c for c in self.sel if c[1] < n and c[0] < len(self.seq.grid))
        self.redraw()

    # ---- geometry
    def _visible(self):
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        ncol = max(1, (w - ROW_HDR_W) // self.cell_w + 1)
        nrow = max(1, (h - HDR_H) // self.cell_h + 1)
        return ncol, nrow

    def _scroll_rows(self, d):
        if not self.seq:
            return
        self.row0 = max(0, min(len(self.seq.grid) - 1, self.row0 + d))
        self.redraw()

    def _scroll_cols(self, d):
        if not self.seq:
            return
        self.col0 = max(0, min(max(0, len(self.order) - 1), self.col0 + d))
        self.redraw()

    def _wheel(self, e):
        self._scroll_rows(-1 if e.delta > 0 else 1)

    def _hwheel(self, e):
        self._scroll_cols(-1 if e.delta > 0 else 1)

    def _yscroll(self, *args):
        n = len(self.seq.grid) if self.seq else 1
        if args[0] == "moveto":
            self.row0 = int(float(args[1]) * n)
        elif args[0] == "scroll":
            step = int(args[1]) * (self._visible()[1] - 1 if args[2] == "pages" else 1)
            self.row0 += step
        self.row0 = max(0, min(max(0, n - 1), self.row0))
        self.redraw()

    def _xscroll(self, *args):
        n = len(self.order) or 1
        if args[0] == "moveto":
            self.col0 = int(float(args[1]) * n)
        elif args[0] == "scroll":
            step = int(args[1]) * (self._visible()[0] - 1 if args[2] == "pages" else 1)
            self.col0 += step
        self.col0 = max(0, min(max(0, n - 1), self.col0))
        self.redraw()

    def scroll_to_edge(self, edge_index):
        if edge_index in self.order:
            self.col0 = max(0, self.order.index(edge_index) - 2)
            self.redraw()

    def _cell_at(self, x, y):
        if x < ROW_HDR_W or y < HDR_H:
            return None
        c = self.col0 + (x - ROW_HDR_W) // self.cell_w
        r = self.row0 + (y - HDR_H) // self.cell_h
        if self.seq and c < len(self.order) and r < len(self.seq.grid):
            return r, self.order[c]
        return None

    def set_cell_width(self, w):
        self.cell_w = max(24, min(160, int(w)))
        self.redraw()

    # ---- drawing
    def cell_text(self, ch, ei, mode, maxchars):
        """(line1, line2, fill, leftover) for one cell under the given display mode."""
        a = Sequence.cell_value(ch, K_ANLG, ei)
        d = Sequence.cell_value(ch, K_DIG, ei)
        f = Sequence.cell_value(ch, K_FUNC, ei)
        st = Sequence.cell_value(ch, K_STEP, ei)
        tc = Sequence.cell_value(ch, K_TC, ei)
        digital = ch[K_SIG] == 1
        fill = C_EMPTY
        val = u""
        if digital:
            if d != -1:
                val = u"1" if d else u"0"
                fill = C_DIG1 if d else C_DIG0
        elif not lvcore.is_nan(a):
            val = fnum(a, 4)
            if len(val) > maxchars:
                val = fnum(a, 3)
            if len(val) > maxchars:
                val = fnum(a, 2)
            fill = C_ANALOG
        leftover = bool(f) and not val
        ramp = bool(f) and bool(val)
        if ramp:
            fill = C_RAMP
        line2 = u""
        if mode == u"value + ramp":
            if ramp:
                tag = abbr_func(f)
                val = (val + u" " + tag) if len(val) + 1 + len(tag) <= maxchars else val + tag
        elif mode == u"value + ramp + step":
            if ramp:
                line2 = abbr_func(f) + u" " + fstep(st)
            elif st != 1.0 and val:
                line2 = fstep(st)
        elif mode == u"step size":
            val = fstep(st) if (st != 1.0 or ramp) else u""
            if ramp:
                val = abbr_func(f) + u" " + val
        elif mode == u"time constant":
            val = fnum(tc, 4) if tc else u""
        return val, line2, fill, leftover

    def redraw(self):
        cv = self.canvas
        cv.delete("all")
        if not self.seq:
            return
        seq = self.seq
        n = len(self.order) or 1
        W = self.cell_w
        mode = self.app.display_mode.get()
        two_lines = mode == u"value + ramp + step"
        self.cell_h = 30 if two_lines else CELL_H
        CH = self.cell_h
        ncol, nrow = self._visible()
        cols = self.order[self.col0:self.col0 + ncol]
        rows = range(self.row0, min(len(seq.grid), self.row0 + nrow))
        small = ("TkDefaultFont", 9 if W >= 44 else 8)
        tiny = ("TkDefaultFont", 8)
        maxchars = max(3, (W - 4) // (6 if W < 44 else 7))
        show_left = self.app.show_leftovers.get()
        self.hbar.set(self.col0 / n, min(1.0, (self.col0 + ncol) / n))
        m = len(seq.grid) or 1
        self.vbar.set(self.row0 / m, min(1.0, (self.row0 + nrow) / m))
        for k, ei in enumerate(cols):
            x = ROW_HDR_W + k * W
            e = seq.edges[ei]
            cv.create_rectangle(x, 0, x + W, HDR_H, fill=C_HDR, outline=C_GRIDLINE)
            label = u"%d %s" % (ei, e[E_NAME])
            try:
                cv.create_text(x + W // 2, HDR_H - 22, text=label[:26], anchor="w", angle=90,
                               font=("TkDefaultFont", 9), fill=TXT)
            except tk.TclError:
                cv.create_text(x + 2, 4, text=label[:maxchars], anchor="nw", font=small, fill=TXT)
            cv.create_text(x + W // 2, HDR_H - 9, text=fnum(e[E_ABS], 5)[:maxchars], font=("TkDefaultFont", 8), fill=TXT)
        for j, r in enumerate(rows):
            y = HDR_H + j * CH
            ch = seq.grid[r][self.app.set_index]
            cv.create_rectangle(0, y, ROW_HDR_W, y + CH, fill=C_ROWHDR, outline=C_GRIDLINE)
            cv.create_text(4, y + CH // 2, text=u"%s  (%d.%d)" % (ch[K_NAME][:22], ch[K_CARD], ch[K_CHAN]),
                           anchor="w", font=("TkDefaultFont", 10), fill=TXT)
            for k, ei in enumerate(cols):
                x = ROW_HDR_W + k * W
                txt, line2, fill, leftover = self.cell_text(ch, ei, mode, maxchars)
                selected = (r, ei) in self.sel
                conflict = (r, ei) in self.conflicts
                outline = C_SEL if selected else (C_CONFLICT if conflict else C_GRIDLINE)
                width = 2 if (selected or conflict) else 1
                cv.create_rectangle(x, y, x + W, y + CH, fill=fill, outline=outline, width=width)
                if two_lines:
                    if txt:
                        cv.create_text(x + 3, y + 8, text=txt[:maxchars], anchor="w", font=small, fill=TXT)
                    if line2:
                        cv.create_text(x + W - 3, y + CH - 8, text=line2[:maxchars], anchor="e", font=tiny, fill="#303030")
                elif txt:
                    cv.create_text(x + 3, y + CH // 2, text=txt[:maxchars], anchor="w", font=small, fill=TXT)
                if leftover and show_left and not txt:
                    cv.create_text(x + W - 3, y + CH // 2, text=abbr_func(Sequence.cell_value(ch, K_FUNC, ei)),
                                   anchor="e", font=tiny, fill="#a0a0a0")
        cv.create_rectangle(0, 0, ROW_HDR_W, HDR_H, fill="#d4d4d4", outline=C_GRIDLINE)
        cv.create_text(6, HDR_H - 10, anchor="w", font=("TkDefaultFont", 9), fill=TXT,
                       text=u"%d channels x %d edges%s" % (len(seq.grid), len(self.order),
                                                           (u"   %d selected" % len(self.sel)) if self.sel else u""))

    # ---- interaction
    def _click(self, e):
        hit = self._cell_at(e.x, e.y)
        if hit:
            self.sel = set([hit])
            self.anchor = hit
            self.app.show_cell_info(*hit)
            self.redraw()
        elif e.y < HDR_H and e.x >= ROW_HDR_W:
            c = self.col0 + (e.x - ROW_HDR_W) // self.cell_w
            if c < len(self.order):
                self.app.select_edge(self.order[c])
        elif e.x < ROW_HDR_W and e.y >= HDR_H:          # row header: select the whole channel row
            r = self.row0 + (e.y - HDR_H) // self.cell_h
            if r < len(self.seq.grid):
                self.sel = set((r, ei) for ei in self.order)
                self.anchor = (r, self.order[0]) if self.order else None
                self.redraw()

    def _ctrl_click(self, e):
        hit = self._cell_at(e.x, e.y)
        if hit:
            if hit in self.sel:
                self.sel.discard(hit)
            else:
                self.sel.add(hit)
            self.anchor = hit
            self.app.show_cell_info(*hit)
            self.redraw()

    def _shift_click(self, e):
        hit = self._cell_at(e.x, e.y)
        if hit and self.anchor:
            r0, r1 = sorted((self.anchor[0], hit[0]))
            c0, c1 = sorted((self.order.index(self.anchor[1]), self.order.index(hit[1])))
            for r in range(r0, r1 + 1):
                for c in range(c0, c1 + 1):
                    self.sel.add((r, self.order[c]))
            self.redraw()
        elif hit:
            self._click(e)

    def _dblclick(self, e):
        hit = self._cell_at(e.x, e.y)
        if hit:
            self.app.edit_cell(*hit)
        elif e.y < HDR_H and e.x >= ROW_HDR_W:
            c = self.col0 + (e.x - ROW_HDR_W) // self.cell_w
            if c < len(self.order):
                self.app.edit_edge(self.order[c])


# ======================================================================= dialogs
class CellDialog(simpledialog.Dialog):
    """Edit one cell, or several at once (blank field = leave as it is)."""

    def __init__(self, parent, app, cells):
        self.app = app
        self.cells = list(cells)
        seq = app.seq
        ch, ei = self.cells[0]
        c = seq.grid[ch][app.set_index]
        self.vals = [Sequence.cell_value(c, f, ei) for f in (K_ANLG, K_DIG, K_TC, K_FUNC, K_STEP)]
        self.multi = len(self.cells) > 1
        title = (u"%d cells" % len(self.cells)) if self.multi else u"%s @ %s" % (c[K_NAME], seq.edges[ei][E_NAME])
        simpledialog.Dialog.__init__(self, parent, title)

    def body(self, master):
        a, d, tc, f, st = self.vals
        if self.multi:
            tk.Label(master, text=u"Editing %d cells. Leave a field blank to keep each cell's own value."
                     % len(self.cells), fg="#a00000").grid(row=0, column=0, columnspan=2, sticky="w", pady=4)
            a, d, tc, f, st = u"", u"", u"", u"", u""
        tk.Label(master, text=u"Analog value (NaN or '-' = no change)").grid(row=1, column=0, sticky="w")
        self.e_a = tk.Entry(master)
        self.e_a.insert(0, fnum(a) if not self.multi else u"")
        if not self.multi and lvcore.is_nan(a):
            self.e_a.insert(0, u"-")
        self.e_a.grid(row=1, column=1)
        tk.Label(master, text=u"Digital (-1 no change, 0, 1)").grid(row=2, column=0, sticky="w")
        self.e_d = tk.Entry(master)
        self.e_d.insert(0, (u"%d" % d) if not self.multi else u"")
        self.e_d.grid(row=2, column=1)
        tk.Label(master, text=u"Ramp function").grid(row=3, column=0, sticky="w")
        self.e_f = ttk.Combobox(master, values=([u"(keep)"] if self.multi else []) + lvcore.function_types(),
                                state="readonly")
        self.e_f.set(f if not self.multi else u"(keep)")
        self.e_f.grid(row=3, column=1)
        tk.Label(master, text=u"Step size (ms)").grid(row=4, column=0, sticky="w")
        self.e_s = tk.Entry(master)
        self.e_s.insert(0, fnum(st) if not self.multi else u"")
        self.e_s.grid(row=4, column=1)
        tk.Label(master, text=u"Time constant").grid(row=5, column=0, sticky="w")
        self.e_t = tk.Entry(master)
        self.e_t.insert(0, fnum(tc) if not self.multi else u"")
        self.e_t.grid(row=5, column=1)
        return self.e_a

    def validate(self):
        try:
            r = {}
            a = self.e_a.get().strip()
            if a:
                r[K_ANLG] = lvcore.FILE_NAN if a in (u"-", u"nan", u"NaN") else float(a)
            if self.e_d.get().strip():
                r[K_DIG] = int(self.e_d.get())
            if self.e_f.get() != u"(keep)":
                r[K_FUNC] = self.e_f.get()
            if self.e_s.get().strip():
                r[K_STEP] = float(self.e_s.get())
            if self.e_t.get().strip():
                r[K_TC] = float(self.e_t.get())
            self.result = r
            return True
        except ValueError as e:
            messagebox.showerror("Bad value", str(e))
            return False

    def apply(self):
        if self.result:
            self.app.seq.set_cells(self.cells, self.app.set_index, **self.result)
            self.app.mark_dirty()


class BatchDialog(simpledialog.Dialog):
    """Find cells by channel / edge-name pattern / value / step / ramp, then set fields on all."""

    def __init__(self, parent, app):
        self.app = app
        simpledialog.Dialog.__init__(self, parent, u"Batch edit")

    def body(self, master):
        names = [u"(all channels)"] + self.app.seq.channel_names()
        tk.Label(master, text=u"Find cells where...", font=("TkDefaultFont", 10, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        tk.Label(master, text=u"Channel").grid(row=1, column=0, sticky="w")
        self.f_ch = ttk.Combobox(master, values=names, width=40)
        self.f_ch.set(names[0])
        self.f_ch.grid(row=1, column=1, sticky="w")
        tk.Label(master, text=u"Edge name contains (regex ok)").grid(row=2, column=0, sticky="w")
        self.f_edge = tk.Entry(master, width=40)
        self.f_edge.grid(row=2, column=1, sticky="w")
        tk.Label(master, text=u"Value equals").grid(row=3, column=0, sticky="w")
        self.f_val = tk.Entry(master, width=14)
        self.f_val.grid(row=3, column=1, sticky="w")
        tk.Label(master, text=u"Step size equals (ms)").grid(row=4, column=0, sticky="w")
        self.f_step = tk.Entry(master, width=14)
        self.f_step.grid(row=4, column=1, sticky="w")
        tk.Label(master, text=u"Ramp function equals").grid(row=5, column=0, sticky="w")
        self.f_func = ttk.Combobox(master, values=[u"(any)", u"(none)"] + lvcore.function_types()[1:], width=24)
        self.f_func.set(u"(any)")
        self.f_func.grid(row=5, column=1, sticky="w")
        tk.Label(master, text=u"...and set (blank = keep)", font=("TkDefaultFont", 10, "bold")).grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))
        tk.Label(master, text=u"Value").grid(row=7, column=0, sticky="w")
        self.s_val = tk.Entry(master, width=14)
        self.s_val.grid(row=7, column=1, sticky="w")
        tk.Label(master, text=u"Step size (ms)").grid(row=8, column=0, sticky="w")
        self.s_step = tk.Entry(master, width=14)
        self.s_step.grid(row=8, column=1, sticky="w")
        tk.Label(master, text=u"Ramp function").grid(row=9, column=0, sticky="w")
        self.s_func = ttk.Combobox(master, values=[u"(keep)"] + lvcore.function_types(), width=24)
        self.s_func.set(u"(keep)")
        self.s_func.grid(row=9, column=1, sticky="w")
        tk.Label(master, text=u"Time constant").grid(row=10, column=0, sticky="w")
        self.s_tc = tk.Entry(master, width=14)
        self.s_tc.grid(row=10, column=1, sticky="w")
        tk.Button(master, text=u"Preview: select matching cells", command=self.preview).grid(row=11, column=0, columnspan=2, pady=6)
        self.msg = tk.Label(master, text=u"")
        self.msg.grid(row=12, column=0, columnspan=2, sticky="w")
        return self.f_edge

    def _criteria(self):
        seq = self.app.seq
        ch = self.f_ch.get()
        channels = None if ch.startswith(u"(") else [seq.find_channel(ch)]
        val = float(self.f_val.get()) if self.f_val.get().strip() else None
        st = float(self.f_step.get()) if self.f_step.get().strip() else None
        fn = self.f_func.get()
        func = None if fn == u"(any)" else (u"" if fn == u"(none)" else fn)
        return seq.find_cells(channels=channels, edge_pattern=self.f_edge.get().strip() or None,
                              value=val, step=st, func=func, s=self.app.set_index)

    def preview(self):
        try:
            cells = self._criteria()
        except Exception as e:
            messagebox.showerror("Batch edit", u"%s" % e)
            return
        self.app.grid.sel = set(cells)
        self.app.grid.redraw()
        self.msg.configure(text=u"%d cells match" % len(cells))

    def validate(self):
        try:
            self.cells = self._criteria()
            r = {}
            if self.s_val.get().strip():
                v = self.s_val.get().strip()
                r[K_ANLG] = lvcore.FILE_NAN if v in (u"-", u"nan") else float(v)
            if self.s_step.get().strip():
                r[K_STEP] = float(self.s_step.get())
            if self.s_func.get() != u"(keep)":
                r[K_FUNC] = self.s_func.get()
            if self.s_tc.get().strip():
                r[K_TC] = float(self.s_tc.get())
            self.result = r
            return True
        except Exception as e:
            messagebox.showerror("Batch edit", u"%s" % e)
            return False

    def apply(self):
        if not self.result or not self.cells:
            return
        seq = self.app.seq
        # digital channels: a 'value' means the digital level
        anlg = self.result.get(K_ANLG)
        for ch, ei in self.cells:
            r = dict(self.result)
            if anlg is not None and seq.grid[ch][self.app.set_index][K_SIG] == 1:
                r[K_DIG] = -1 if lvcore.is_nan(anlg) else int(anlg)
                del r[K_ANLG]
            seq.set_cells([(ch, ei)], self.app.set_index, **r)
        self.app.grid.sel = set(self.cells)
        self.app.mark_dirty()
        messagebox.showinfo("Batch edit", u"%d cells changed." % len(self.cells))


class EdgeBatchDialog(simpledialog.Dialog):
    """Change the relative time of every edge whose name matches a pattern."""

    def __init__(self, parent, app):
        self.app = app
        simpledialog.Dialog.__init__(self, parent, u"Batch edit edges")

    def body(self, master):
        tk.Label(master, text=u"Edge name contains (regex ok)").grid(row=0, column=0, sticky="w")
        self.f_name = tk.Entry(master, width=40)
        self.f_name.grid(row=0, column=1)
        tk.Label(master, text=u"Current relative time equals (ms, optional)").grid(row=1, column=0, sticky="w")
        self.f_rel = tk.Entry(master, width=14)
        self.f_rel.grid(row=1, column=1, sticky="w")
        tk.Label(master, text=u"New relative time (ms)").grid(row=2, column=0, sticky="w")
        self.s_rel = tk.Entry(master, width=14)
        self.s_rel.grid(row=2, column=1, sticky="w")
        tk.Label(master, text=u"(edges timed by a variable keep following the variable)").grid(row=3, column=0, columnspan=2, sticky="w")
        return self.f_name

    def validate(self):
        try:
            rel = float(self.f_rel.get()) if self.f_rel.get().strip() else None
            self.edges = self.app.seq.find_edges(self.f_name.get().strip() or None, rel)
            self.new_rel = float(self.s_rel.get())
            return True
        except Exception as e:
            messagebox.showerror("Batch edit edges", u"%s" % e)
            return False

    def apply(self):
        seq = self.app.seq
        for i in self.edges:
            seq.edges[i][E_REL] = self.new_rel
        seq.recompute_times()
        self.app.mark_dirty(structural=True)
        messagebox.showinfo("Batch edit edges", u"%d edges changed." % len(self.edges))


class EdgeDialog(simpledialog.Dialog):
    def __init__(self, parent, app, ei=None):
        self.app = app
        self.ei = ei
        simpledialog.Dialog.__init__(self, parent, u"Edge" if ei is None else u"Edge %d" % ei)

    def body(self, master):
        seq = self.app.seq
        e = seq.edges[self.ei] if self.ei is not None else None
        names = [u"%d %s" % (i, x[E_NAME]) for i, x in enumerate(seq.edges)]
        vnames = [u"(none)"] + [u"%d %s" % (i, v[V_NAME]) for i, v in enumerate(seq.variables)]
        tk.Label(master, text=u"Name").grid(row=0, column=0, sticky="w")
        self.e_name = tk.Entry(master, width=40)
        self.e_name.insert(0, e[E_NAME] if e else u"new edge")
        self.e_name.grid(row=0, column=1)
        tk.Label(master, text=u"Defined with respect to").grid(row=1, column=0, sticky="w")
        self.e_parent = ttk.Combobox(master, values=names, width=38)
        self.e_parent.set(names[e[E_PARENT]] if e and e[E_PARENT] < len(names) else names[0])
        self.e_parent.grid(row=1, column=1)
        tk.Label(master, text=u"Time type (0 fixed, 1 from variable)").grid(row=2, column=0, sticky="w")
        self.e_type = tk.Entry(master)
        self.e_type.insert(0, u"%d" % (e[E_TYPE] if e else 0))
        self.e_type.grid(row=2, column=1, sticky="w")
        tk.Label(master, text=u"Relative time (ms)").grid(row=3, column=0, sticky="w")
        self.e_rel = tk.Entry(master)
        self.e_rel.insert(0, fnum(e[E_REL]) if e else u"0")
        self.e_rel.grid(row=3, column=1, sticky="w")
        tk.Label(master, text=u"Variable").grid(row=4, column=0, sticky="w")
        self.e_var = ttk.Combobox(master, values=vnames, width=38)
        cur = e[E_VARS][0] if e and e[E_VARS] else None
        self.e_var.set(vnames[cur + 1] if cur is not None and cur + 1 < len(vnames) else vnames[0])
        self.e_var.grid(row=4, column=1)
        if e:
            tk.Label(master, text=u"Absolute time: %s ms" % fnum(e[E_ABS])).grid(row=5, column=0, columnspan=2, sticky="w")
        return self.e_name

    def validate(self):
        try:
            self.result = {"name": self.e_name.get(), "parent": int(self.e_parent.get().split(u" ", 1)[0]),
                           "type": int(self.e_type.get()), "rel": float(self.e_rel.get() or 0),
                           "var": None if self.e_var.get().startswith(u"(") else int(self.e_var.get().split(u" ", 1)[0])}
            return True
        except ValueError as ex:
            messagebox.showerror("Bad value", str(ex))
            return False

    def apply(self):
        seq = self.app.seq
        r = self.result
        vars_ = [r["var"]] if r["var"] is not None else []
        if self.ei is None:
            seq.add_edge(r["name"], r["parent"], r["rel"], r["type"], vars_)
        else:
            e = seq.edges[self.ei]
            e[E_NAME], e[E_PARENT], e[E_REL], e[E_TYPE], e[E_VARS] = r["name"], r["parent"], r["rel"], r["type"], vars_
            seq.recompute_times()
        self.app.mark_dirty(structural=True)


# ======================================================================= plot window
class PlotWindow(tk.Toplevel):
    """Value against time for chosen channels of one or two sequences, drawn on a canvas."""

    COLORS = ["#1f4fd6", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf", "#8c564b", "#e377c2",
              "#7f7f7f", "#bcbd22"]

    def __init__(self, app, seq, seq_b=None, channels=None):
        tk.Toplevel.__init__(self, app.root)
        self.app = app
        self.seq = seq
        self.seq_b = seq_b
        self.title(u"Plot: %s%s" % (os.path.basename(seq.path or "A"),
                                     (u"  vs  " + os.path.basename(seq_b.path or "B")) if seq_b else u""))
        self.geometry("1100x650")
        left = tk.Frame(self)
        left.pack(side="left", fill="y")
        tk.Label(left, text=u"Channels (click to toggle)").pack()
        self.lb = tk.Listbox(left, selectmode="multiple", width=30, exportselection=False)
        for n in seq.channel_names():
            self.lb.insert("end", n)
        self.lb.pack(fill="y", expand=True)
        self.lb.bind("<<ListboxSelect>>", lambda e: self.draw())
        for ch in (channels or []):
            self.lb.selection_set(ch)
        bar = tk.Frame(left)
        bar.pack(fill="x")
        tk.Label(bar, text=u"t from").grid(row=0, column=0)
        self.t0 = tk.Entry(bar, width=9)
        self.t0.grid(row=0, column=1)
        tk.Label(bar, text=u"to (ms)").grid(row=1, column=0)
        self.t1 = tk.Entry(bar, width=9)
        self.t1.grid(row=1, column=1)
        tk.Button(bar, text=u"Apply", command=self.draw).grid(row=2, column=0, columnspan=2)
        tk.Button(bar, text=u"Full range", command=self.full).grid(row=3, column=0, columnspan=2)
        self.stack = tk.BooleanVar(value=True)
        tk.Checkbutton(bar, text=u"one strip per channel", variable=self.stack, command=self.draw).grid(row=4, column=0, columnspan=2, sticky="w")
        self.canvas = tk.Canvas(self, bg="white", highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.draw())
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.readout = tk.Label(self, anchor="w")
        self.readout.pack(side="bottom", fill="x")
        self.drag = None
        self.full()

    def full(self):
        self.t0.delete(0, "end")
        self.t0.insert(0, u"0")
        self.t1.delete(0, "end")
        self.t1.insert(0, fnum(max(self.seq.cycle_length(), self.seq_b.cycle_length() if self.seq_b else 0)))
        self.draw()

    def _range(self):
        try:
            a, b = float(self.t0.get()), float(self.t1.get())
        except ValueError:
            a, b = 0.0, self.seq.cycle_length()
        if b <= a:
            b = a + 1.0
        return a, b

    def draw(self):
        cv = self.canvas
        cv.delete("all")
        chans = [int(i) for i in self.lb.curselection()]
        W, H = cv.winfo_width(), cv.winfo_height()
        L, R, T, B = 60, 20, 20, 30
        ta, tb = self._range()
        self.geom = (L, R, T, B, ta, tb, W, H)
        if not chans:
            cv.create_text(W // 2, H // 2, text=u"select channels on the left", fill="#808080")
            return
        strips = len(chans) if self.stack.get() else 1
        sh = (H - T - B) / strips
        self.strip_info = []
        for k, ch in enumerate(chans):
            y0 = T + k * sh if self.stack.get() else T
            y1 = y0 + sh if self.stack.get() else H - B
            series = [(self.seq, self.COLORS[k % len(self.COLORS)], u"A")]
            if self.seq_b:
                chb = self.seq_b.find_channel(self.seq.channel_names()[ch])
                if chb >= 0:
                    series.append((self.seq_b, "#ff00ff", u"B"))
            pts_all = []
            for s_, col, tag in series:
                c = ch if s_ is self.seq else self.seq_b.find_channel(self.seq.channel_names()[ch])
                pts = s_.trace(c, self.app.set_index if s_ is self.seq else 0)
                pts_all.append((pts, col, tag))
            clipped = []
            for pts, col, tag in pts_all:
                clipped.append((self._clip(pts, ta, tb), col, tag))
            pts_all = clipped
            vals = [v for pts, _, _ in pts_all for t, v in pts] or [0.0]
            vmin, vmax = min(vals), max(vals)
            if vmax == vmin:
                vmax = vmin + 1.0
            pad = (vmax - vmin) * 0.08
            vmin, vmax = vmin - pad, vmax + pad
            self.strip_info.append((y0, y1, vmin, vmax, ch))
            cv.create_rectangle(L, y0, W - R, y1, outline="#c0c0c0")
            name = self.seq.channel_names()[ch]
            cv.create_text(L + 4, y0 + 3, text=name, anchor="nw", fill=self.COLORS[k % len(self.COLORS)], font=("TkDefaultFont", 9))
            cv.create_text(L - 4, y0 + 4, text=fnum(vmax, 4), anchor="ne", fill=TXT, font=("TkDefaultFont", 8))
            cv.create_text(L - 4, y1 - 4, text=fnum(vmin, 4), anchor="se", fill=TXT, font=("TkDefaultFont", 8))

            def X(t):
                return L + (t - ta) / (tb - ta) * (W - L - R)

            def Y(v):
                return y1 - (v - vmin) / (vmax - vmin) * (y1 - y0)
            for pts, col, tag in pts_all:
                coords = []
                for t, v in pts:
                    coords.extend([X(t), Y(v)])
                if len(coords) >= 4:
                    cv.create_line(*coords, fill=col, width=1 if tag == u"B" else 2, dash=(4, 3) if tag == u"B" else None)
        # time axis
        for i in range(11):
            t = ta + (tb - ta) * i / 10.0
            x = L + (W - L - R) * i / 10.0
            cv.create_line(x, H - B, x, H - B + 4, fill=TXT)
            cv.create_text(x, H - B + 6, text=fnum(t, 5), anchor="n", fill=TXT, font=("TkDefaultFont", 8))
        # edges as faint vertical lines when zoomed in enough
        if (tb - ta) < 400:
            for i in self.seq.edge_order():
                t = self.seq.edges[i][E_ABS]
                if ta <= t <= tb:
                    x = L + (t - ta) / (tb - ta) * (W - L - R)
                    cv.create_line(x, T, x, H - B, fill="#e8e8e8")
                    cv.create_text(x + 2, T + 2, text=self.seq.edges[i][E_NAME][:18], anchor="nw", angle=270,
                                   fill="#909090", font=("TkDefaultFont", 7)) if (tb - ta) < 60 else None

    @staticmethod
    def _clip(pts, ta, tb):
        """Clip a (t, v) polyline to [ta, tb], interpolating at the boundaries."""
        out = []
        for k in range(len(pts)):
            t, v = pts[k]
            if k > 0:
                t0, v0 = pts[k - 1]
                for tc in (ta, tb):                      # boundary crossings
                    if (t0 < tc < t) or (t < tc < t0):
                        f = (tc - t0) / (t - t0) if t != t0 else 0.0
                        out.append((tc, v0 + f * (v - v0)))
            if ta <= t <= tb:
                out.append((t, v))
        if pts and not out:                             # whole trace outside: show the held value
            before = [p for p in pts if p[0] <= ta]
            if before:
                out = [(ta, before[-1][1]), (tb, before[-1][1])]
        elif out and out[0][0] > ta:
            before = [p for p in pts if p[0] <= ta]
            if before:
                out.insert(0, (ta, before[-1][1]))
        if out and out[-1][0] < tb:
            out.append((tb, out[-1][1]))
        return out

    def _motion(self, e):
        L, R, T, B, ta, tb, W, H = self.geom
        if W - L - R <= 0:
            return
        t = ta + (e.x - L) / (W - L - R) * (tb - ta)
        txt = u"t = %s ms" % fnum(t, 6)
        for y0, y1, vmin, vmax, ch in getattr(self, "strip_info", []):
            if y0 <= e.y <= y1:
                v = vmax - (e.y - y0) / (y1 - y0) * (vmax - vmin)
                txt += u"   %s: %s" % (self.seq.channel_names()[ch], fnum(v, 4))
        self.readout.configure(text=txt)

    def _press(self, e):
        self.drag = e.x

    def _release(self, e):
        if self.drag is None or abs(e.x - self.drag) < 5:
            self.drag = None
            return
        L, R, T, B, ta, tb, W, H = self.geom
        x0, x1 = sorted((self.drag, e.x))
        t0 = ta + (x0 - L) / (W - L - R) * (tb - ta)
        t1 = ta + (x1 - L) / (W - L - R) * (tb - ta)
        self.t0.delete(0, "end")
        self.t0.insert(0, fnum(max(0.0, t0), 6))
        self.t1.delete(0, "end")
        self.t1.insert(0, fnum(t1, 6))
        self.drag = None
        self.draw()


# ======================================================================= compare window
class DiffGrid(tk.Frame):
    """Graphical diff: matched channels x matched edges, cells coloured by what differs."""

    C_SAME = "#ffffff"
    C_VAL = "#ff9f9f"
    C_RAMP = "#ffd27a"
    C_STEP = "#c8a0ff"
    C_ONLY = "#d0d0d0"

    def __init__(self, master, win):
        tk.Frame.__init__(self, master)
        self.win = win
        self.canvas = tk.Canvas(self, bg="white", highlightthickness=0)
        self.vbar = tk.Scrollbar(self, orient="vertical", command=self._yscroll)
        self.hbar = tk.Scrollbar(self, orient="horizontal", command=self._xscroll)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vbar.grid(row=0, column=1, sticky="ns")
        self.hbar.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.col0 = self.row0 = 0
        self.cw = 14
        self.rh = 14
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<MouseWheel>", lambda e: self._scroll(0, -3 if e.delta > 0 else 3))
        self.canvas.bind("<Shift-MouseWheel>", lambda e: self._scroll(-3 if e.delta > 0 else 3, 0))
        self.rebuild()

    def rebuild(self):
        """Index the comparison into a cell map keyed by (channel row, edge column)."""
        cmp_ = self.win.cmp
        self.edge_cols = [m for m in cmp_.edge_map]            # (ia, ib, key)
        self.chan_rows = [m for m in cmp_.chan_map]            # (ia, ib, name)
        # sort edge columns by time in A (or B for B-only edges)
        a, b = cmp_.a, cmp_.b

        def tkey(m):
            ia, ib, key = m
            return a.edges[ia][E_ABS] if ia is not None else b.edges[ib][E_ABS]
        self.edge_cols.sort(key=tkey)
        self.cells = {}
        for d in cmp_.diffs:
            if d.kind == "cell":
                self.cells.setdefault((d.where[0], d.where[1]), []).append(d)
        self.redraw()

    def _scroll(self, dc, dr):
        self.col0 = max(0, min(max(0, len(self.edge_cols) - 1), self.col0 + dc))
        self.row0 = max(0, min(max(0, len(self.chan_rows) - 1), self.row0 + dr))
        self.redraw()

    def _yscroll(self, *args):
        n = len(self.chan_rows) or 1
        if args[0] == "moveto":
            self.row0 = int(float(args[1]) * n)
        else:
            self.row0 += int(args[1]) * (10 if args[2] == "pages" else 1)
        self.row0 = max(0, min(max(0, n - 1), self.row0))
        self.redraw()

    def _xscroll(self, *args):
        n = len(self.edge_cols) or 1
        if args[0] == "moveto":
            self.col0 = int(float(args[1]) * n)
        else:
            self.col0 += int(args[1]) * (30 if args[2] == "pages" else 1)
        self.col0 = max(0, min(max(0, n - 1), self.col0))
        self.redraw()

    def _label(self, key):
        return key[0] if key[1] == 0 else u"%s (%d)" % key

    def redraw(self):
        cv = self.canvas
        cv.delete("all")
        W, H = cv.winfo_width(), cv.winfo_height()
        LW, TH = 150, 70
        ncol = max(1, (W - LW) // self.cw + 1)
        nrow = max(1, (H - TH) // self.rh + 1)
        cols = self.edge_cols[self.col0:self.col0 + ncol]
        rows = self.chan_rows[self.row0:self.row0 + nrow]
        n = len(self.edge_cols) or 1
        self.hbar.set(self.col0 / n, min(1.0, (self.col0 + ncol) / n))
        m = len(self.chan_rows) or 1
        self.vbar.set(self.row0 / m, min(1.0, (self.row0 + nrow) / m))
        for k, (ia, ib, key) in enumerate(cols):
            x = LW + k * self.cw
            fill = self.C_ONLY if (ia is None or ib is None) else "#eeeeee"
            cv.create_rectangle(x, 0, x + self.cw, TH, fill=fill, outline="#d0d0d0")
            if self.cw >= 12:
                try:
                    cv.create_text(x + self.cw // 2, TH - 3, text=self._label(key)[:14], anchor="w", angle=90,
                                   fill=TXT, font=("TkDefaultFont", 7))
                except tk.TclError:
                    pass
        for j, (ia, ib, name) in enumerate(rows):
            y = TH + j * self.rh
            cv.create_rectangle(0, y, LW, y + self.rh, fill=self.C_ONLY if (ia is None or ib is None) else "#eeeeee", outline="#d0d0d0")
            cv.create_text(3, y + self.rh // 2, text=name[:24], anchor="w", fill=TXT, font=("TkDefaultFont", 8))
            for k, (ea, eb, key) in enumerate(cols):
                x = LW + k * self.cw
                if ia is None or ib is None or ea is None or eb is None:
                    fill = self.C_ONLY
                else:
                    ds = self.cells.get((name, self._label(key)))
                    if not ds:
                        fill = self.C_SAME
                    else:
                        fields = set(d.field for d in ds)
                        fill = self.C_VAL if ("analog" in fields or "digital" in fields) else (
                            self.C_RAMP if "ramp" in fields else self.C_STEP)
                cv.create_rectangle(x, y, x + self.cw, y + self.rh, fill=fill, outline="#e4e4e4")
        cv.create_rectangle(0, 0, LW, TH, fill="#d4d4d4", outline="#d0d0d0")
        cv.create_text(4, 6, anchor="nw", fill=TXT, font=("TkDefaultFont", 8), justify="left",
                       text=u"red: value\norange: ramp\npurple: step/tc\ngrey: only in A or B\nclick a cell")

    def _click(self, e):
        LW, TH = 150, 70
        if e.x < LW or e.y < TH:
            return
        c = self.col0 + (e.x - LW) // self.cw
        r = self.row0 + (e.y - TH) // self.rh
        if c >= len(self.edge_cols) or r >= len(self.chan_rows):
            return
        ia, ib, key = self.edge_cols[c]
        ca, cb, name = self.chan_rows[r]
        self.win.show_cell(name, self._label(key), ia, ib, ca, cb)


class CompareWindow(tk.Toplevel):
    KINDS = [u"all", u"cell", u"edge", u"edge-missing", u"channel", u"channel-missing", u"variable", u"setting"]

    def __init__(self, app, seq_a, seq_b):
        tk.Toplevel.__init__(self, app.root)
        self.app = app
        self.a = seq_a
        self.b = seq_b
        self._title()
        self.geometry("1250x700")
        top = tk.Frame(self)
        top.pack(fill="x")
        tk.Label(top, text=u"Show:").pack(side="left")
        self.kind = ttk.Combobox(top, values=self.KINDS, state="readonly", width=14)
        self.kind.set(u"all")
        self.kind.pack(side="left")
        self.kind.bind("<<ComboboxSelected>>", lambda e: self.fill())
        tk.Label(top, text=u" filter:").pack(side="left")
        self.chan_filter = tk.Entry(top, width=16)
        self.chan_filter.pack(side="left")
        self.chan_filter.bind("<Return>", lambda e: self.fill())
        tk.Button(top, text=u"Copy A -> B (sel)", command=lambda: self.copy_sel("A->B")).pack(side="left", padx=3)
        tk.Button(top, text=u"Copy B -> A (sel)", command=lambda: self.copy_sel("B->A")).pack(side="left", padx=3)
        tk.Button(top, text=u"Unify all A -> B", command=lambda: self.unify("A->B")).pack(side="left", padx=3)
        tk.Button(top, text=u"Unify all B -> A", command=lambda: self.unify("B->A")).pack(side="left", padx=3)
        tk.Button(top, text=u"Plot A vs B", command=self.plot).pack(side="left", padx=8)
        tk.Button(top, text=u"Save A", command=lambda: self.save(self.a)).pack(side="left", padx=3)
        tk.Button(top, text=u"Save B as...", command=lambda: self.save(self.b, True)).pack(side="left", padx=3)
        self.summary = tk.Label(self, anchor="w")
        self.summary.pack(fill="x")
        self.cmp = Comparison(self.a, self.b)
        pane = tk.PanedWindow(self, orient="vertical", sashwidth=5)
        pane.pack(fill="both", expand=True)
        self.dgrid = DiffGrid(pane, self)
        pane.add(self.dgrid, height=300, stretch="always")
        bottom = tk.Frame(pane)
        pane.add(bottom, stretch="always")
        cols = ("kind", "where", "field", "A", "B")
        self.tree = ttk.Treeview(bottom, columns=cols, show="headings", selectmode="extended")
        for c, w in zip(cols, (100, 460, 110, 170, 170)):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="w")
        vs = tk.Scrollbar(bottom, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.tree.bind("<Double-Button-1>", self.goto)
        self.cell_info = tk.Label(self, anchor="w", relief="sunken", justify="left")
        self.cell_info.pack(fill="x")
        self.fill()

    def _title(self):
        self.title(u"Compare: A = %s   |   B = %s" % (os.path.basename(self.a.path or "A"), os.path.basename(self.b.path or "B")))

    def fill(self):
        self.tree.delete(*self.tree.get_children())
        kind = self.kind.get()
        cf = self.chan_filter.get().strip().lower()
        self.rows = []
        for d in self.cmp.diffs:
            if kind != u"all" and d.kind != kind:
                continue
            if cf and cf not in d.label().lower():
                continue
            self.rows.append(d)
            self.tree.insert("", "end", values=(d.kind, d.label(), d.field, fmt_value(d.va), fmt_value(d.vb)))
        self.summary.configure(text=u"%d differences: %s" % (len(self.cmp.diffs), self.cmp.summary() or u"none"))
        self.dgrid.rebuild()

    def show_cell(self, cname, ename, ea, eb, ca, cb):
        lines = [u"%s @ %s" % (cname, ename)]
        for tag, seq, ch, ei in ((u"A", self.a, ca, ea), (u"B", self.b, cb, eb)):
            if ch is None or ei is None:
                lines.append(u"  %s: (absent)" % tag)
                continue
            c = seq.grid[ch][0]
            vals = [Sequence.cell_value(c, f, ei) for f in (K_ANLG, K_DIG, K_FUNC, K_STEP, K_TC)]
            lines.append(u"  %s: analog %s  digital %s  ramp %s  step %s ms  tc %s   (edge at %s ms)" % (
                tag, fnum(vals[0]) or u"-", vals[1], vals[2] or u"-", fnum(vals[3]), fnum(vals[4]),
                fnum(seq.edges[ei][E_ABS])))
        self.cell_info.configure(text=u"\n".join(lines))
        # select the matching rows in the list
        self.tree.selection_remove(self.tree.selection())
        for iid, d in zip(self.tree.get_children(), self.rows):
            if d.kind == "cell" and d.where == (cname, ename):
                self.tree.selection_add(iid)
                self.tree.see(iid)

    def _selected(self):
        idx = [self.tree.index(i) for i in self.tree.selection()]
        return [self.rows[i] for i in idx if i < len(self.rows)]

    def copy_sel(self, direction):
        sel = self._selected()
        n = 0
        structural = False
        for d in sel:
            if self.cmp.apply(d, direction):
                n += 1
                structural = structural or d.kind in self.cmp.STRUCTURAL
            if structural:
                break
        self.cmp.run()
        self.fill()
        self.app.after_external_change()
        if structural and len(sel) > 1:
            messagebox.showinfo("Compare", u"Applied %d; re-select the rest after this structural change." % n)

    def unify(self, direction):
        n = self.cmp.unify_all(direction)
        self.fill()
        self.app.after_external_change()
        messagebox.showinfo("Compare", u"Applied %d differences (%s)." % (n, direction))

    def plot(self):
        sel = self._selected()
        chans = []
        for d in sel:
            if d.kind == "cell":
                ch = self.a.find_channel(d.where[0])
                if ch >= 0 and ch not in chans:
                    chans.append(ch)
        PlotWindow(self.app, self.a, self.b, chans)

    def save(self, seq, ask=False):
        path = seq.path
        if ask or not path:
            path = filedialog.asksaveasfilename(defaultextension=".dt4", initialfile=os.path.basename(path or "sequence.dt4"))
            if not path:
                return
        seq.save(path)
        self.app.after_external_change()
        self._title()

    def goto(self, e):
        sel = self._selected()
        if sel and sel[0].kind == "cell" and sel[0].data.get("ea") is not None:
            self.app.grid.scroll_to_edge(sel[0].data["ea"])
            ch = sel[0].data.get("ia")
            if ch is not None:
                self.app.grid.row0 = max(0, ch - 3)
                self.app.grid.sel = set([(ch, sel[0].data["ea"])])
                self.app.grid.redraw()


# ======================================================================= main app
class App(object):
    def __init__(self, root, path=None):
        self.root = root
        self.seq = None
        self.dirty = False
        self.set_index = 0
        root.title(u"Supertime sequence editor")
        root.geometry("1300x750")
        self.display_mode = tk.StringVar(value=DISPLAY_MODES[0])
        self.show_leftovers = tk.BooleanVar(value=True)
        self._menu()
        pane = tk.PanedWindow(root, orient="horizontal", sashwidth=5)
        pane.pack(fill="both", expand=True)
        left = tk.Frame(pane, width=380)
        pane.add(left)
        self.nb = ttk.Notebook(left)
        self.nb.pack(fill="both", expand=True)
        f1 = tk.Frame(self.nb)
        self.nb.add(f1, text=u"Edges")
        cols = ("i", "name", "time", "parent", "rel", "type", "var")
        self.etree = ttk.Treeview(f1, columns=cols, show="headings")
        for c, w in zip(cols, (36, 150, 70, 50, 60, 36, 90)):
            self.etree.heading(c, text=c)
            self.etree.column(c, width=w, anchor="w")
        vs = tk.Scrollbar(f1, orient="vertical", command=self.etree.yview)
        self.etree.configure(yscrollcommand=vs.set)
        self.etree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.etree.bind("<<TreeviewSelect>>", self._edge_selected)
        self.etree.bind("<Double-Button-1>", lambda e: self.edit_selected_edge())
        f2 = tk.Frame(self.nb)
        self.nb.add(f2, text=u"Variables")
        self.vtree = ttk.Treeview(f2, columns=("i", "name", "value"), show="headings")
        for c, w in zip(("i", "name", "value"), (36, 220, 80)):
            self.vtree.heading(c, text=c)
            self.vtree.column(c, width=w, anchor="w")
        self.vtree.pack(fill="both", expand=True)
        self.vtree.bind("<Double-Button-1>", lambda e: self.edit_variable())
        f3 = tk.Frame(self.nb)
        self.nb.add(f3, text=u"Ramps")
        self.rtree = ttk.Treeview(f3, columns=("problem", "where"), show="headings")
        self.rtree.heading("problem", text=u"problem")
        self.rtree.heading("where", text=u"where")
        self.rtree.column("problem", width=150, anchor="w")
        self.rtree.column("where", width=220, anchor="w")
        self.rtree.pack(fill="both", expand=True)
        self.rtree.bind("<<TreeviewSelect>>", self._ramp_selected)
        f4 = tk.Frame(self.nb)
        self.nb.add(f4, text=u"Info")
        self.info = tk.Text(f4, width=40, wrap="word")
        self.info.pack(fill="both", expand=True)
        right = tk.Frame(pane)
        pane.add(right, stretch="always")
        bar = tk.Frame(right)
        bar.pack(fill="x")
        tk.Label(bar, text=u"Set:").pack(side="left")
        self.set_box = ttk.Combobox(bar, values=[u"0"], state="readonly", width=16)
        self.set_box.set(u"0")
        self.set_box.pack(side="left")
        self.set_box.bind("<<ComboboxSelected>>", self._set_changed)
        tk.Label(bar, text=u" cells show:").pack(side="left")
        dm = ttk.Combobox(bar, values=DISPLAY_MODES, textvariable=self.display_mode, state="readonly", width=18)
        dm.pack(side="left")
        dm.bind("<<ComboboxSelected>>", lambda e: self.grid.redraw())
        tk.Checkbutton(bar, text=u"grey leftovers", variable=self.show_leftovers,
                       command=lambda: self.grid.redraw()).pack(side="left", padx=4)
        tk.Label(bar, text=u" width:").pack(side="left")
        self.width_var = tk.StringVar(value=u"%d" % CELL_W)
        sp = tk.Spinbox(bar, from_=24, to=160, increment=4, width=4, textvariable=self.width_var, command=self._width_changed)
        sp.pack(side="left")
        sp.bind("<Return>", lambda e: self._width_changed())
        bar2 = tk.Frame(right)
        bar2.pack(fill="x")
        tk.Button(bar2, text=u"Edit selected cells", command=self.edit_selected_cells).pack(side="left", padx=3)
        tk.Button(bar2, text=u"Batch edit...", command=lambda: BatchDialog(self.root, self) if self.seq else None).pack(side="left", padx=3)
        tk.Button(bar2, text=u"Batch edit edges...", command=lambda: EdgeBatchDialog(self.root, self) if self.seq else None).pack(side="left", padx=3)
        tk.Button(bar2, text=u"Add edge", command=lambda: self.edit_edge(None)).pack(side="left", padx=3)
        tk.Button(bar2, text=u"Delete edge", command=self.delete_selected_edge).pack(side="left", padx=3)
        tk.Button(bar2, text=u"Add variable", command=self.add_variable).pack(side="left", padx=3)
        tk.Button(bar2, text=u"Add channel", command=self.add_channel).pack(side="left", padx=3)
        tk.Button(bar2, text=u"Delete channel", command=self.delete_channel).pack(side="left", padx=3)
        tk.Button(bar2, text=u"Plot...", command=self.plot).pack(side="left", padx=8)
        tk.Button(bar2, text=u"Check ramps", command=self.check_ramps).pack(side="left", padx=3)
        tk.Button(bar2, text=u"Compare with...", command=self.compare).pack(side="left", padx=8)
        self.cell_info = tk.Label(right, anchor="w", relief="sunken")
        self.cell_info.pack(fill="x")
        self.grid = SequenceGrid(right, self)
        self.grid.pack(fill="both", expand=True)
        self.status = tk.Label(root, anchor="w", relief="sunken")
        self.status.pack(fill="x")
        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.bind("<Control-equal>", lambda e: self._zoom(4))
        root.bind("<Control-plus>", lambda e: self._zoom(4))
        root.bind("<Control-minus>", lambda e: self._zoom(-4))
        root.bind("<Return>", lambda e: self.edit_selected_cells() if self.grid.sel else None)
        if path:
            self.open(path)

    def _menu(self):
        m = tk.Menu(self.root)
        fm = tk.Menu(m, tearoff=0)
        fm.add_command(label=u"Open...", command=self.open, accelerator="Ctrl+O")
        fm.add_command(label=u"Save", command=self.save, accelerator="Ctrl+S")
        fm.add_command(label=u"Save as...", command=lambda: self.save(True))
        fm.add_separator()
        fm.add_command(label=u"Compare with...", command=self.compare)
        fm.add_command(label=u"Plot...", command=self.plot)
        fm.add_command(label=u"Check ramps", command=self.check_ramps)
        fm.add_command(label=u"Repair channel arrays", command=self.repair)
        fm.add_separator()
        fm.add_command(label=u"Quit", command=self.quit)
        m.add_cascade(label=u"File", menu=fm)
        em = tk.Menu(m, tearoff=0)
        em.add_command(label=u"Edit selected cells...", command=self.edit_selected_cells, accelerator="Return")
        em.add_command(label=u"Batch edit cells...", command=lambda: BatchDialog(self.root, self) if self.seq else None)
        em.add_command(label=u"Batch edit edges...", command=lambda: EdgeBatchDialog(self.root, self) if self.seq else None)
        em.add_command(label=u"Select all cells of channel", command=self.select_channel_row)
        em.add_command(label=u"Clear selection", command=self.clear_selection)
        m.add_cascade(label=u"Edit", menu=em)
        self.root.config(menu=m)
        self.root.bind("<Control-o>", lambda e: self.open())
        self.root.bind("<Control-s>", lambda e: self.save())

    # ---- file
    def open(self, path=None):
        if not path:
            path = filedialog.askopenfilename(filetypes=[("Supertime sequence", "*.dt4 *.dt3"), ("All", "*")])
            if not path:
                return
        try:
            self.seq = Sequence.load(path)
        except Exception as e:
            messagebox.showerror("Open failed", u"%s" % e)
            return
        self.dirty = False
        self.set_index = 0
        names = [u"%d %s" % (i, n) for i, n in enumerate(self.seq.set_names)] or [u"0"]
        self.set_box.configure(values=names)
        self.set_box.set(names[0])
        self.grid.set_sequence(self.seq)
        self.refresh_lists()
        self.check_ramps(quiet=True)
        self.root.title(u"Supertime sequence editor - %s" % os.path.basename(path))

    def save(self, ask=False):
        if not self.seq:
            return
        path = self.seq.path
        if ask or not path:
            path = filedialog.asksaveasfilename(defaultextension=".dt4", initialfile=os.path.basename(path or "sequence.dt4"))
            if not path:
                return
        problems = self.seq.check()
        rp, _ = self.seq.check_ramps(self.set_index)
        msgs = problems[:5] + [self._ramp_text(p) for p in rp[:5]]
        if msgs and not messagebox.askyesno("Save", u"%d consistency problems, %d ramp problems:\n%s\n\nSave anyway?"
                                            % (len(problems), len(rp), u"\n".join(msgs))):
            return
        self.seq.save(path)
        self.dirty = False
        self.root.title(u"Supertime sequence editor - %s" % os.path.basename(path))
        self.refresh_status()

    def quit(self):
        if self.dirty and not messagebox.askyesno("Quit", u"Unsaved changes. Quit anyway?"):
            return
        self.root.destroy()

    # ---- refresh
    def refresh_lists(self):
        seq = self.seq
        self.etree.delete(*self.etree.get_children())
        for i in seq.edge_order():
            e = seq.edges[i]
            vn = u", ".join(seq.variables[k][V_NAME] for k in e[E_VARS] if k < len(seq.variables))
            self.etree.insert("", "end", iid=str(i), values=(i, e[E_NAME], fnum(e[E_ABS]), e[E_PARENT], fnum(e[E_REL]), e[E_TYPE], vn))
        self.vtree.delete(*self.vtree.get_children())
        for i, v in enumerate(seq.variables):
            self.vtree.insert("", "end", iid=str(i), values=(i, v[V_NAME], fnum(v[V_VAL])))
        self.info.delete("1.0", "end")
        lines = [u"File: %s" % (seq.path or u""), u"Format: %s" % seq.fmt,
                 u"Edges: %d   Variables: %d   Channels: %d   Sets: %d" % (len(seq.edges), len(seq.variables), len(seq.grid), seq.nsets),
                 u"Cycle length: %s ms" % fnum(seq.cycle_length()), u""]
        for k in ("Target \nResolution (us):", "Number of installed cards", "Device number for timing card", "External vi"):
            lines.append(u"%s: %s" % (k.replace("\n", " "), seq.data.get(k)))
        probs = seq.check()
        lines.append(u"")
        lines.append(u"Consistency: %s" % (u"ok" if not probs else u"%d problems" % len(probs)))
        lines.extend(probs[:30])
        self.info.insert("1.0", u"\n".join(lines))
        self.refresh_status()

    def refresh_status(self):
        if not self.seq:
            self.status.configure(text=u"no sequence loaded")
            return
        self.status.configure(text=u"%s%s   edges %d   channels %d   cycle %s ms   ramp problems %d" % (
            os.path.basename(self.seq.path or u"untitled"), u" *" if self.dirty else u"",
            len(self.seq.edges), len(self.seq.grid), fnum(self.seq.cycle_length()), len(self.grid.conflicts) // 2))

    def mark_dirty(self, structural=False):
        self.dirty = True
        if structural:
            self.grid.refresh_order()
            self.refresh_lists()
        else:
            self.grid.redraw()
            self.refresh_status()
        self.check_ramps(quiet=True)

    def after_external_change(self):
        self.dirty = True
        self.grid.refresh_order()
        self.refresh_lists()
        self.check_ramps(quiet=True)

    # ---- ramps
    def _ramp_text(self, p):
        kind, r1, r2, g = p
        n1 = self.seq.grid[r1.ch][0][K_NAME]
        s = u"%s: %s step %s ms (%s..%s ms)" % (kind, n1, fnum(r1.step), fnum(r1.t0), fnum(r1.t1))
        if r2:
            n2 = self.seq.grid[r2.ch][0][K_NAME]
            s += u" with %s step %s ms (%s..%s ms): common step %d us" % (n2, fnum(r2.step), fnum(r2.t0), fnum(r2.t1), g)
        return s

    def check_ramps(self, quiet=False):
        if not self.seq:
            return
        probs, ramps = self.seq.check_ramps(self.set_index)
        self.ramp_problems = probs
        self.grid.conflicts = set()
        self.rtree.delete(*self.rtree.get_children())
        for n, p in enumerate(probs):
            kind, r1, r2, g = p
            self.grid.conflicts.add((r1.ch, r1.i0))
            if r2:
                self.grid.conflicts.add((r2.ch, r2.i0))
            where = u"%s @ %s" % (self.seq.grid[r1.ch][0][K_NAME], self.seq.edges[r1.i0][E_NAME])
            if r2:
                where += u"  +  %s @ %s" % (self.seq.grid[r2.ch][0][K_NAME], self.seq.edges[r2.i0][E_NAME])
            self.rtree.insert("", "end", iid=str(n), values=(kind, where))
        self.grid.redraw()
        self.refresh_status()
        if not quiet:
            if probs:
                self.nb.select(2)
                messagebox.showwarning("Check ramps", u"%d ramp problems (listed in the Ramps tab, cells outlined in magenta):\n\n%s"
                                       % (len(probs), u"\n".join(self._ramp_text(p) for p in probs[:8])))
            else:
                messagebox.showinfo("Check ramps", u"%d ramps, no step-size conflicts." % len(ramps))

    def _ramp_selected(self, e=None):
        sel = self.rtree.selection()
        if sel and self.seq:
            kind, r1, r2, g = self.ramp_problems[int(sel[0])]
            self.grid.row0 = max(0, r1.ch - 3)
            self.grid.scroll_to_edge(r1.i0)
            self.grid.sel = set([(r1.ch, r1.i0)] + ([(r2.ch, r2.i0)] if r2 else []))
            self.grid.redraw()

    # ---- interaction
    def _width_changed(self):
        try:
            self.grid.set_cell_width(int(self.width_var.get()))
        except ValueError:
            pass

    def _zoom(self, d):
        self.width_var.set(u"%d" % max(24, min(160, self.grid.cell_w + d)))
        self._width_changed()

    def _set_changed(self, e=None):
        self.set_index = int(self.set_box.get().split(u" ", 1)[0])
        self.grid.redraw()
        self.check_ramps(quiet=True)

    def show_cell_info(self, ch, ei):
        c = self.seq.grid[ch][self.set_index]
        a, d, tc, f, st = (Sequence.cell_value(c, x, ei) for x in (K_ANLG, K_DIG, K_TC, K_FUNC, K_STEP))
        e = self.seq.edges[ei]
        self.cell_info.configure(text=u"%s @ edge %d '%s' (%s ms):  analog %s   digital %s   ramp %s   step %s ms   time const %s"
                                 % (c[K_NAME], ei, e[E_NAME], fnum(e[E_ABS]), fnum(a) or u"-", d, f or u"-", fnum(st), fnum(tc)))

    def edit_cell(self, ch, ei):
        CellDialog(self.root, self, [(ch, ei)])

    def edit_selected_cells(self):
        if self.seq and self.grid.sel:
            CellDialog(self.root, self, sorted(self.grid.sel))

    def select_channel_row(self):
        if self.seq and self.grid.sel:
            rows = set(r for r, _ in self.grid.sel)
            self.grid.sel = set((r, ei) for r in rows for ei in self.grid.order)
            self.grid.redraw()

    def clear_selection(self):
        self.grid.sel = set()
        self.grid.redraw()

    def select_edge(self, ei):
        try:
            self.etree.selection_set(str(ei))
            self.etree.see(str(ei))
        except tk.TclError:
            pass

    def _edge_selected(self, e=None):
        sel = self.etree.selection()
        if sel:
            self.grid.scroll_to_edge(int(sel[0]))

    def edit_selected_edge(self):
        sel = self.etree.selection()
        if sel:
            self.edit_edge(int(sel[0]))

    def edit_edge(self, ei):
        if not self.seq:
            return
        EdgeDialog(self.root, self, ei)

    def delete_selected_edge(self):
        sel = self.etree.selection()
        if not sel or not self.seq:
            return
        i = int(sel[0])
        if messagebox.askyesno("Delete edge", u"Delete edge %d '%s'? Children are re-parented." % (i, self.seq.edges[i][E_NAME])):
            self.seq.delete_edge(i)
            self.mark_dirty(structural=True)

    def add_variable(self):
        if not self.seq:
            return
        name = simpledialog.askstring("Add variable", "Variable name:")
        if not name:
            return
        val = simpledialog.askfloat("Add variable", "Value (ms):", initialvalue=0.0)
        if val is None:
            return
        self.seq.add_variable(name, val)
        self.mark_dirty(structural=True)

    def edit_variable(self):
        sel = self.vtree.selection()
        if not sel:
            return
        k = int(sel[0])
        v = self.seq.variables[k]
        val = simpledialog.askfloat("Variable", u"%s (ms):" % v[V_NAME], initialvalue=v[V_VAL])
        if val is None:
            return
        v[V_VAL] = val
        self.seq.recompute_times()
        self.mark_dirty(structural=True)

    def add_channel(self):
        if not self.seq:
            return
        name = simpledialog.askstring("Add channel", "Channel name:")
        if not name:
            return
        card = simpledialog.askinteger("Add channel", "Card #:", initialvalue=1)
        chan = simpledialog.askinteger("Add channel", "Channel #:", initialvalue=0)
        sig = simpledialog.askinteger("Add channel", "Signal type (0 analog, 1 digital):", initialvalue=0)
        if None in (card, chan, sig):
            return
        self.seq.add_channel(name, card, chan, sig)
        self.mark_dirty(structural=True)

    def delete_channel(self):
        if not self.seq or not self.grid.sel:
            messagebox.showinfo("Delete channel", "Click a cell of the channel first.")
            return
        ch = sorted(self.grid.sel)[0][0]
        name = self.seq.grid[ch][0][K_NAME]
        if messagebox.askyesno("Delete channel", u"Delete channel '%s'?" % name):
            self.seq.delete_channel(ch)
            self.grid.sel = set()
            self.mark_dirty(structural=True)

    def repair(self):
        if self.seq:
            n = self.seq.repair()
            messagebox.showinfo("Repair", u"%d channel arrays padded or trimmed to the edge count." % n)
            self.mark_dirty(structural=True)

    def plot(self):
        if not self.seq:
            return
        chans = sorted(set(r for r, _ in self.grid.sel))
        PlotWindow(self, self.seq, None, chans)

    def compare(self):
        if not self.seq:
            messagebox.showinfo("Compare", "Open a sequence first (it becomes A).")
            return
        path = filedialog.askopenfilename(title="Sequence B", filetypes=[("Supertime sequence", "*.dt4 *.dt3"), ("All", "*")])
        if not path:
            return
        try:
            b = Sequence.load(path)
        except Exception as e:
            messagebox.showerror("Open failed", u"%s" % e)
            return
        CompareWindow(self, self.seq, b)


def main():
    root = tk.Tk()
    App(root, sys.argv[1] if len(sys.argv) > 1 else None)
    root.mainloop()


if __name__ == "__main__":
    main()
