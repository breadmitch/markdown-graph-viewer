#!/usr/bin/env python3
"""
Standalone Markdown Graph Viewer

A local, read-only desktop graph viewer for ordinary Markdown/text folders.
No Obsidian dependency. No scraper-specific logic. No network calls.

Run:
    python md_graph_gui.py
    python md_graph_gui.py "C:\\path\\to\\notes"
"""

from __future__ import annotations

import argparse
import math
import random
import re
import sys
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_TITLE = "Markdown Graph Viewer"
SUPPORTED_EXTS = {".md", ".markdown", ".txt"}

WIKI_LINK_RE = re.compile(r"!??\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
MD_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
TAG_RE = re.compile(r"(?<!\w)#([A-Za-z0-9_][A-Za-z0-9_/-]*)")
URL_RE = re.compile(r"^https?://", re.I)


@dataclass
class Node:
    id: str
    label: str
    kind: str = "file"  # file, tag, unresolved, external
    path: Optional[Path] = None
    degree: int = 0
    x: float = 0.0
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    pinned: bool = False


@dataclass
class Edge:
    source: str
    target: str
    kind: str = "link"  # link, tag, external, unresolved
    label: str = ""


@dataclass
class GraphData:
    nodes: Dict[str, Node] = field(default_factory=dict)
    edges: List[Edge] = field(default_factory=list)
    adjacency: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))

    def add_node(self, node: Node) -> None:
        if node.id not in self.nodes:
            self.nodes[node.id] = node

    def add_edge(self, source: str, target: str, kind: str = "link", label: str = "") -> None:
        if source == target:
            return
        key = (source, target, kind)
        for e in self.edges:
            if (e.source, e.target, e.kind) == key:
                return
        self.edges.append(Edge(source, target, kind, label))
        self.adjacency[source].add(target)
        self.adjacency[target].add(source)
        if source in self.nodes:
            self.nodes[source].degree += 1
        if target in self.nodes:
            self.nodes[target].degree += 1


class MarkdownScanner:
    def __init__(self, include_tags: bool = True, include_unresolved: bool = True, include_external: bool = False):
        self.include_tags = include_tags
        self.include_unresolved = include_unresolved
        self.include_external = include_external

    def scan(self, folder: Path) -> GraphData:
        data = GraphData()
        files = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS]
        files.sort(key=lambda p: str(p.relative_to(folder)).lower())

        by_rel_no_ext: Dict[str, str] = {}
        by_stem: Dict[str, str] = {}

        for path in files:
            rel = path.relative_to(folder)
            node_id = self._file_id(path, folder)
            data.add_node(Node(id=node_id, label=path.stem, kind="file", path=path))
            by_rel_no_ext[str(rel.with_suffix("" )).replace("\\", "/").lower()] = node_id
            by_rel_no_ext[str(rel).replace("\\", "/").lower()] = node_id
            by_stem[path.stem.lower()] = node_id

        for path in files:
            node_id = self._file_id(path, folder)
            text = self._read_text(path)

            for raw in WIKI_LINK_RE.findall(text):
                target = raw.strip()
                self._add_link(data, node_id, target, by_rel_no_ext, by_stem)

            for raw in MD_LINK_RE.findall(text):
                target = raw.strip().split()[0].strip('<>')
                if target.startswith("#"):
                    continue
                if URL_RE.match(target):
                    if self.include_external:
                        ext_id = f"external:{target}"
                        data.add_node(Node(ext_id, target.replace("https://", "").replace("http://", ""), "external"))
                        data.add_edge(node_id, ext_id, "external", "external")
                    continue
                self._add_link(data, node_id, target, by_rel_no_ext, by_stem)

            if self.include_tags:
                for tag in sorted(set(TAG_RE.findall(text))):
                    tag_id = f"tag:{tag.lower()}"
                    data.add_node(Node(tag_id, f"#{tag}", "tag"))
                    data.add_edge(node_id, tag_id, "tag", "tag")

        return data

    def _add_link(self, data: GraphData, source: str, raw_target: str, by_rel_no_ext: Dict[str, str], by_stem: Dict[str, str]) -> None:
        clean = raw_target.strip().replace("\\", "/")
        clean = clean.split("#", 1)[0].strip()
        clean = clean[:-3] if clean.lower().endswith(".md") else clean
        if not clean:
            return
        target_id = by_rel_no_ext.get(clean.lower()) or by_stem.get(Path(clean).stem.lower())
        if target_id:
            data.add_edge(source, target_id, "link", "link")
        elif self.include_unresolved:
            unresolved_id = f"unresolved:{clean.lower()}"
            data.add_node(Node(unresolved_id, Path(clean).stem or clean, "unresolved"))
            data.add_edge(source, unresolved_id, "unresolved", "unresolved")

    @staticmethod
    def _read_text(path: Path) -> str:
        for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
            try:
                return path.read_text(encoding=enc, errors="replace")
            except Exception:
                pass
        return ""

    @staticmethod
    def _file_id(path: Path, root: Path) -> str:
        return "file:" + str(path.relative_to(root)).replace("\\", "/")


