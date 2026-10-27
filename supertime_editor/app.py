# -*- coding: utf-8 -*-
"""Supertime sequence editor: a Tkinter desktop app to view, edit and compare .dt4 files.

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
                    K_STEP, E_ABS, E_NAME, E_PARENT, E_REL, E_VARS, E_TYPE, V_NAME, V_VAL)
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
FUNC_ABBR = {u"": u"", u"Linear": u"L", u"Exponential": u"E", u"Cubic": u"C", u"Custom": u"K",
             u"Optical: 1/(1+t)^2": u"O", u"Optical with offset": u"O+", u"Depth lin freq const": u"D"}


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
        self.sel = None
        self.cell_w = CELL_W
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
        self.canvas.bind("<Double-Button-1>", self._dblclick)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Shift-MouseWheel>", self._hwheel)
        self.canvas.bind("<Button-4>", lambda e: self._scroll_rows(-3))
        self.canvas.bind("<Button-5>", lambda e: self._scroll_rows(3))
        self.tip = None

    def set_sequence(self, seq):
        self.seq = seq
        self.col0 = self.row0 = 0
        self.sel = None
        self.refresh_order()

    def refresh_order(self):
        self.order = self.seq.edge_order() if self.seq else []
        self.redraw()

    # ---- geometry
    def _visible(self):
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        ncol = max(1, (w - ROW_HDR_W) // self.cell_w + 1)
        nrow = max(1, (h - HDR_H) // CELL_H + 1)
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
        r = self.row0 + (y - HDR_H) // CELL_H
        if self.seq and c < len(self.order) and r < len(self.seq.grid):
            return r, self.order[c]
        return None

    # ---- drawing
    def redraw(self):
        cv = self.canvas
        cv.delete("all")
        if not self.seq:
            return
        seq = self.seq
        ncol, nrow = self._visible()
        cols = self.order[self.col0:self.col0 + ncol]
        rows = range(self.row0, min(len(seq.grid), self.row0 + nrow))
        # scrollbars
        n = len(self.order) or 1
        self.hbar.set(self.col0 / n, min(1.0, (self.col0 + ncol) / n))
        m = len(seq.grid) or 1
        self.vbar.set(self.row0 / m, min(1.0, (self.row0 + nrow) / m))
        W = self.cell_w
        small = ("TkDefaultFont", 9 if W >= 44 else 8)
        maxchars = max(3, (W - 6) // 7)
        # column headers
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
        # rows
        for j, r in enumerate(rows):
            y = HDR_H + j * CELL_H
            ch = seq.grid[r][self.app.set_index]
            cv.create_rectangle(0, y, ROW_HDR_W, y + CELL_H, fill=C_ROWHDR, outline=C_GRIDLINE)
            cv.create_text(4, y + CELL_H // 2, text=u"%s  (%d.%d)" % (ch[K_NAME][:22], ch[K_CARD], ch[K_CHAN]),
                           anchor="w", font=("TkDefaultFont", 10), fill=TXT)
            digital = ch[K_SIG] == 1
            for k, ei in enumerate(cols):
                x = ROW_HDR_W + k * W
                a = Sequence.cell_value(ch, K_ANLG, ei)
                d = Sequence.cell_value(ch, K_DIG, ei)
                f = Sequence.cell_value(ch, K_FUNC, ei)
                fill = C_EMPTY
                txt = u""
                if digital:
                    if d != -1:
                        txt = u"1" if d else u"0"
                        fill = C_DIG1 if d else C_DIG0
                else:
                    if not lvcore.is_nan(a):
                        txt = fnum(a, 4)
                        fill = C_ANALOG
                leftover = False
                if f:
                    if txt:                                   # value + ramp function: a real ramp
                        txt = txt + u" " + abbr_func(f)
                        fill = C_RAMP
                    else:                                     # function set but no value: inert leftover
                        leftover = True
                selected = self.sel == (r, ei)
                cv.create_rectangle(x, y, x + W, y + CELL_H, fill=fill,
                                    outline="#e00000" if selected else C_GRIDLINE, width=2 if selected else 1)
                if txt:
                    cv.create_text(x + 3, y + CELL_H // 2, text=txt[:maxchars], anchor="w", font=small, fill=TXT)
                elif leftover and self.app.show_leftovers.get():
                    cv.create_text(x + W - 3, y + CELL_H // 2, text=abbr_func(f), anchor="e",
                                   font=("TkDefaultFont", 8), fill="#a0a0a0")
        cv.create_rectangle(0, 0, ROW_HDR_W, HDR_H, fill="#d4d4d4", outline=C_GRIDLINE)
        cv.create_text(6, HDR_H - 10, anchor="w", font=("TkDefaultFont", 9), fill=TXT,
                       text=u"%d channels x %d edges" % (len(seq.grid), len(self.order)))

    # ---- interaction
    def _click(self, e):
        hit = self._cell_at(e.x, e.y)
        if hit:
            self.sel = hit
            self.app.show_cell_info(*hit)
            self.redraw()
        elif e.y < HDR_H and e.x >= ROW_HDR_W:
            c = self.col0 + (e.x - ROW_HDR_W) // self.cell_w
            if c < len(self.order):
                self.app.select_edge(self.order[c])

    def _dblclick(self, e):
        hit = self._cell_at(e.x, e.y)
        if hit:
            self.app.edit_cell(*hit)
        elif e.y < HDR_H and e.x >= ROW_HDR_W:
            c = self.col0 + (e.x - ROW_HDR_W) // self.cell_w
            if c < len(self.order):
                self.app.edit_edge(self.order[c])

    def set_cell_width(self, w):
        self.cell_w = max(24, min(160, int(w)))
        self.redraw()


# ======================================================================= dialogs
class CellDialog(simpledialog.Dialog):
    def __init__(self, parent, app, ch, ei):
        self.app = app
        self.ch = ch
        self.ei = ei
        seq = app.seq
        c = seq.grid[ch][app.set_index]
        self.vals = [Sequence.cell_value(c, f, ei) for f in (K_ANLG, K_DIG, K_TC, K_FUNC, K_STEP)]
        self.title_text = u"%s @ %s" % (c[K_NAME], seq.edges[ei][E_NAME])
        simpledialog.Dialog.__init__(self, parent, self.title_text)

    def body(self, master):
        a, d, tc, f, st = self.vals
        tk.Label(master, text=u"Analog value (blank = no change)").grid(row=0, column=0, sticky="w")
        self.e_a = tk.Entry(master)
        self.e_a.insert(0, fnum(a))
        self.e_a.grid(row=0, column=1)
        tk.Label(master, text=u"Digital (-1 no change, 0, 1)").grid(row=1, column=0, sticky="w")
        self.e_d = tk.Entry(master)
        self.e_d.insert(0, u"%d" % d)
        self.e_d.grid(row=1, column=1)
        tk.Label(master, text=u"Ramp function").grid(row=2, column=0, sticky="w")
        self.e_f = ttk.Combobox(master, values=lvcore.function_types(), state="readonly")
        self.e_f.set(f)
        self.e_f.grid(row=2, column=1)
        tk.Label(master, text=u"Step size (ms)").grid(row=3, column=0, sticky="w")
        self.e_s = tk.Entry(master)
        self.e_s.insert(0, fnum(st))
        self.e_s.grid(row=3, column=1)
        tk.Label(master, text=u"Time constant").grid(row=4, column=0, sticky="w")
        self.e_t = tk.Entry(master)
        self.e_t.insert(0, fnum(tc))
        self.e_t.grid(row=4, column=1)
        return self.e_a

    def validate(self):
        try:
            a = self.e_a.get().strip()
            self.result = {K_ANLG: float(a) if a else lvcore.FILE_NAN,
                           K_DIG: int(self.e_d.get()),
                           K_FUNC: self.e_f.get(),
                           K_STEP: float(self.e_s.get() or 1.0),
                           K_TC: float(self.e_t.get() or 0.0)}
            return True
        except ValueError as e:
            messagebox.showerror("Bad value", str(e))
            return False

    def apply(self):
        self.app.seq.repair()
        self.app.seq.set_cell(self.ch, self.ei, self.app.set_index, **self.result)
        self.app.mark_dirty()


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


# ======================================================================= compare window
class CompareWindow(tk.Toplevel):
    KINDS = [u"all", u"cell", u"edge", u"edge-missing", u"channel", u"channel-missing", u"variable", u"setting"]

    def __init__(self, app, seq_a, seq_b):
        tk.Toplevel.__init__(self, app.root)
        self.app = app
        self.a = seq_a
        self.b = seq_b
        self.title(u"Compare: A = %s   |   B = %s" % (os.path.basename(seq_a.path or "A"), os.path.basename(seq_b.path or "B")))
        self.geometry("1100x600")
        top = tk.Frame(self)
        top.pack(fill="x")
        tk.Label(top, text=u"Show:").pack(side="left")
        self.kind = ttk.Combobox(top, values=self.KINDS, state="readonly", width=16)
        self.kind.set(u"all")
        self.kind.pack(side="left")
        self.kind.bind("<<ComboboxSelected>>", lambda e: self.fill())
        tk.Label(top, text=u"  channel filter:").pack(side="left")
        self.chan_filter = tk.Entry(top, width=18)
        self.chan_filter.pack(side="left")
        self.chan_filter.bind("<Return>", lambda e: self.fill())
        tk.Button(top, text=u"Copy A -> B (selected)", command=lambda: self.copy_sel("A->B")).pack(side="left", padx=4)
        tk.Button(top, text=u"Copy B -> A (selected)", command=lambda: self.copy_sel("B->A")).pack(side="left", padx=4)
        tk.Button(top, text=u"Unify all A -> B", command=lambda: self.unify("A->B")).pack(side="left", padx=4)
        tk.Button(top, text=u"Unify all B -> A", command=lambda: self.unify("B->A")).pack(side="left", padx=4)
        tk.Button(top, text=u"Save A", command=lambda: self.save(self.a)).pack(side="left", padx=4)
        tk.Button(top, text=u"Save B as...", command=lambda: self.save(self.b, True)).pack(side="left", padx=4)
        self.summary = tk.Label(self, anchor="w")
        self.summary.pack(fill="x")
        cols = ("kind", "where", "field", "A", "B")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", selectmode="extended")
        for c, w in zip(cols, (100, 420, 110, 160, 160)):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="w")
        vs = tk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.tree.bind("<Double-Button-1>", self.goto)
        self.cmp = Comparison(self.a, self.b)
        self.fill()

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
                break           # indices change after a structural edit: recompare first
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

    def save(self, seq, ask=False):
        path = seq.path
        if ask or not path:
            path = filedialog.asksaveasfilename(defaultextension=".dt4", initialfile=os.path.basename(path or "sequence.dt4"))
            if not path:
                return
        seq.save(path)
        self.app.after_external_change()
        self.title(u"Compare: A = %s   |   B = %s" % (os.path.basename(self.a.path or "A"), os.path.basename(self.b.path or "B")))

    def goto(self, e):
        sel = self._selected()
        if sel and sel[0].kind == "cell" and sel[0].data.get("ea") is not None:
            self.app.grid.scroll_to_edge(sel[0].data["ea"])
            ch = sel[0].data.get("ia")
            if ch is not None:
                self.app.grid.row0 = max(0, ch - 3)
                self.app.grid.sel = (ch, sel[0].data["ea"])
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
        self._menu()
        pane = tk.PanedWindow(root, orient="horizontal", sashwidth=5)
        pane.pack(fill="both", expand=True)
        left = tk.Frame(pane, width=380)
        pane.add(left)
        self.nb = ttk.Notebook(left)
        self.nb.pack(fill="both", expand=True)
        # edges
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
        # variables
        f2 = tk.Frame(self.nb)
        self.nb.add(f2, text=u"Variables")
        self.vtree = ttk.Treeview(f2, columns=("i", "name", "value"), show="headings")
        for c, w in zip(("i", "name", "value"), (36, 220, 80)):
            self.vtree.heading(c, text=c)
            self.vtree.column(c, width=w, anchor="w")
        self.vtree.pack(fill="both", expand=True)
        self.vtree.bind("<Double-Button-1>", lambda e: self.edit_variable())
        # settings
        f3 = tk.Frame(self.nb)
        self.nb.add(f3, text=u"Info")
        self.info = tk.Text(f3, width=40, wrap="word")
        self.info.pack(fill="both", expand=True)
        # grid
        right = tk.Frame(pane)
        pane.add(right, stretch="always")
        bar = tk.Frame(right)
        bar.pack(fill="x")
        tk.Label(bar, text=u"Data set:").pack(side="left")
        self.set_box = ttk.Combobox(bar, values=[u"0"], state="readonly", width=24)
        self.set_box.set(u"0")
        self.set_box.pack(side="left")
        self.set_box.bind("<<ComboboxSelected>>", self._set_changed)
        tk.Button(bar, text=u"Add edge", command=lambda: self.edit_edge(None)).pack(side="left", padx=3)
        tk.Button(bar, text=u"Delete edge", command=self.delete_selected_edge).pack(side="left", padx=3)
        tk.Button(bar, text=u"Add variable", command=self.add_variable).pack(side="left", padx=3)
        tk.Button(bar, text=u"Add channel", command=self.add_channel).pack(side="left", padx=3)
        tk.Button(bar, text=u"Delete channel", command=self.delete_channel).pack(side="left", padx=3)
        tk.Button(bar, text=u"Compare with...", command=self.compare).pack(side="left", padx=12)
        self.show_leftovers = tk.BooleanVar(value=True)
        tk.Checkbutton(bar, text=u"grey ramp leftovers", variable=self.show_leftovers,
                       command=lambda: self.grid.redraw()).pack(side="left", padx=6)
        tk.Label(bar, text=u"  Column width:").pack(side="left")
        self.width_var = tk.StringVar(value=u"%d" % CELL_W)
        sp = tk.Spinbox(bar, from_=24, to=160, increment=4, width=4, textvariable=self.width_var,
                        command=self._width_changed)
        sp.pack(side="left")
        sp.bind("<Return>", lambda e: self._width_changed())
        root.bind("<Control-equal>", lambda e: self._zoom(4))
        root.bind("<Control-plus>", lambda e: self._zoom(4))
        root.bind("<Control-minus>", lambda e: self._zoom(-4))
        self.cell_info = tk.Label(right, anchor="w", relief="sunken")
        self.cell_info.pack(fill="x")
        self.grid = SequenceGrid(right, self)
        self.grid.pack(fill="both", expand=True)
        self.status = tk.Label(root, anchor="w", relief="sunken")
        self.status.pack(fill="x")
        root.protocol("WM_DELETE_WINDOW", self.quit)
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
        fm.add_command(label=u"Repair channel arrays", command=self.repair)
        fm.add_separator()
        fm.add_command(label=u"Quit", command=self.quit)
        m.add_cascade(label=u"File", menu=fm)
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
        if problems and not messagebox.askyesno("Save", u"%d consistency problems:\n%s\n\nSave anyway?" % (len(problems), u"\n".join(problems[:5]))):
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
        self.status.configure(text=u"%s%s   edges %d   channels %d   cycle %s ms" % (
            os.path.basename(self.seq.path or u"untitled"), u" *" if self.dirty else u"",
            len(self.seq.edges), len(self.seq.grid), fnum(self.seq.cycle_length())))

    def mark_dirty(self, structural=False):
        self.dirty = True
        if structural:
            self.grid.refresh_order()
            self.refresh_lists()
        else:
            self.grid.redraw()
            self.refresh_status()

    def after_external_change(self):
        """Called by the compare window after it changed A (the sequence shown here)."""
        self.dirty = True
        self.grid.refresh_order()
        self.refresh_lists()

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

    def show_cell_info(self, ch, ei):
        c = self.seq.grid[ch][self.set_index]
        a, d, tc, f, st = (Sequence.cell_value(c, x, ei) for x in (K_ANLG, K_DIG, K_TC, K_FUNC, K_STEP))
        e = self.seq.edges[ei]
        self.cell_info.configure(text=u"%s @ edge %d '%s' (%s ms):  analog %s   digital %s   ramp %s   step %s ms   time const %s"
                                 % (c[K_NAME], ei, e[E_NAME], fnum(e[E_ABS]), fnum(a) or u"-", d, f or u"-", fnum(st), fnum(tc)))

    def edit_cell(self, ch, ei):
        CellDialog(self.root, self, ch, ei)

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
        ch = self.grid.sel[0]
        name = self.seq.grid[ch][0][K_NAME]
        if messagebox.askyesno("Delete channel", u"Delete channel '%s'?" % name):
            self.seq.delete_channel(ch)
            self.grid.sel = None
            self.mark_dirty(structural=True)

    def repair(self):
        if self.seq:
            n = self.seq.repair()
            messagebox.showinfo("Repair", u"%d channel arrays padded or trimmed to the edge count." % n)
            self.mark_dirty(structural=True)

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