class GraphCanvas(tk.Canvas):
    COLORS = {
        "bg": "#111827",
        "panel": "#172033",
        "edge": "#4b5563",
        "edge_dim": "#273244",
        "text": "#e5e7eb",
        "muted": "#94a3b8",
        "file": "#7dd3fc",
        "tag": "#86efac",
        "unresolved": "#fca5a5",
        "external": "#c4b5fd",
        "selected": "#fbbf24",
    }

    def __init__(self, parent, on_select):
        super().__init__(parent, bg=self.COLORS["bg"], highlightthickness=0)
        self.on_select = on_select
        self.data = GraphData()
        self.visible_nodes: Set[str] = set()
        self.selected: Optional[str] = None
        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.drag_node: Optional[str] = None
        self.drag_canvas = False
        self.last_mouse = (0, 0)
        self.running = True
        self.bind("<ButtonPress-1>", self._down)
        self.bind("<B1-Motion>", self._move)
        self.bind("<ButtonRelease-1>", self._up)
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Button-4>", lambda e: self._zoom(e.x, e.y, 1.1))
        self.bind("<Button-5>", lambda e: self._zoom(e.x, e.y, 0.9))
        self.after(20, self._tick)

    def set_graph(self, data: GraphData, visible_nodes: Optional[Set[str]] = None) -> None:
        self.data = data
        self.visible_nodes = visible_nodes if visible_nodes is not None else set(data.nodes)
        self.selected = None
        self._init_positions()
        self.fit()
        self.draw()

    def update_visible(self, visible_nodes: Set[str]) -> None:
        self.visible_nodes = visible_nodes
        self.draw()

    def _init_positions(self) -> None:
        w = max(self.winfo_width(), 900)
        h = max(self.winfo_height(), 600)
        n = max(len(self.data.nodes), 1)
        radius = min(w, h) * 0.35
        for i, node in enumerate(self.data.nodes.values()):
            if node.x == 0 and node.y == 0:
                angle = 2 * math.pi * i / n
                node.x = radius * math.cos(angle) + random.uniform(-30, 30)
                node.y = radius * math.sin(angle) + random.uniform(-30, 30)

    def fit(self) -> None:
        if not self.visible_nodes:
            return
        xs = [self.data.nodes[n].x for n in self.visible_nodes if n in self.data.nodes]
        ys = [self.data.nodes[n].y for n in self.visible_nodes if n in self.data.nodes]
        if not xs or not ys:
            return
        w = max(self.winfo_width(), 800)
        h = max(self.winfo_height(), 500)
        minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
        spanx = max(maxx - minx, 100)
        spany = max(maxy - miny, 100)
        self.scale = min(w / (spanx + 220), h / (spany + 220), 1.5)
        cx = (minx + maxx) / 2
        cy = (miny + maxy) / 2
        self.offset_x = w / 2 - cx * self.scale
        self.offset_y = h / 2 - cy * self.scale

    def _tick(self) -> None:
        if self.running and len(self.visible_nodes) > 1:
            self._simulate()
            self.draw()
        self.after(30, self._tick)

    def _simulate(self) -> None:
        ids = list(self.visible_nodes)
        if len(ids) > 450:
            return
        nodes = self.data.nodes
        repulsion = 9000.0
        spring = 0.018
        rest = 135.0
        center_pull = 0.003

        for i, a_id in enumerate(ids):
            a = nodes.get(a_id)
            if not a or a.pinned:
                continue
            fx = -a.x * center_pull
            fy = -a.y * center_pull
            for b_id in ids[i+1:]:
                b = nodes.get(b_id)
                if not b:
                    continue
                dx = a.x - b.x
                dy = a.y - b.y
                d2 = dx*dx + dy*dy + 0.01
                if d2 > 160000:
                    continue
                f = repulsion / d2
                dist = math.sqrt(d2)
                ux, uy = dx / dist, dy / dist
                fx += ux * f
                fy += uy * f
                if not b.pinned:
                    b.vx -= ux * f
                    b.vy -= uy * f
            a.vx += fx
            a.vy += fy

        for e in self.data.edges:
            if e.source not in self.visible_nodes or e.target not in self.visible_nodes:
                continue
            a = nodes[e.source]
            b = nodes[e.target]
            dx = b.x - a.x
            dy = b.y - a.y
            dist = max(math.sqrt(dx*dx + dy*dy), 1)
            f = spring * (dist - rest)
            ux, uy = dx / dist, dy / dist
            if not a.pinned:
                a.vx += ux * f
                a.vy += uy * f
            if not b.pinned:
                b.vx -= ux * f
                b.vy -= uy * f

        for node_id in ids:
            n = nodes.get(node_id)
            if not n or n.pinned:
                continue
            n.vx *= 0.82
            n.vy *= 0.82
            n.x += max(min(n.vx, 8), -8)
            n.y += max(min(n.vy, 8), -8)

    def draw(self) -> None:
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        self.create_text(18, 16, anchor="nw", text=f"{len(self.visible_nodes)} nodes • {self._visible_edge_count()} links", fill=self.COLORS["muted"], font=("Segoe UI", 10))
        for e in self.data.edges:
            if e.source in self.visible_nodes and e.target in self.visible_nodes:
                a = self.data.nodes[e.source]
                b = self.data.nodes[e.target]
                ax, ay = self.world_to_screen(a.x, a.y)
                bx, by = self.world_to_screen(b.x, b.y)
                color = self.COLORS["edge"] if self.selected in {e.source, e.target} else self.COLORS["edge_dim"]
                width = 2 if self.selected in {e.source, e.target} else 1
                self.create_line(ax, ay, bx, by, fill=color, width=width)

        for node_id in self.visible_nodes:
            node = self.data.nodes.get(node_id)
            if not node:
                continue
            x, y = self.world_to_screen(node.x, node.y)
            if x < -100 or y < -100 or x > w + 100 or y > h + 100:
                continue
            r = self._radius(node)
            fill = self.COLORS.get(node.kind, self.COLORS["file"])
            outline = self.COLORS["selected"] if node_id == self.selected else "#0f172a"
            ow = 3 if node_id == self.selected else 1
            self.create_oval(x-r, y-r, x+r, y+r, fill=fill, outline=outline, width=ow, tags=("node", node_id))
            if node.pinned:
                self.create_text(x, y, text="•", fill="#111827", font=("Segoe UI", 12, "bold"))
            if r > 4 and self.scale > 0.25:
                label = node.label if len(node.label) <= 34 else node.label[:31] + "…"
                self.create_text(x, y + r + 12, text=label, fill=self.COLORS["text"], font=("Segoe UI", 9), tags=("label", node_id))

    def _visible_edge_count(self) -> int:
        return sum(1 for e in self.data.edges if e.source in self.visible_nodes and e.target in self.visible_nodes)

    def _radius(self, node: Node) -> float:
        base = {"file": 8, "tag": 7, "unresolved": 6, "external": 6}.get(node.kind, 7)
        return max(4, min(18, (base + math.sqrt(max(node.degree, 0)) * 1.8) * max(0.75, min(self.scale, 1.2))))

    def world_to_screen(self, x: float, y: float) -> Tuple[float, float]:
        return x * self.scale + self.offset_x, y * self.scale + self.offset_y

    def screen_to_world(self, x: float, y: float) -> Tuple[float, float]:
        return (x - self.offset_x) / self.scale, (y - self.offset_y) / self.scale

    def _hit_node(self, sx: float, sy: float) -> Optional[str]:
        best = None
        best_d = 999999
        for node_id in self.visible_nodes:
            node = self.data.nodes.get(node_id)
            if not node:
                continue
            x, y = self.world_to_screen(node.x, node.y)
            d = (x-sx)**2 + (y-sy)**2
            r = self._radius(node) + 8
            if d <= r*r and d < best_d:
                best = node_id
                best_d = d
        return best

    def _down(self, event):
        self.focus_set()
        self.last_mouse = (event.x, event.y)
        hit = self._hit_node(event.x, event.y)
        if hit:
            self.selected = hit
            self.drag_node = hit
            self.data.nodes[hit].pinned = True
            self.on_select(hit)
        else:
            self.drag_canvas = True
        self.draw()

    def _move(self, event):
        lx, ly = self.last_mouse
        dx, dy = event.x - lx, event.y - ly
        self.last_mouse = (event.x, event.y)
        if self.drag_node and self.drag_node in self.data.nodes:
            wx, wy = self.screen_to_world(event.x, event.y)
            n = self.data.nodes[self.drag_node]
            n.x, n.y = wx, wy
            n.vx = n.vy = 0
        elif self.drag_canvas:
            self.offset_x += dx
            self.offset_y += dy
        self.draw()

    def _up(self, event):
        self.drag_node = None
        self.drag_canvas = False

    def _wheel(self, event):
        self._zoom(event.x, event.y, 1.1 if event.delta > 0 else 0.9)

    def _zoom(self, sx: float, sy: float, factor: float):
        old = self.scale
        self.scale = max(0.08, min(5.0, self.scale * factor))
        wx, wy = (sx - self.offset_x) / old, (sy - self.offset_y) / old
        self.offset_x = sx - wx * self.scale
        self.offset_y = sy - wy * self.scale
        self.draw()

    def toggle_freeze(self) -> None:
        self.running = not self.running

    def unpin_all(self) -> None:
        for n in self.data.nodes.values():
            n.pinned = False


class GraphApp(tk.Tk):
    def __init__(self, start_folder: Optional[Path] = None):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1280x820")
        self.minsize(980, 620)
        self.configure(bg="#0f172a")
        self.folder: Optional[Path] = start_folder
        self.data = GraphData()
        self.filtered_nodes: Set[str] = set()
        self.selected: Optional[str] = None

        self.search_var = tk.StringVar()
        self.include_tags_var = tk.BooleanVar(value=True)
        self.include_unresolved_var = tk.BooleanVar(value=True)
        self.include_external_var = tk.BooleanVar(value=False)
        self.hide_isolated_var = tk.BooleanVar(value=False)
        self.local_only_var = tk.BooleanVar(value=False)
        self.depth_var = tk.IntVar(value=1)
        self.status_var = tk.StringVar(value="Choose a folder to begin.")

        self._style()
        self._build_ui()
        if self.folder:
            self.after(100, self.rescan)

    def _style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TFrame", background="#0f172a")
        style.configure("Panel.TFrame", background="#111827")
        style.configure("TLabel", background="#0f172a", foreground="#e5e7eb", font=("Segoe UI", 10))
        style.configure("Panel.TLabel", background="#111827", foreground="#e5e7eb", font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background="#111827", foreground="#94a3b8", font=("Segoe UI", 9))
        style.configure("Title.TLabel", background="#0f172a", foreground="#f8fafc", font=("Segoe UI", 16, "bold"))
        style.configure("TButton", font=("Segoe UI", 10), padding=6)
        style.configure("TCheckbutton", background="#0f172a", foreground="#e5e7eb", font=("Segoe UI", 10))
        style.map("TCheckbutton", background=[("active", "#0f172a")], foreground=[("active", "#ffffff")])

    def _build_ui(self):
        top = ttk.Frame(self, padding=(12, 10, 12, 8))
        top.pack(fill="x")
        ttk.Label(top, text="Markdown Graph Viewer", style="Title.TLabel").pack(side="left")
        ttk.Button(top, text="Open folder", command=self.choose_folder).pack(side="left", padx=(18, 6))
        ttk.Button(top, text="Rescan", command=self.rescan).pack(side="left", padx=6)
        ttk.Button(top, text="Fit", command=self.fit).pack(side="left", padx=6)
        ttk.Button(top, text="Freeze / resume", command=self.toggle_freeze).pack(side="left", padx=6)
        ttk.Button(top, text="Unpin all", command=self.unpin_all).pack(side="left", padx=6)
        ttk.Label(top, textvariable=self.status_var).pack(side="right")

        main = ttk.Frame(self)
        main.pack(fill="both", expand=True)

        left = ttk.Frame(main, style="Panel.TFrame", padding=10, width=270)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        ttk.Label(left, text="Search / filter", style="Panel.TLabel").pack(anchor="w")
        search = ttk.Entry(left, textvariable=self.search_var)
        search.pack(fill="x", pady=(6, 8))
        search.bind("<KeyRelease>", lambda e: self.apply_filters())

        for text, var in [
            ("Show tags", self.include_tags_var),
            ("Show unresolved links", self.include_unresolved_var),
            ("Show external URL nodes", self.include_external_var),
        ]:
            ttk.Checkbutton(left, text=text, variable=var, command=self.rescan).pack(anchor="w", pady=2)
        ttk.Checkbutton(left, text="Hide isolated files", variable=self.hide_isolated_var, command=self.apply_filters).pack(anchor="w", pady=2)
        ttk.Checkbutton(left, text="Local graph only", variable=self.local_only_var, command=self.apply_filters).pack(anchor="w", pady=(12, 2))

        depth_row = ttk.Frame(left, style="Panel.TFrame")
        depth_row.pack(fill="x", pady=(4, 10))
        ttk.Label(depth_row, text="Depth", style="Panel.TLabel").pack(side="left")
        ttk.Spinbox(depth_row, from_=1, to=5, textvariable=self.depth_var, width=5, command=self.apply_filters).pack(side="right")

        ttk.Label(left, text="Nodes", style="Panel.TLabel").pack(anchor="w", pady=(8, 4))
        self.node_list = tk.Listbox(left, bg="#0b1220", fg="#e5e7eb", selectbackground="#334155", activestyle="none", borderwidth=0, highlightthickness=1, highlightbackground="#334155", font=("Segoe UI", 10))
        self.node_list.pack(fill="both", expand=True)
        self.node_list.bind("<<ListboxSelect>>", self._list_select)

        center = ttk.Frame(main)
        center.pack(side="left", fill="both", expand=True)
        self.canvas = GraphCanvas(center, self.select_node)
        self.canvas.pack(fill="both", expand=True)

        right = ttk.Frame(main, style="Panel.TFrame", padding=10, width=360)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)
        ttk.Label(right, text="Preview", style="Panel.TLabel").pack(anchor="w")
        self.info_label = ttk.Label(right, text="Select a file or node.", style="Muted.TLabel", wraplength=330)
        self.info_label.pack(fill="x", pady=(6, 8))
        self.preview = tk.Text(right, bg="#0b1220", fg="#e5e7eb", insertbackground="#e5e7eb", wrap="word", borderwidth=0, highlightthickness=1, highlightbackground="#334155", font=("Consolas", 10))
        self.preview.pack(fill="both", expand=True)
        self.preview.configure(state="disabled")
        ttk.Label(right, text="Connections", style="Panel.TLabel").pack(anchor="w", pady=(10, 4))
        self.conn_list = tk.Listbox(right, height=8, bg="#0b1220", fg="#e5e7eb", selectbackground="#334155", activestyle="none", borderwidth=0, highlightthickness=1, highlightbackground="#334155", font=("Segoe UI", 10))
        self.conn_list.pack(fill="x")

    def choose_folder(self):
        folder = filedialog.askdirectory(title="Choose Markdown/text folder")
        if folder:
            self.folder = Path(folder)
            self.rescan()

    def rescan(self):
        if not self.folder:
            self.choose_folder()
            return
        if not self.folder.exists():
            messagebox.showerror(APP_TITLE, "Folder does not exist.")
            return
        scanner = MarkdownScanner(
            include_tags=self.include_tags_var.get(),
            include_unresolved=self.include_unresolved_var.get(),
            include_external=self.include_external_var.get(),
        )
        start = time.time()
        self.data = scanner.scan(self.folder)
        elapsed = time.time() - start
        self.status_var.set(f"{self.folder} • {len(self.data.nodes)} nodes • {len(self.data.edges)} links • {elapsed:.1f}s")
        self.canvas.set_graph(self.data)
        self.apply_filters(reset_selection=True)

    def apply_filters(self, reset_selection: bool = False):
        q = self.search_var.get().strip().lower()
        visible = set(self.data.nodes)
        if q:
            visible = {nid for nid, n in self.data.nodes.items() if q in n.label.lower() or q in nid.lower()}
            # include neighbors so search results make visual sense
            expanded = set(visible)
            for nid in list(visible):
                expanded.update(self.data.adjacency.get(nid, set()))
            visible = expanded
        if self.hide_isolated_var.get():
            visible = {nid for nid in visible if self.data.nodes[nid].degree > 0}
        if self.local_only_var.get() and self.selected:
            visible = self._local_nodes(self.selected, max(1, self.depth_var.get())) & visible
        self.filtered_nodes = visible
        if reset_selection:
            self.selected = None
        self.canvas.update_visible(visible)
        self._populate_node_list()

    def _local_nodes(self, start: str, depth: int) -> Set[str]:
        seen = {start}
        q = deque([(start, 0)])
        while q:
            nid, d = q.popleft()
            if d >= depth:
                continue
            for nb in self.data.adjacency.get(nid, set()):
                if nb not in seen:
                    seen.add(nb)
                    q.append((nb, d + 1))
        return seen

    def _populate_node_list(self):
        self.node_list.delete(0, "end")
        items = sorted((self.data.nodes[nid].label, nid) for nid in self.filtered_nodes if nid in self.data.nodes)
        self._list_index = []
        for label, nid in items:
            n = self.data.nodes[nid]
            icon = {"file": "📄", "tag": "#", "unresolved": "?", "external": "↗"}.get(n.kind, "•")
            self.node_list.insert("end", f"{icon} {label}")
            self._list_index.append(nid)

    def _list_select(self, event):
        sel = self.node_list.curselection()
        if sel:
            self.select_node(self._list_index[sel[0]])
            self.canvas.selected = self.selected
            self.canvas.draw()

    def select_node(self, node_id: str):
        self.selected = node_id
        node = self.data.nodes.get(node_id)
        if not node:
            return
        self.info_label.configure(text=f"{node.label}\nType: {node.kind} • Connections: {node.degree}")
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        if node.path and node.path.exists():
            text = MarkdownScanner._read_text(node.path)
            self.preview.insert("1.0", text[:30000])
        else:
            self.preview.insert("1.0", f"{node.label}\n\nThis is a generated graph node, not a local file.")
        self.preview.configure(state="disabled")
        self.conn_list.delete(0, "end")
        for nb in sorted(self.data.adjacency.get(node_id, set()), key=lambda x: self.data.nodes[x].label.lower()):
            n = self.data.nodes[nb]
            self.conn_list.insert("end", f"{n.label}  ({n.kind})")
        if self.local_only_var.get():
            self.apply_filters()

    def fit(self):
        self.canvas.fit()
        self.canvas.draw()

    def toggle_freeze(self):
        self.canvas.toggle_freeze()

    def unpin_all(self):
        self.canvas.unpin_all()
        self.canvas.draw()


def main():
    parser = argparse.ArgumentParser(description="Standalone local Markdown/text graph viewer.")
    parser.add_argument("folder", nargs="?", help="Folder containing .md, .markdown, or .txt files")
    args = parser.parse_args()
    start_folder = Path(args.folder).expanduser().resolve() if args.folder else None
    app = GraphApp(start_folder=start_folder)
    app.mainloop()


if __name__ == "__main__":
    main()
