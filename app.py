"""Galaxy Map Editor: edit the galactic conquest maps of Empire at War, Forces of Corruption and their mods, make new
ones, install them, and export them as a mod for the Steam Workshop."""
import ctypes
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import export
import gamedata
import project

APP_TITLE = "Galaxy Map Editor"
SAFE_WORLDS = 200          # the largest maps known to run well in the unmodified game
BG = "#0b0e16"
TEXT_TAGS = project.TEXT_TAGS
FALLBACK_COLORS = {"INDEPENDENT_FORCES": "#d9d9d9", "NEUTRAL": "#5a5a5a", "WARLORDS": "#a06a4a", "HOSTILE": "#7a3030"}
DELETE_WORLD_TEXT = ("Deleting a world permanently removes its information from that map selection.\n\n"
                     "Are you sure you wish to proceed?")

IMPORT_TEXT = ("Importing planets from another mod copies files from it. Ensure you have all the proper "
               "permissions before publishing. Are you sure you wish to continue?")

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = ImageTk = None


def resource(name):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def set_icon(win):
    try:
        win.iconbitmap(str(resource("editor.ico")))
    except Exception:
        pass


def game_running():
    try:
        out = subprocess.run(["tasklist", "/NH", "/FO", "CSV"], capture_output=True, text=True,
                             creationflags=0x08000000).stdout.lower()
        return "starwarsg.exe" in out or "sweaw.exe" in out
    except Exception:
        return False


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")


class ScrollFrame(ttk.Frame):
    def __init__(self, parent, width):
        super().__init__(parent, width=width)
        self.canvas = tk.Canvas(self, width=width - 18, highlightthickness=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.window, width=e.width))
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.inner.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self.wheel))
        self.inner.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def wheel(self, e):
        self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")


class DependencyDialog:
    """'This world comes from a submod...' with a 'Don't ask me again' box (it counts only after Yes)."""

    def __init__(self, parent, submod_name):
        self.result, self.dont_ask = False, False
        win = self.win = tk.Toplevel(parent)
        win.title(APP_TITLE)
        set_icon(win)
        win.transient(parent)
        win.resizable(False, False)
        ttk.Label(win, wraplength=420, justify="left", text=(
            f"This world comes from the submod \"{submod_name}\". Your map will then need that submod: players "
            "without it can't use your map.\n\nAdd it?")).pack(padx=16, pady=(14, 8), anchor="w")
        self.var = tk.BooleanVar(value=False)
        ttk.Checkbutton(win, text="Don't ask me again", variable=self.var).pack(padx=16, anchor="w")
        row = ttk.Frame(win)
        row.pack(padx=16, pady=12, anchor="e")
        ttk.Button(row, text="Yes", width=9, command=self.yes).pack(side="left", padx=4)
        ttk.Button(row, text="No", width=9, command=win.destroy).pack(side="left")
        win.grab_set()
        parent.wait_window(win)

    def yes(self):
        self.result, self.dont_ask = True, self.var.get()
        self.win.destroy()


# --- choosing the game ---
class Chooser:
    """The first window: which game or mod to edit."""

    def __init__(self, root, settings, on_choose):
        self.root, self.settings, self.on_choose = root, settings, on_choose
        root.title(APP_TITLE)
        self.frame = ttk.Frame(root)
        self.frame.pack(fill="both", expand=True)
        ttk.Label(self.frame, text=APP_TITLE, font=("Segoe UI", 16, "bold")).pack(pady=(14, 2))
        self.status = ttk.Label(self.frame, text="Looking for the game and its mods...", foreground="#555")
        self.status.pack(pady=(0, 8))
        self.list = ttk.Frame(self.frame)
        self.list.pack(fill="x", padx=16, pady=(0, 6))
        threading.Thread(target=self.detect, daemon=True).start()

    def detect(self):
        game_dir, workshop = gamedata.find_installs(self.settings)
        try:
            mods = gamedata.detect(game_dir, workshop, self.settings)
        except Exception:
            mods = []
        try:
            project.save_settings(self.settings)
        except OSError:
            pass
        self.root.after(0, lambda: self.show(game_dir, mods))

    def show(self, game_dir, mods):
        for c in self.list.winfo_children():
            c.destroy()
        if not mods:
            self.status.configure(text="Star Wars: Empire at War was not found. Choose its folder (it holds the "
                                       "GameData and corruption folders).")
            ttk.Button(self.list, text="Choose the game's folder...", command=self.choose_folder).pack(pady=8)
            return
        self.status.configure(text="Choose what to edit:")
        self.mods = mods
        holder = self.list
        rows_fit = max(6, int(self.root.winfo_screenheight() * 0.75) // 31)
        if len(mods) > rows_fit:                  # (more mods than the screen holds: a list that scrolls)
            box = ScrollFrame(self.list, 560)
            box.canvas.configure(height=rows_fit * 31)
            box.pack(fill="x")
            holder = box.inner
        for m in mods:
            row = ttk.Frame(holder)
            row.pack(fill="x", pady=2)
            ttk.Button(row, text=m["name"], width=60, command=lambda m=m: self.pick(game_dir, m)).pack(side="left")
            if m["submods"]:
                ttk.Label(row, text=f"  + {len(m['submods'])} submod(s)", foreground="#777").pack(side="left")
        ttk.Button(self.list, text="Choose another game folder...", command=self.choose_folder).pack(pady=(8, 4))

    def choose_folder(self):
        chosen = filedialog.askdirectory(title="Star Wars Empire at War folder")
        if chosen:
            self.settings["game"] = chosen
            project.save_settings(self.settings)
            self.status.configure(text="Looking for the game and its mods...")
            threading.Thread(target=self.detect, daemon=True).start()

    def pick(self, game_dir, mod):
        self.status.configure(text=f"Reading {mod['name']}...")
        self.root.config(cursor="watch")
        self.root.update()
        try:
            game = gamedata.Game(game_dir, mod)
            game.all_mods = getattr(self, "mods", [])
        except Exception as e:
            self.root.config(cursor="")
            messagebox.showerror(APP_TITLE, f"{mod['name']} could not be read:\n\n{e}")
            self.status.configure(text="Choose what to edit:")
            return
        self.root.config(cursor="")
        if not game.maps:
            messagebox.showinfo(APP_TITLE, f"{mod['name']} has no galactic conquest maps the editor can read.")
            self.status.configure(text="Choose what to edit:")
            return
        self.frame.destroy()
        self.root.geometry("1500x920")
        self.on_choose(game)


# --- the editor ---
class Editor:
    def __init__(self, root, game, settings, back):
        self.root, self.game, self.settings, self.back = root, game, settings, back
        self.model = None
        self.era = None
        self.scale, self.cx, self.cy = 0.5, 0.0, 0.0
        self.selected = None
        self.lane_from = None
        self.drag = None
        self.undo = []
        self.dirty = False
        self.photo = None
        self.incomplete_index = 0
        self.dont_ask_submod = False            # (this run only)
        self.tool = tk.StringVar(value="select")
        self.paint = tk.StringVar()
        self.move_on = tk.BooleanVar(value=False)
        self.show_names = tk.BooleanVar(value=True)
        self.show_spawns = tk.BooleanVar(value=False)
        self.show_excluded = tk.BooleanVar(value=False)
        self.flip = tk.BooleanVar(value=False)
        self.status = tk.StringVar()
        self.frame = ttk.Frame(root)
        self.frame.pack(fill="both", expand=True)
        self.build_ui()
        last = self.settings.get("last_map", {}).get(game.mod_id)
        try:
            if last and (Path(last) / "project.json").exists():
                self.open_project(last)
            else:
                self.open_mod_map(game.maps[0]["key"])
        except Exception:
            self.open_mod_map(game.maps[0]["key"])

    # --- layout ---
    def build_ui(self):
        top = ttk.Frame(self.frame)
        top.pack(side="top", fill="x", pady=(4, 0))
        ttk.Button(top, text="Export as mod...", command=self.export_dialog).pack(side="right", padx=4)
        ttk.Button(top, text="Save", width=7, command=self.save).pack(side="right", padx=4)
        ttk.Button(top, text="Undo", width=7, command=self.do_undo).pack(side="right")
        self.map_button = ttk.Button(top, text="Map", width=36, command=self.map_selector)
        self.map_button.pack(side="left", padx=4)
        self.date_frame = ttk.Frame(top)
        self.date_frame.pack(side="left", padx=4)
        for label, value in (("Select", "select"), ("Lanes", "lanes"), ("Paint owner", "paint"),
                             ):
            ttk.Radiobutton(top, text=label, value=value, variable=self.tool, command=self.tool_changed).pack(
                side="left", padx=3)
        self.paint_box = ttk.Combobox(top, textvariable=self.paint, state="readonly", width=34)
        self.paint_box.pack(side="left")
        ttk.Radiobutton(top, text="Create new planet", value="create", variable=self.tool,
                        command=self.tool_changed).pack(side="left", padx=(8, 3))
        ttk.Checkbutton(top, text="Move worlds", variable=self.move_on, command=self.move_changed).pack(side="left",
                                                                                                         padx=(8, 0))
        row = ttk.Frame(self.frame)
        row.pack(side="top", fill="x", pady=3)
        ttk.Button(row, text="Other Mods", command=self.go_back).pack(side="left", padx=4)
        ttk.Button(row, text="Find incomplete planets", command=self.next_incomplete).pack(side="left")
        ttk.Button(row, text="Restore default positions", command=self.restore_positions).pack(side="left", padx=4)
        ttk.Button(row, text="Import Excluded planets from mod...", command=self.import_dialog).pack(side="left")
        if self.game.tr_menu:
            ttk.Button(row, text="Menu buttons...", command=self.slots_window).pack(side="left")
        toggles = [("Names", self.show_names)]
        if self.game.warlords:
            toggles.append(("Proteus spawns", self.show_spawns))
        toggles += [("Excluded Worlds", self.show_excluded), ("Flip north/south", self.flip)]
        for text, var in toggles:
            ttk.Checkbutton(row, text=text, variable=var, command=self.redraw).pack(side="left", padx=6)
        self.find = ttk.Entry(row, width=16)
        self.find.pack(side="right", padx=(0, 6))
        self.find.bind("<Return>", lambda e: self.find_world())
        ttk.Label(row, text="Find:").pack(side="right", padx=(0, 2))

        body = ttk.Frame(self.frame)
        body.pack(side="top", fill="both", expand=True)
        self.canvas = tk.Canvas(body, background=BG, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        side = ScrollFrame(body, 410)
        side.pack(side="right", fill="y")
        side.pack_propagate(False)
        self.build_side(side.inner)
        status = ttk.Frame(self.frame)
        status.pack(side="bottom", fill="x")
        self.status_label = tk.Label(status, textvariable=self.status, anchor="w")
        self.status_label.pack(side="left", fill="x", expand=True, padx=4)

        c = self.canvas
        c.bind("<Configure>", self.on_configure)
        c.bind("<MouseWheel>", self.on_wheel)
        c.bind("<ButtonPress-1>", self.on_press)
        c.bind("<B1-Motion>", self.on_motion)
        c.bind("<ButtonRelease-1>", self.on_release)
        for b in ("<ButtonPress-2>", "<ButtonPress-3>"):
            c.bind(b, self.on_pan_start)
        for b in ("<B2-Motion>", "<B3-Motion>"):
            c.bind(b, self.on_pan)
        self.root.bind("<Control-z>", lambda e: self.do_undo())
        self.root.bind("<Control-s>", lambda e: self.save())
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def build_side(self, side):
        w = 380
        self.title_var = tk.StringVar(value="Click a world.")
        ttk.Label(side, textvariable=self.title_var, font=("Segoe UI", 12, "bold"), wraplength=w).pack(
            anchor="w", padx=8, pady=(8, 2))
        self.flags_var = tk.StringVar()
        ttk.Label(side, textvariable=self.flags_var, wraplength=w, foreground="#555").pack(anchor="w", padx=8)
        self.missing_var = tk.StringVar()
        tk.Label(side, textvariable=self.missing_var, wraplength=w, foreground="#c0392b", justify="left").pack(
            anchor="w", padx=8)

        def field_row(label):
            row = ttk.Frame(side)
            row.pack(fill="x", padx=8, pady=2)
            lab = ttk.Label(row, text=label, width=17)
            lab.pack(side="left")
            return row, lab
        row, _ = field_row("Name")
        self.name_entry = ttk.Entry(row, width=25)
        self.name_entry.pack(side="left", padx=4)
        self.name_entry.bind("<Return>", lambda e: self.rename())
        ttk.Button(row, text="Rename", command=self.rename).pack(side="left")
        row, self.owner_label = field_row("Owner")
        self.owner_box = ttk.Combobox(row, state="readonly", width=32)
        self.owner_box.pack(side="left", padx=4)
        self.owner_box.bind("<<ComboboxSelected>>", lambda e: self.set_owner(self.selected, self.owner_box.get()))
        row, _ = field_row("Position")
        ttk.Label(row, text="X").pack(side="left")
        self.x_entry = ttk.Entry(row, width=7)
        self.x_entry.pack(side="left", padx=2)
        ttk.Label(row, text="Y").pack(side="left")
        self.y_entry = ttk.Entry(row, width=7)
        self.y_entry.pack(side="left", padx=2)
        self.move_button = ttk.Button(row, text="Move", width=6, command=self.move_typed)
        self.move_button.pack(side="left", padx=2)
        row = ttk.Frame(side)
        row.pack(fill="x", padx=8, pady=4)
        self.remove_btn = ttk.Button(row, text="Remove from map", command=self.remove_world)
        self.remove_btn.pack(side="left")
        self.add_btn = ttk.Button(row, text="Add to map", command=self.add_world)
        self.add_btn.pack(side="left", padx=4)
        self.delete_btn = ttk.Button(row, text="Delete planet", command=self.delete_world)
        self.delete_btn.pack(side="left")
        self.lanes_var = tk.StringVar()
        ttk.Label(side, textvariable=self.lanes_var, wraplength=w, foreground="#555").pack(anchor="w", padx=8)

        ttk.Separator(side).pack(fill="x", padx=8, pady=6)
        ttk.Label(side, text="Build slots and station").pack(anchor="w", padx=8)
        self.slot_vars = {}
        for field, label in (("land_slots", "Land build slots"), ("space_slots", "Space build slots"),
                             ("station", "Space station level")):
            row, _ = field_row(label)
            var = tk.StringVar()
            spin = ttk.Spinbox(row, from_=0, to=99 if field != "station" else 5, width=5, textvariable=var,
                               command=lambda f=field: self.set_number(f))
            spin.pack(side="left", padx=4)
            spin.bind("<Return>", lambda e, f=field: self.set_number(f))
            spin.bind("<FocusOut>", lambda e, f=field: self.set_number(f))
            self.slot_vars[field] = var
        ttk.Label(side, wraplength=w, foreground="#777", text=(
            "Space station level: the highest station the world can have. A world that starts with an owner starts "
            "with its station built to this level.")).pack(anchor="w", padx=8)

        ttk.Separator(side).pack(fill="x", padx=8, pady=6)
        ttk.Label(side, text="Planet picture (the planet view in the game)").pack(anchor="w", padx=8)
        self.picture = tk.Canvas(side, width=220, height=124, background="#1d2230", highlightthickness=0)
        self.picture.pack(anchor="w", padx=8, pady=2)
        ttk.Button(side, text="Change picture...", command=self.change_picture).pack(anchor="w", padx=8)
        self.picture_var = tk.StringVar()
        ttk.Label(side, textvariable=self.picture_var, wraplength=w, foreground="#555").pack(anchor="w", padx=8)

        self.surface = tk.BooleanVar()
        ttk.Checkbutton(side, text="Land battles (the world has a surface)", variable=self.surface,
                        command=self.set_surface).pack(anchor="w", padx=8, pady=(6, 0))
        self.files = {}
        for key, label, kind in (("land", "Land battle map", "Maps"), ("space", "Space battle map", "Maps"),
                                 ("model", "Galaxy map model", "Models")):
            ttk.Label(side, text=label).pack(anchor="w", padx=8, pady=(4, 0))
            row = ttk.Frame(side)
            row.pack(fill="x", padx=8)
            box = ttk.Combobox(row, width=30)
            box.pack(side="left")
            box.bind("<Return>", lambda e, k=key: self.set_file(k))
            box.bind("<<ComboboxSelected>>", lambda e, k=key: self.set_file(k))
            box.bind("<FocusOut>", lambda e, k=key: self.set_file(k))
            ttk.Button(row, text="Browse...", width=9, command=lambda k=key, d=kind: self.browse_file(k, d)).pack(
                side="left", padx=2)
            ttk.Button(row, text="Open folder", width=11, command=lambda k=key, d=kind: self.open_folder(k, d)).pack(
                side="left")
            self.files[key] = box

        ttk.Separator(side).pack(fill="x", padx=8, pady=6)
        ttk.Label(side, text="Planet texts").pack(anchor="w", padx=8)
        self.text_boxes = {}
        for tag in TEXT_TAGS:
            ttk.Label(side, text=tag).pack(anchor="w", padx=8)
            box = tk.Text(side, height=5 if tag == "History" else 2, wrap="word", font=("Segoe UI", 9), width=47)
            box.pack(anchor="w", padx=8)
            self.text_boxes[tag] = box
        ttk.Button(side, text="Keep text changes", command=self.apply_texts).pack(anchor="e", padx=8, pady=6)

    def on_configure(self, e):
        if getattr(self, "need_fit", False) and e.width > 400:
            self.need_fit = False
            self.fit()
        self.redraw()

    def close_windows(self):
        """Every open popup and window of the editor (menus, lists, dialogs)."""
        self.close_drop()
        for w in self.root.winfo_children():
            if isinstance(w, tk.Toplevel):
                try:
                    w.destroy()
                except tk.TclError:
                    pass

    def go_back(self):
        if self.confirm_unsaved():
            self.close_windows()
            self.root.unbind("<Control-z>")
            self.root.unbind("<Control-s>")
            self.frame.destroy()
            self.back()

    # --- maps ---
    def projects(self):
        return project.list_projects(self.game.mod_id)

    def edit_folder(self, key):
        return project.projects_dir(self.game.mod_id) / f"Edit_{project.safe_name(key)}"

    def map_entries(self):
        """[(category, [(label, kind, value)])] for the map dropdown: the mod's maps, your maps, New ... map."""
        projects = self.projects()
        edited = {d["map"] for f, d in projects if d["kind"] == "edit" and (d.get("starts") or d.get("planets")
                                                                             or d.get("new_planets") or d.get("button"))}
        cats = []
        for m in self.game.maps:
            if m["category"] not in cats:
                cats.append(m["category"])
        for f, d in projects:
            if d["kind"] == "new" and d["category"] not in cats:
                cats.append(d["category"])
        out = []
        for cat in cats:
            items = []
            for m in [m for m in self.game.maps if m["category"] == cat]:
                label = m["title"] + ("   (changed)" if m["key"] in edited else "")
                if m["layer"]:
                    label += "   (from a submod)"
                items.append((label, "mod", m["key"]))
            mine = [(f, d) for f, d in projects if d["kind"] == "new" and d["category"] == cat]
            if mine:
                items.append(None)
                items += [((d.get("title") or f.name) + "   (your map)", "yours", str(f)) for f, d in mine]
            items += [None, (f"New {cat.lower()} map...", "new", cat)]
            out.append((cat, items))
        return out

    def map_selector(self):
        """The map dropdown: each list opens into its maps. Click a map to open it; right click: Copy from map,
        Reset to Default, Delete."""
        if getattr(self, "drop", None):
            self.close_drop()
            return
        menu_bg, hover, font = "#ffffff", "#cce8ff", ("Segoe UI", 9)
        self.drop = []

        def window(x, y):
            w = tk.Toplevel(self.root)
            w.overrideredirect(True)
            w.configure(background="#999999")
            w.geometry(f"+{x}+{y}")
            inner = tk.Frame(w, background=menu_bg)
            inner.pack(padx=1, pady=1)
            self.drop.append(w)
            return w, inner

        def row(parent, text, arrow=False):
            r = tk.Frame(parent, background=menu_bg)
            r.pack(fill="x")
            lab = tk.Label(r, text=text, background=menu_bg, font=font, anchor="w", padx=22, pady=3)
            lab.pack(side="left", fill="x", expand=True)
            if arrow:
                tk.Label(r, text="▸", background=menu_bg, font=font, padx=8).pack(side="right")
            widgets = [r] + list(r.winfo_children())

            def paint(color):
                for wd in widgets:
                    wd.configure(background=color)
            return widgets, paint

        def separator(parent):
            tk.Frame(parent, background="#d8d8d8", height=1).pack(fill="x", padx=4, pady=3)

        x, y = self.map_button.winfo_rootx(), self.map_button.winfo_rooty() + self.map_button.winfo_height()
        top, inner = window(x, y)
        state = {"sub": None, "paint": None}

        def open_sub(cat_widgets, items):
            if state["sub"]:
                state["sub"].destroy()
                self.drop.remove(state["sub"])
            top.update_idletasks()
            r = cat_widgets[0]
            sub, sub_inner = window(top.winfo_rootx() + top.winfo_width() - 2, r.winfo_rooty() - 1)
            state["sub"] = sub
            for item in items:
                if item is None:
                    separator(sub_inner)
                    continue
                label, kind, value = item
                widgets, paint = row(sub_inner, label)
                for wd in widgets:
                    wd.bind("<Enter>", lambda e, p=paint: p(hover))
                    wd.bind("<Leave>", lambda e, p=paint: p(menu_bg))
                    wd.bind("<Button-1>", lambda e, k=kind, v=value: self.drop_pick(k, v))
                    if kind in ("mod", "yours"):
                        wd.bind("<Button-3>", lambda e, k=kind, v=value: self.drop_context(e, k, v))

        for cat, items in self.map_entries():
            widgets, paint = row(inner, cat, arrow=True)

            def enter(e, w=widgets, p=paint, it=items):
                if state["paint"]:
                    state["paint"](menu_bg)
                p(hover)
                state["paint"] = p
                open_sub(w, it)
            for wd in widgets:
                wd.bind("<Enter>", enter)
                wd.bind("<Button-1>", enter)
        self.root.bind_all("<Button-1>", self.drop_outside, add="+")
        self.root.bind_all("<Escape>", lambda e: self.close_drop(), add="+")

    def drop_outside(self, e):
        if not getattr(self, "drop", None):
            return
        try:
            top = e.widget.winfo_toplevel()
        except Exception:
            top = None
        if top not in self.drop and e.widget is not self.map_button:
            self.close_drop()

    def close_drop(self):
        for w in getattr(self, "drop", None) or []:
            try:
                w.destroy()
            except Exception:
                pass
        self.drop = None
        try:
            self.root.unbind_all("<Button-1>")
            self.root.unbind_all("<Escape>")
        except Exception:
            pass

    def drop_pick(self, kind, value):
        self.close_drop()
        if kind == "mod":
            self.switch(lambda: self.open_mod_map(value))
        elif kind == "yours":
            self.switch(lambda: self.open_project(value))
        else:
            self.switch(lambda: self.new_map_dialog(value))

    def drop_context(self, e, kind, value):
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="Copy from map...", command=lambda: (self.close_drop(), self.copy_from_map(kind, value)))
        menu.add_command(label="Reset to Default", command=lambda: (self.close_drop(), self.reset_map(kind, value)))
        if kind == "yours":
            menu.add_command(label="Delete", command=lambda: (self.close_drop(), self.delete_map(value)))
        menu.tk_popup(e.x_root, e.y_root)

    def switch(self, action):
        if self.confirm_unsaved():
            action()

    def open_mod_map(self, key):
        folder = self.edit_folder(key)
        if (folder / "project.json").exists():
            self.open_project(str(folder))
            return
        info = self.game.map_info(key)
        data = project.new_project_data(self.game.mod_id, "edit", key, info["category"], info["layer"])
        self.load(folder, data)

    def open_project(self, folder):
        folder = Path(folder)
        data = read_json(folder / "project.json")
        base = data["template"] if data["kind"] == "new" else data["map"]
        if not self.game.map_info(base):
            messagebox.showwarning(APP_TITLE, "This map was made from a map that is no longer installed.")
            return
        self.load(folder, data)

    def load(self, folder, data):
        self.model = project.Model(self.game, folder, data)
        self.settings.setdefault("last_map", {})[self.game.mod_id] = str(folder)
        project.save_settings(self.settings)
        self.undo, self.dirty, self.selected, self.lane_from = [], False, None, None
        ticked = self.model.ticked_eras()
        self.era = ticked[0] if ticked else self.model.era_list()[0]
        factions = list(self.model.factions)
        self.paint_box["values"] = [self.faction_text(f) for f in factions]
        if factions:
            self.paint.set(self.faction_text("Independent_Forces" if "Independent_Forces" in factions else factions[0]))
        self.owner_box["values"] = self.paint_box["values"]
        self.build_dates()
        self.map_button.configure(text=self.model.title + ("  (your map)" if self.model.is_new else "") + "  ▾")
        self.root.title(f"{APP_TITLE} - {self.game.mod['name']} - {self.model.title}")
        self.need_fit = True
        self.fit()
        self.redraw()
        self.show(None)

    def faction_text(self, faction):
        return f"{self.game.faction_label(faction)}  [{faction}]"

    def faction_of(self, text):
        return text.rsplit("[", 1)[-1].rstrip("]").strip() if "[" in text else text

    def fit(self):
        worlds = self.model.worlds(self.era) or self.model.pool()
        pts = [self.pos(w) for w in worlds if self.pos(w)]
        if not pts:
            self.cx, self.cy, self.scale = 0, 0, 0.5
            return
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        self.cx, self.cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        self.root.update_idletasks()
        w, h = max(self.canvas.winfo_width(), 400), max(self.canvas.winfo_height(), 400)
        self.scale = min(w / (max(xs) - min(xs) + 120), h / (max(ys) - min(ys) + 120))

    def new_map_dialog(self, category):
        maps = [m for m in self.game.maps if m["category"] == category]
        win = tk.Toplevel(self.root)
        win.title(f"New {category.lower()} map")
        set_icon(win)
        win.transient(self.root)
        win.resizable(False, False)
        ttk.Label(win, text="Title (in the game's map list)").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 2))
        title = ttk.Entry(win, width=44)
        title.grid(row=1, column=0, columnspan=2, sticky="w", padx=10)
        ttk.Label(win, text="Description").grid(row=2, column=0, sticky="w", padx=10, pady=(8, 2))
        desc = tk.Text(win, width=50, height=4, wrap="word", font=("Segoe UI", 9))
        desc.grid(row=3, column=0, columnspan=2, padx=10)
        ttk.Label(win, text="Start from (its factions, start dates and story events)").grid(
            row=4, column=0, sticky="w", padx=10, pady=(8, 2))
        base = ttk.Combobox(win, state="readonly", width=46, values=[m["title"] for m in maps])
        base.grid(row=5, column=0, columnspan=2, sticky="w", padx=10)
        base.current(0)
        blank = tk.BooleanVar(value=False)
        ttk.Checkbutton(win, text="Start empty (no worlds or lanes; add them yourself)", variable=blank).grid(
            row=6, column=0, columnspan=2, sticky="w", padx=10, pady=6)
        year_var = None
        if category == "Historical" and self.game.tr_menu:
            row = ttk.Frame(win)
            row.grid(row=7, column=0, columnspan=2, sticky="w", padx=10)
            ttk.Label(row, text="Start date (fixed for this map):").pack(side="left")
            year_var = tk.StringVar(value=f"{maps[0]['year']:g}")
            ttk.Spinbox(row, from_=0, to=100, increment=0.5, width=6, textvariable=year_var).pack(side="left", padx=4)
            ttk.Label(row, text="ABY").pack(side="left")

        def create():
            name = title.get().strip()
            if not name:
                messagebox.showwarning(APP_TITLE, "Give the map a title.", parent=win)
                return
            m = maps[base.current()]
            year = None
            if year_var is not None:
                try:
                    year = float(year_var.get())
                except ValueError:
                    year = m["year"]
            folder = project.projects_dir(self.game.mod_id) / project.safe_name(name)
            n = 2
            while folder.exists():
                folder = project.projects_dir(self.game.mod_id) / f"{project.safe_name(name)}_{n}"
                n += 1
            data = project.new_project_data(self.game.mod_id, "new", None, category, m["layer"], template=m["key"],
                                            blank=blank.get(), title=name, description=desc.get("1.0", "end").strip(),
                                            year=year)
            data["slot"] = self.free_slot(category)
            win.destroy()
            self.load(folder, data)
            self.model.save()
            if blank.get():
                self.show_excluded.set(True)
                self.redraw()
            self.status.set(f"New map '{name}' made from {m['title']}.")
        ttk.Button(win, text="Create", command=create).grid(row=8, column=1, sticky="e", padx=10, pady=10)
        title.focus_set()

    def free_slot(self, category):
        if self.game.tr_menu:
            layout = export.button_layout(self.game, self.projects())
            return next((b for b in export.tr_buttons(category) if b not in layout), None)
        used = {d.get("slot") for _, d in self.projects() if d.get("slot")}
        used |= set(export.installed_slots(self.game, {self.install_folder_name()}))
        return next((s for s in export.std_slots() if s not in used), None)

    def copy_from_map(self, kind, value):
        """Right click > Copy from map: the chosen map's worlds, lanes and owners replace this map's."""
        if kind == "mod":
            self.switch(lambda: self.open_mod_map(value))
        else:
            self.switch(lambda: self.open_project(value))
        win = tk.Toplevel(self.root)
        win.title("Copy from map")
        set_icon(win)
        win.transient(self.root)
        win.resizable(False, False)
        ttk.Label(win, wraplength=440, text=f"Copy which map into {self.model.title}? Its worlds, lanes and owners "
                  "replace this map's (start dates the other map lacks take its first start).").pack(
            padx=12, pady=(12, 6), anchor="w")
        choices = list(self.game.maps)
        box = ttk.Combobox(win, state="readonly", width=58, values=[f"{m['category']}: {m['title']}" for m in choices])
        box.pack(padx=12)
        box.current(0)

        def go():
            src = choices[box.current()]
            win.destroy()
            folder = self.edit_folder(src["key"])
            if (folder / "project.json").exists():
                data = read_json(folder / "project.json")
            else:
                data = project.new_project_data(self.game.mod_id, "edit", src["key"], src["category"], src["layer"])
            other = project.Model(self.game, folder, data)
            self.remember()
            self.model.copy_map(other)
            self.redraw()
            self.show(None)
            self.status.set(f"Copied from {src['title']}. Save to keep it.")
        ttk.Button(win, text="Copy", command=go).pack(padx=12, pady=10, anchor="e")

    def reset_map(self, kind, value):
        if not messagebox.askyesno(APP_TITLE, "Are you sure you wish to reset this map to its default?"):
            return
        if kind == "mod":
            project.delete_project(self.edit_folder(value))
            self.dirty = False
            self.open_mod_map(value)
        else:
            folder = Path(value)
            data = read_json(folder / "project.json")
            for k in ("starts", "planets", "new_planets", "eras"):
                data[k] = {}
            write_json(folder / "project.json", data)
            self.dirty = False
            self.open_project(value)
        self.install(quiet=True)
        self.status.set("Map reset to its default.")

    def delete_map(self, value):
        if not messagebox.askyesno(APP_TITLE, "Are you sure you wish to permanently delete this map?"):
            return
        project.delete_project(Path(value))
        if self.model and str(self.model.folder) == value:
            self.dirty = False
            self.open_mod_map(self.game.maps[0]["key"])
        self.install(quiet=True)
        self.status.set("Map deleted.")

    # --- start dates ---
    def build_dates(self):
        for c in self.date_frame.winfo_children():
            c.destroy()
        m = self.model
        if not self.game.tr_menu:
            return
        if m.single:
            year = m.data.get("year")
            text = f"{year:g} ABY" if year else (m.info.get("date") or f"{m.info.get('year', 0):g} ABY")
            ttk.Label(self.date_frame, text=f"Start: {text}").pack(side="left")
            return
        self.date_button = ttk.Button(self.date_frame, text=f"Start date: {self.game.date_label(self.era)}  ▾",
                                      width=22, command=self.date_popup)
        self.date_button.pack(side="left")

    def date_popup(self):
        """Every start date: tick = offered in the game; click a date to see it; right click: Copy from date."""
        m = self.model
        win = tk.Toplevel(self.root)
        win.title("Start dates")
        set_icon(win)
        win.transient(self.root)
        win.resizable(False, False)
        x, y = self.date_button.winfo_rootx(), self.date_button.winfo_rooty() + self.date_button.winfo_height()
        win.geometry(f"+{x}+{y}")
        ttk.Label(win, text="Tick: offered in the game. Click a date to see it.\nRight click a date: Copy from date.",
                  foreground="#555").pack(padx=10, pady=(8, 4), anchor="w")
        for era in m.era_list():
            row = ttk.Frame(win)
            row.pack(fill="x", padx=10, pady=1)
            var = tk.BooleanVar(value=m.ticked(era))
            ttk.Checkbutton(row, variable=var, command=lambda e=era, v=var: self.tick_date(e, v, win)).pack(side="left")
            content = m.has_content(era)
            label = tk.Label(row, text=self.game.date_label(era) + ("" if content else "   (no content in the mod)"),
                             cursor="hand2", anchor="w", width=30,
                             font=("Segoe UI", 9, "bold underline" if era == self.era else "normal"),
                             foreground="#1a5fb4" if era == self.era else ("#333" if content else "#999"))
            label.pack(side="left")
            label.bind("<Button-1>", lambda e, n=era: (win.destroy(), self.view_era(n)))
            label.bind("<Button-3>", lambda e, n=era: self.date_context(e, n, win))
        ttk.Label(win, text="").pack()
        win.bind("<Escape>", lambda e: win.destroy())

    def tick_date(self, era, var, win):
        m = self.model
        on = var.get()
        if not on and m.ticked(era) and len(m.ticked_eras()) <= 1:
            var.set(True)
            messagebox.showinfo(APP_TITLE, "A map needs at least one start date.", parent=win)
            return
        if on and not m.has_content(era):
            if not messagebox.askyesno(APP_TITLE, f"{self.game.mod['name']} has no content for "
                                       f"{self.game.date_label(era)} yet: a campaign there may lack factions or heroes, "
                                       "or fail to start.\n\nOffer it anyway?", icon="warning", parent=win):
                var.set(False)
                return
        self.remember()
        m.data["eras"][str(era)] = on
        m.changed()
        self.status.set(f"{self.game.date_label(era)}: " + ("offered in the game." if on else "not offered in the game."))

    def date_context(self, e, era, win):
        menu = tk.Menu(win, tearoff=False)
        menu.add_command(label="Copy from date", state="disabled" if era == self.era else "normal",
                         command=lambda: (win.destroy(), self.copy_from_date(era)))
        menu.tk_popup(e.x_root, e.y_root)

    def copy_from_date(self, source):
        target = self.era
        if not messagebox.askyesno(APP_TITLE, f"Copy every world, lane and owner of {self.game.date_label(source)} into "
                                   f"{self.game.date_label(target)}? {self.game.date_label(target)}'s own are replaced."):
            return
        self.remember()
        self.model.copy_date(source, target)
        self.redraw()
        self.show(self.selected if self.selected in self.model.worlds(target) else None)
        self.status.set(f"{self.game.date_label(target)} is now a copy of {self.game.date_label(source)}.")

    def view_era(self, n):
        self.era = n
        self.lane_from = None
        self.build_dates()
        self.redraw()
        self.show(self.selected if self.selected and self.pos(self.selected) else None)

    # --- saving and installing ---
    def remember(self):
        self.undo.append(self.model.snapshot())
        self.undo = self.undo[-200:]
        self.dirty = True

    def do_undo(self):
        if not self.undo:
            return
        self.model.restore(self.undo.pop())
        self.dirty = True
        self.build_dates()
        self.redraw()
        self.show(self.selected if self.selected and self.pos(self.selected) else None)

    def install_folder_name(self):
        return f"GalaxyMaps_{project.safe_name(self.game.mod['name'])}"

    def install(self, quiet=False):
        """Every map of this game or mod into the game's Mods folder."""
        if not self.game.mods_dir:
            return None
        models = []
        for folder, data in self.projects():
            base = data["template"] if data["kind"] == "new" else data["map"]
            if not self.game.map_info(base):
                continue
            if data["kind"] == "new" and not data.get("slot"):
                data["slot"] = self.free_slot(data["category"])
                write_json(folder / "project.json", data)
                if not data["slot"]:
                    continue
            if self.model and Path(folder) == self.model.folder:
                models.append(self.model)
            else:
                models.append(project.Model(self.game, folder, data))
        target = self.game.mods_dir / self.install_folder_name()
        if not models:
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            return None
        try:
            export.write_maps(self.game, models, target, installed=True)
        except PermissionError:
            if not quiet:
                messagebox.showwarning(APP_TITLE, "Your maps could not be installed: close the game first, then Save.")
            return None
        return models

    def save(self):
        if not self.model:
            return
        if self.model.is_new and not self.model.data.get("slot"):
            self.model.data["slot"] = self.free_slot(self.model.data["category"])
        self.model.save()
        self.dirty = False
        self.root.config(cursor="watch")
        self.root.update()
        try:
            installed = self.install()
        finally:
            self.root.config(cursor="")
        if installed is not None:
            self.status.set(f"Saved and installed into the game (Mods\\{self.install_folder_name()}). To play your "
                            f"maps, set the game's launch options to:  {self.launch_options()}  and start a NEW "
                            "campaign.")
        else:
            self.status.set(f"Saved ({self.model.folder}).")

    def launch_options(self):
        """The launch options that load the installed maps (with the mod and the submods they need)."""
        models = [project.Model(self.game, f, d) for f, d in self.projects()
                  if self.game.map_info(d["template"] if d["kind"] == "new" else d["map"])]
        args = export.launch_line(self.game, models, self.install_folder_name())
        if self.game.mod["kind"] == "workshop" and f"STEAMMOD={self.game.mod_id}" not in args:
            args += f" STEAMMOD={self.game.mod_id}"
        return args

    def confirm_unsaved(self):
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel(APP_TITLE, "Save the changes to this map first?")
        if answer is None:
            return False
        if answer:
            self.save()
        else:
            self.dirty = False
        return True

    def on_close(self):
        if self.confirm_unsaved():
            self.close_windows()
            self.root.destroy()

    # --- drawing ---
    def pos(self, world):
        p = self.model.planet(world)
        if p:
            return p["pos"]
        imp = self.model.imported(world)
        if imp:
            return imp[2]["pos"]
        other = self.game.planets(self.game.all_layer()).get(world)
        return other["pos"] if other else None

    def to_screen(self, x, y):
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        sy = (y - self.cy) * self.scale
        return w / 2 + (x - self.cx) * self.scale, h / 2 + (sy if self.flip.get() else -sy)

    def to_world(self, sx, sy):
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        dy = (sy - h / 2) / self.scale
        return self.cx + (sx - w / 2) / self.scale, self.cy + (dy if self.flip.get() else -dy)

    def color(self, faction):
        f = (faction or "").upper()
        if f in self.game.colors:
            return self.game.colors[f]
        if f in FALLBACK_COLORS:
            return FALLBACK_COLORS[f]
        h = sum(ord(c) * (i + 7) for i, c in enumerate(f))
        return "#%02x%02x%02x" % (80 + h % 150, 80 + (h * 7) % 150, 80 + (h * 13) % 150)

    def excluded_worlds(self):
        """Worlds not on the map at this start that could be put on it (submods' worlds included)."""
        on = set(self.model.worlds(self.era))
        out = [w for w in self.model.pool() if w not in on]
        have = set(out)
        for w, p in self.game.planets(self.game.all_layer()).items():
            if w not in on and w not in have and w not in self.model.planets and self.game.is_world(w, p):
                out.append(w)
        have = set(out)
        out += [w for w in self.model.imported_names() if w not in on and w not in have]
        return out

    def year(self):
        m = self.model
        if m.single:
            return m.data.get("year") or m.info.get("year") or 0
        d = self.game.date(self.era)
        return d["year"] if d else 0

    def spawns(self):
        year = self.year()
        on = set(self.model.worlds(self.era))
        out, self.homes = {}, {}
        for w in self.game.warlords:
            if (w["start"] is not None and year < w["start"]) or (w["last"] is not None and year > w["last"]):
                continue
            planets = [p for p in self.game.warlord_planets(w, year) if p in on and p not in out]
            if not planets:
                continue
            takers = {"WARLORDS"} | set(w["overrides"])
            flips = [p for p in planets if self.model.owner(self.era, p).upper() in takers]
            for p in planets:
                out[p] = (w, "spawns" if p in flips else "held")
            if flips:
                self.homes[flips[0]] = w
        return out

    def radius(self):
        return max(3, min(9, 6 * self.scale))

    def redraw(self):
        c = self.canvas
        c.delete("all")
        self.world_items, self.lane_items = {}, {}
        if not self.model:
            return
        era = self.era
        worlds = self.model.worlds(era)
        r = self.radius()
        names = self.show_names.get()
        owners = {w: self.model.owner(era, w) for w in worlds}
        for pair in self.model.lanes(era):
            a, b = tuple(pair)
            pa, pb = self.pos(a), self.pos(b)
            if not pa or not pb:
                continue
            x1, y1 = self.to_screen(*pa[:2])
            x2, y2 = self.to_screen(*pb[:2])
            same = owners[a].upper() == owners[b].upper()
            self.lane_items[pair] = c.create_line(x1, y1, x2, y2, width=2 if same else 1, tags=("map",),
                                                  fill=self.color(owners[a]) if same else "#3c4458")
        if self.show_excluded.get():
            for key in self.excluded_worlds():
                p = self.pos(key)
                if not p:
                    continue
                x, y = self.to_screen(*p[:2])
                color = "#777" if self.model.planet(key) else ("#e0a040" if self.model.imported(key) else "#b07ad8")
                c.create_oval(x - r, y - r, x + r, y + r, outline=color, dash=(2, 2), tags=("map",))
                if names and self.scale > 0.6:
                    c.create_text(x + r + 3, y, text=self.world_label(key), fill=color, anchor="w",
                                  font=("Segoe UI", 8), tags=("map",))
        self.homes = {}
        spawn = self.spawns() if self.show_spawns.get() else {}
        for key, (lord, state) in spawn.items():
            x, y = self.to_screen(*self.pos(key)[:2])
            g = r + 3
            if state == "spawns":
                c.create_oval(x - g, y - g, x + g, y + g, outline="#ffd24a", width=3, tags=("map",))
            else:
                c.create_oval(x - g, y - g, x + g, y + g, outline="#8a8a8a", width=1, dash=(2, 3), tags=("map",))
            if key in self.homes:
                k = g + 2
                c.create_polygon(x - 5, y - k - 1, x - 5, y - k - 8, x - 2.5, y - k - 4, x, y - k - 9, x + 2.5, y - k - 4,
                                 x + 5, y - k - 8, x + 5, y - k - 1, fill="#ffd24a", outline="#7a5a00", tags=("map",))
            if names and self.scale > 0.45:
                c.create_text(x, y + g + 7, text=lord["name"], fill="#ffd24a" if state == "spawns" else "#9a9a9a",
                              font=("Segoe UI", 7, "italic"), tags=("map",))
        incomplete = set(self.model.incomplete())
        for key in worlds:
            p = self.pos(key)
            if not p:
                continue
            x, y = self.to_screen(*p[:2])
            planet = self.model.planet(key)
            outline = "#ffffff" if planet.get("new") else "#202020"
            ids = [c.create_oval(x - r, y - r, x + r, y + r, fill=self.color(owners[key]), outline=outline,
                                 width=2 if key == self.selected else 1, tags=("map",))]
            if key in incomplete:
                k = r + 3
                ids.append(c.create_line(x - k, y - k, x + k, y + k, fill="#ff3030", width=3, tags=("map",)))
                ids.append(c.create_line(x - k, y + k, x + k, y - k, fill="#ff3030", width=3, tags=("map",)))
            if key == self.selected:
                ids.append(c.create_oval(x - r - 5, y - r - 5, x + r + 5, y + r + 5, outline="#ffff66", width=2,
                                         tags=("map",)))
            if key == self.lane_from:
                ids.append(c.create_oval(x - r - 4, y - r - 4, x + r + 4, y + r + 4, outline="#66ffff", width=2,
                                         tags=("map",)))
            if names and self.scale > 0.45:
                ids.append(c.create_text(x + r + 3, y, text=self.world_label(key), fill="#cfd6e6", anchor="w",
                                         font=("Segoe UI", 8), tags=("map",)))
            self.world_items[key] = ids
        self.draw_legend(owners)
        self.update_status(len(worlds), len(incomplete))

    def world_label(self, key):
        if self.model.planet(key):
            return self.model.display_name(key)
        imp = self.model.imported(key)
        if imp:
            return imp[2].get("display") or key.title()
        other = self.game.planets(self.game.all_layer()).get(key)
        return self.game.planet_name(other) if other else key.title()

    def update_status(self, n, incomplete):
        text = f"{self.model.title}: {n} worlds, {len(self.model.lanes(self.era))} lanes"
        if self.era:
            text += f" ({self.game.date_label(self.era)})"
        text += "."
        warn = False
        if n > SAFE_WORLDS:
            text += f"  Over {SAFE_WORLDS} worlds: more than any map known to run well without engine fixes; the game " \
                    "may slow down badly or crash."
            warn = True
        if incomplete:
            text += f"  {incomplete} incomplete planet(s) (red X)."
            warn = True
        if self.dirty:
            text += "  Unsaved changes."
        self.status.set(text)
        self.status_label.configure(foreground="#b04000" if warn else "#000")

    def draw_legend(self, owners):
        c = self.canvas
        count = {}
        for f in owners.values():
            count[f.upper()] = count.get(f.upper(), 0) + 1
        y = 10
        for f, n in sorted(count.items(), key=lambda kv: -kv[1]):
            c.create_rectangle(10, y, 22, y + 12, fill=self.color(f), outline="#000", tags=("legend",))
            c.create_text(28, y + 6, text=f"{self.game.faction_label(f)} ({n})", anchor="w", fill="#cfd6e6",
                          font=("Segoe UI", 8), tags=("legend",))
            y += 17
        notes = ["White ring: a new world.", "Red X: incomplete (no battle map or model yet)."]
        if self.show_excluded.get():
            notes.append("Dashed: excluded from this map (purple: from a submod; orange: imported from a mod).")
        if self.show_spawns.get():
            notes += ["Proteus spawns: gold = taken by the warlord", "if chosen (crown: its capital and heroes);",
                      "grey dashed = its world, held by another power."]
        y += 4
        for line in notes:
            c.create_text(10, y + 6, text=line, anchor="w", fill="#8890a0", font=("Segoe UI", 8), tags=("legend",))
            y += 15

    # --- mouse ---
    def hit(self, sx, sy, include_excluded=False):
        best, bd = None, 14 ** 2
        pools = [self.model.worlds(self.era)] + ([self.excluded_worlds()] if include_excluded else [])
        for pool in pools:
            for key in pool:
                p = self.pos(key)
                if not p:
                    continue
                x, y = self.to_screen(*p[:2])
                d = (x - sx) ** 2 + (y - sy) ** 2
                if d < bd:
                    best, bd = key, d
        return best

    def on_wheel(self, e):
        wx, wy = self.to_world(e.x, e.y)
        old = self.scale
        self.scale = max(0.05, min(self.scale * (1.2 if e.delta > 0 else 1 / 1.2), 20))
        nx, ny = self.to_world(e.x, e.y)
        self.cx += wx - nx
        self.cy += wy - ny
        f = self.scale / old
        self.canvas.scale("map", e.x, e.y, f, f)
        if getattr(self, "zoom_job", None):
            self.root.after_cancel(self.zoom_job)
        self.zoom_job = self.root.after(140, self.redraw)

    def on_pan_start(self, e):
        self.pan = (e.x, e.y)

    def on_pan(self, e):
        dx, dy = e.x - self.pan[0], e.y - self.pan[1]
        self.pan = (e.x, e.y)
        self.cx -= dx / self.scale
        self.cy += (dy if not self.flip.get() else -dy) / self.scale
        self.canvas.move("map", dx, dy)

    def on_press(self, e):
        tool = self.tool.get()
        if tool == "create":
            x, y = self.to_world(e.x, e.y)
            self.create_planet(x, y)
            return
        key = self.hit(e.x, e.y, include_excluded=self.show_excluded.get() and tool == "select")
        on_map = key in self.model.worlds(self.era)
        if tool == "select":
            self.show(key)
            self.drag = (key, False) if on_map and self.move_on.get() else None
        elif tool == "paint" and on_map:
            self.set_owner(key, self.paint.get())
        elif tool == "lanes" and on_map:
            if self.lane_from is None:
                self.lane_from = key
                self.redraw()
            elif key == self.lane_from:
                self.lane_from = None
                self.redraw()
            else:
                self.remember()
                added = self.model.toggle_lane(self.era, self.lane_from, key)
                names = f"{self.model.display_name(self.lane_from)} - {self.model.display_name(key)}"
                self.lane_from = None
                self.redraw()
                self.status.set(f"Lane {names} " + ("added." if added else "removed.") +
                                (f" ({self.game.date_label(self.era)})" if self.era else ""))

    def on_motion(self, e):
        if not self.drag:
            return
        key, moved = self.drag
        if not moved:
            self.remember()
            self.drag = (key, True)
        x, y = self.to_world(e.x, e.y)
        p = self.model.planet(key)
        old = self.to_screen(*p["pos"][:2])
        z = p["pos"][2] if len(p["pos"]) > 2 else 0
        self.model.edit_planet(key, pos=[round(x), round(y), z])
        new = self.to_screen(*self.model.planet(key)["pos"][:2])
        for item in self.world_items.get(key, []):
            self.canvas.move(item, new[0] - old[0], new[1] - old[1])
        for pair, item in self.lane_items.items():
            if key in pair:
                a, b = tuple(pair)
                self.canvas.coords(item, *self.to_screen(*self.pos(a)[:2]), *self.to_screen(*self.pos(b)[:2]))

    def on_release(self, e):
        if self.drag and self.drag[1]:
            self.status.set(f"{self.model.display_name(self.drag[0])} moved (on every map while your maps are "
                            "installed).")
            self.show(self.drag[0])
        self.drag = None

    def tool_changed(self):
        self.lane_from = None
        self.canvas.configure(cursor="crosshair" if self.tool.get() == "create" else "")
        self.redraw()

    def move_changed(self):
        if self.move_on.get():
            self.status.set("Move worlds is on: drag a world to move it. A world's position is shared by every map, "
                            "so it moves on all of them while your maps are installed.")
        self.show(self.selected)

    # --- edits ---
    def set_owner(self, key, text):
        if not key or key not in self.model.worlds(self.era) or not text:
            return
        faction = self.faction_of(text)
        if self.model.owner(self.era, key).upper() == faction.upper():
            return
        self.remember()
        self.model.set_owner(self.era, key, faction)
        self.redraw()
        if key == self.selected:
            self.show(key)

    def create_planet(self, x, y):
        name = simpledialog.askstring(APP_TITLE, "Name of the new world:", parent=self.root)
        if not name or not name.strip():
            return
        self.remember()
        key = self.model.create_planet(name.strip(), x, y, self.era)
        self.model.save()
        self.tool.set("select")
        self.tool_changed()
        self.show(key)
        p = self.model.planet(key)
        on = (f" It is on {self.game.date_label(self.era)} only; 'Add to map' on another date puts it there too."
              if self.era else "")
        self.status.set(f"{name} created. Put its battle maps in its folder ({p['land']}, {p['space']}: 'Open "
                        f"folder') and give it a galaxy map model; until then it has a red X.{on}")

    def move_typed(self):
        key = self.selected
        if key not in self.model.worlds(self.era) or not self.move_on.get():
            return
        try:
            x, y = float(self.x_entry.get()), float(self.y_entry.get())
        except ValueError:
            return
        self.remember()
        p = self.model.planet(key)
        self.model.edit_planet(key, pos=[round(x), round(y), p["pos"][2] if len(p["pos"]) > 2 else 0])
        self.redraw()

    def restore_positions(self):
        moved = [w for w, e in self.model.data["planets"].items() if "pos" in e]
        if not moved:
            self.status.set("No world has been moved.")
            return
        if not messagebox.askyesno(APP_TITLE, f"Put the {len(moved)} moved world(s) back where "
                                   f"{self.game.mod['name']} has them? (New worlds stay where you put them.)"):
            return
        self.remember()
        for w in moved:
            self.model.data["planets"][w].pop("pos", None)
            if not self.model.data["planets"][w]:
                self.model.data["planets"].pop(w)
        self.model.changed()
        self.redraw()
        self.show(self.selected)

    def remove_world(self):
        key = self.selected
        if key not in self.model.worlds(self.era):
            return
        self.remember()
        self.model.remove_world(key)
        self.redraw()
        self.show(key)
        self.status.set(f"{self.model.display_name(key)} taken off the map (every start date). 'Add to map' puts it "
                        "back; tick 'Excluded Worlds' to see it.")

    def add_world(self):
        key = self.selected
        if not key or key in self.model.worlds(self.era):
            return
        imp = self.model.imported(key)
        if imp:
            other = self.other_game(imp[0])
            self.remember()
            self.model.take_import(key, other)
            self.model.save()
        new = key in self.model.data["new_planets"]
        if imp:
            pass
        elif not self.model.planet(key):
            sub = self.game.submod_of_world(key)
            if not self.dont_ask_submod:
                d = DependencyDialog(self.root, sub["name"] if sub else "a submod")
                if not d.result:
                    return
                if d.dont_ask:
                    self.dont_ask_submod = True
            self.remember()
            if sub:
                self.model.data["layer"] = sorted(set(self.model.layer) | {sub["id"]})
                self.model.reload_layer()
                self.model.changed()
        else:
            self.remember()
        if new:
            eras = [self.era]                   # (a new world: on the date it is added at)
        else:
            eras = self.model.ticked_eras() if not self.model.single else [0]
            if self.era not in eras:
                eras.append(self.era)
        self.model.add_world(key, eras)
        self.redraw()
        self.show(key)
        where = f"{self.game.date_label(self.era)}" if new and self.era else "every start date offered"
        self.status.set(f"{self.model.display_name(key)} added to the map ({where}; owner: "
                        f"{self.game.faction_label(self.model.owner(self.era, key))}).")

    def delete_world(self):
        key = self.selected
        if not key or not (self.model.planet(key) or self.model.imported(key)):
            return
        if not messagebox.askyesno(APP_TITLE, DELETE_WORLD_TEXT, icon="warning"):
            return
        self.remember()
        name = self.world_label(key)
        self.model.delete_world(key)
        self.model.save()
        self.redraw()
        self.show(None)
        self.status.set(f"{name} deleted from this map.")

    def rename(self):
        key = self.selected
        name = self.name_entry.get().strip()
        if not key or not self.model.planet(key) or not name or name == self.model.display_name(key):
            return
        self.remember()
        self.model.edit_planet(key, display=name)
        self.redraw()
        self.show(key)

    def set_number(self, field):
        key = self.selected
        p = self.model.planet(key) if key else None
        if not p:
            return
        try:
            value = int(float(self.slot_vars[field].get()))
        except ValueError:
            return
        value = max(0, min(value, 5 if field == "station" else 99))
        if value == p.get(field):
            return
        self.remember()
        self.model.edit_planet(key, **{field: value})
        label = {"land_slots": "land build slots", "space_slots": "space build slots",
                 "station": "space station level"}[field]
        self.status.set(f"{self.model.display_name(key)}: {label} {value} (on every map while your maps are "
                        "installed).")

    def set_surface(self):
        key = self.selected
        if not key or not self.model.planet(key):
            return
        self.remember()
        self.model.edit_planet(key, surface=self.surface.get())
        self.redraw()
        self.show(key)

    def set_file(self, field):
        key = self.selected
        p = self.model.planet(key) if key else None
        if not p:
            return
        value = self.files[field].get().strip()
        if value == (p.get(field) or ""):
            return
        self.remember()
        self.model.edit_planet(key, **{field: value})
        self.redraw()
        self.show(key)

    def browse_file(self, field, kind):
        key = self.selected
        if not key or not self.model.planet(key):
            return
        types = [("Battle maps", "*.ted")] if kind == "Maps" else [("Models", "*.alo")]
        chosen = filedialog.askopenfilename(title="Choose a file", filetypes=types + [("All files", "*.*")])
        if not chosen:
            return
        src = Path(chosen)
        dest = self.model.art_folder(kind) / src.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.resolve() != dest.resolve():
            dest.write_bytes(src.read_bytes())
        self.remember()
        self.model.edit_planet(key, **{field: src.name})
        self.model.save()
        self.redraw()
        self.show(key)
        self.status.set(f"{src.name} copied into the map's {kind.lower()} folder; it goes into your mod.")

    def open_folder(self, field, kind):
        key = self.selected
        p = self.model.planet(key) if key else None
        name = (p or {}).get(field) or ""
        folder = self.model.art_folder(kind)
        if name and not (folder / name).exists() and self.game.asset_folder(name):
            folder = self.game.asset_folder(name)
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder))

    def change_picture(self):
        key = self.selected
        stem = self.model.picture_name(key) if key else None
        if not stem:
            messagebox.showinfo(APP_TITLE, "Give the world a battle map first: the game finds a world's picture by "
                                "its battle map's name.")
            return
        if Image is None:
            return
        chosen = filedialog.askopenfilename(title="Choose a picture", filetypes=[
            ("Pictures", "*.png *.jpg *.jpeg *.bmp *.tga *.dds"), ("All files", "*.*")])
        if not chosen:
            return
        try:
            im = Image.open(chosen).convert("RGBA")
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"That picture could not be read:\n{e}")
            return
        side = min(im.size)
        left, top = (im.width - side) // 2, (im.height - side) // 2
        im = im.crop((left, top, left + side, top + side)).resize((512, 512), Image.LANCZOS)
        folder = self.model.art_folder("Textures")
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.glob(stem + ".*"):
            old.unlink()
        im.save(folder / f"{stem}.dds")
        self.remember()
        self.model.edit_planet(key, picture=True)
        self.model.save()
        self.show(key)
        shared = self.sharing(key)
        self.status.set("Picture changed." + (f" It is also the picture of {', '.join(shared[:4])}"
                                               f"{' and others' if len(shared) > 4 else ''} (same battle map)."
                                               if shared else ""))

    def sharing(self, key):
        stem = self.model.picture_name(key)
        return [self.model.display_name(n) for n in self.model.planets
                if n != key and self.model.picture_name(n) == stem]

    def apply_texts(self):
        key = self.selected
        if not key or not self.model.planet(key):
            return
        changed = {}
        for tag, box in self.text_boxes.items():
            value = box.get("1.0", "end").strip().replace("\n", "\\n")
            if value != self.model.text_of(key, tag).strip():
                changed[tag] = value
        if changed:
            self.remember()
            self.model.edit_planet(key, texts=changed)
            self.status.set("Text changes kept. They go into your mod's copy of the game's text file.")

    # --- side panel ---
    def show(self, key):
        self.selected = key
        self.redraw()
        for box in self.text_boxes.values():
            box.configure(state="normal")
            box.delete("1.0", "end")
        self.picture.delete("all")
        self.photo = None
        for box in self.files.values():
            box.set("")
        for var in self.slot_vars.values():
            var.set("")
        self.name_entry.delete(0, "end")
        self.missing_var.set("")
        self.picture_var.set("")
        if key is None:
            self.title_var.set("Click a world.")
            self.flags_var.set("Tools: Select a world to see it; Lanes: click two worlds to add or remove the lane "
                               "between them (click a world again to let go of it); Paint owner: click worlds to give "
                               "them the owner chosen; Create a planet: click an empty spot.\nMouse wheel: zoom; right "
                               "or middle button: drag the view.")
            self.lanes_var.set("")
            self.owner_box.set("")
            return
        p = self.model.planet(key)
        on_map = key in self.model.worlds(self.era)
        imp = None if p else self.model.imported(key)
        if imp:
            self.title_var.set(self.world_label(key) + "  (excluded from this map)")
            self.flags_var.set(f"A world imported from {imp[1]}. 'Add to map' copies it into your map with its battle "
                               "maps, model and picture.")
            self.lanes_var.set("")
            self.remove_btn.configure(state="disabled")
            self.delete_btn.configure(state="normal")
            self.add_btn.configure(state="normal")
            return
        if not p:
            sub = self.game.submod_of_world(key)
            self.title_var.set(self.world_label(key) + "  (excluded from this map)")
            self.flags_var.set(f"A world of the submod \"{sub['name'] if sub else '?'}\". 'Add to map' puts it on this "
                               "map (the map then needs that submod).")
            self.lanes_var.set("")
            self.remove_btn.configure(state="disabled")
            self.delete_btn.configure(state="disabled")
            self.add_btn.configure(state="normal")
            return
        self.title_var.set(self.model.display_name(key) + ("" if on_map else "  (excluded from this map)"))
        kind = "a new world" if p["new"] else f"a world of {self.game.mod['name']}"
        self.flags_var.set(f"{p['name']}: {kind}.")
        missing = self.model.missing(key)
        if missing:
            self.missing_var.set("Incomplete: no " + ", no ".join(missing) + " yet. Exporting it like this can make "
                                 "the game crash or show errors.")
        self.name_entry.insert(0, self.model.display_name(key))
        self.owner_label.configure(text=f"Owner ({self.game.date_label(self.era)})" if self.era else "Owner")
        self.owner_box.set(self.faction_text(self.model.owner(self.era, key)) if on_map else "")
        pos = p["pos"]
        self.x_entry.delete(0, "end")
        self.x_entry.insert(0, f"{pos[0]:g}")
        self.y_entry.delete(0, "end")
        self.y_entry.insert(0, f"{pos[1]:g}")
        self.move_button.configure(state="normal" if self.move_on.get() and on_map else "disabled")
        self.remove_btn.configure(state="normal" if on_map else "disabled")
        self.add_btn.configure(state="disabled" if on_map else "normal")
        self.delete_btn.configure(state="normal")
        near = sorted(self.model.display_name(o) for pr in self.model.lanes(self.era) if key in pr for o in pr if o != key)
        self.lanes_var.set(("Lanes to: " + (", ".join(near) or "none")) if on_map else "")
        for field, var in self.slot_vars.items():
            var.set(str(p.get(field, 0)))
        self.surface.set(bool(p.get("surface")))
        maps = self.ted_names()
        for field in ("land", "space", "model"):
            box = self.files[field]
            box["values"] = maps if field != "model" else self.model_names()
            box.set(p.get(field) or "")
        for tag, box in self.text_boxes.items():
            box.insert("1.0", self.model.text_of(key, tag).replace("\\n", "\n"))
        self.show_picture(key)

    def ted_names(self):
        if not hasattr(self, "_teds"):
            self._teds = [n.title() for n in self.game.asset_names(".TED")]
        return self._teds

    def model_names(self):
        if not hasattr(self, "_models"):
            self._models = sorted({p["model"] for p in self.game.planets(self.game.all_layer()).values() if p["model"]},
                                  key=str.lower)
        return self._models

    def show_picture(self, key):
        stem = self.model.picture_name(key)
        if not stem:
            self.picture_var.set("No picture: the world has no battle map yet.")
            return
        data, where = None, ""
        folder = self.model.art_folder("Textures")
        for ext in (".dds", ".tga", ".DDS", ".TGA"):
            f = folder / (stem + ext)
            if f.exists():
                data, where = f.read_bytes(), "your picture"
                break
        if data is None:
            for ext in (".DDS", ".TGA"):
                data = self.game.asset_bytes(stem + ext)
                if data:
                    where = "the game's picture"
                    break
        if not data:
            self.picture_var.set(f"No picture yet ({stem}). 'Change picture...' makes one.")
            return
        self.picture_var.set(f"{where} ({stem})")
        if Image is None:
            return
        try:
            im = Image.open(io.BytesIO(data)).convert("RGB")
            im.thumbnail((220, 124))
            self.photo = ImageTk.PhotoImage(im)
            self.picture.create_image(110, 62, image=self.photo)
        except Exception:
            self.picture_var.set(f"{where} ({stem}): can't be shown here.")

    def find_world(self):
        text = self.find.get().strip().upper().replace(" ", "_")
        if not text:
            return
        pools = [self.model.worlds(self.era), self.excluded_worlds()]
        for i, pool in enumerate(pools):
            for key in pool:
                if text in key or text in self.world_label(key).upper().replace(" ", "_"):
                    if i and not self.show_excluded.get():
                        self.show_excluded.set(True)
                    self.cx, self.cy = self.pos(key)[:2]
                    self.scale = max(self.scale, 1.2)
                    self.show(key)
                    return
        self.status.set(f"No world named {self.find.get()}.")

    def next_incomplete(self):
        keys = self.model.incomplete()
        if not keys:
            self.status.set("No incomplete planets: every new or changed world has its battle maps and model.")
            return
        self.incomplete_index = self.incomplete_index % len(keys)
        key = keys[self.incomplete_index]
        self.incomplete_index += 1
        if key not in self.model.worlds(self.era):
            for era in self.model.ticked_eras():
                if key in self.model.worlds(era):
                    self.view_era(era)
                    break
        self.cx, self.cy = self.pos(key)[:2]
        self.scale = max(self.scale, 1.2)
        self.show(key)
        self.status.set(f"Incomplete planet {self.incomplete_index} of {len(keys)}: {self.model.display_name(key)} "
                        f"(missing: {', '.join(self.model.missing(key))}).")

    # --- importing worlds from another mod ---
    def other_game(self, mod_id):
        """Another game or mod, read once (for imported worlds' art); None if it is no longer installed."""
        cache = self.__dict__.setdefault("_other_games", {})
        if mod_id not in cache:
            mod = next((m for m in getattr(self.game, "all_mods", []) if m["id"] == mod_id), None)
            try:
                cache[mod_id] = gamedata.Game(self.game.game_dir, mod) if mod else None
            except Exception:
                cache[mod_id] = None
        return cache[mod_id]

    def import_dialog(self):
        mods = [m for m in getattr(self.game, "all_mods", []) if m["id"] != self.game.mod_id]
        if not mods:
            messagebox.showinfo(APP_TITLE, "No other game or mod is installed.")
            return
        win = tk.Toplevel(self.root)
        win.title("Import Excluded planets from mod")
        set_icon(win)
        win.transient(self.root)
        win.resizable(False, False)
        ttk.Label(win, wraplength=420, text=("Bring the worlds of another game or mod into this map's Excluded Worlds "
                  f"(the ones {self.game.mod['name']} doesn't have). Add them to the map like any other world.")).pack(
            padx=12, pady=(12, 6), anchor="w")
        box = ttk.Combobox(win, state="readonly", width=56, values=[m["name"] for m in mods])
        box.pack(padx=12)
        box.current(0)

        def go():
            mod = mods[box.current()]
            if not messagebox.askyesno(APP_TITLE, IMPORT_TEXT, icon="warning", parent=win):
                return
            win.destroy()
            self.root.config(cursor="watch")
            self.root.update()
            try:
                other = self.other_game(mod["id"])
                if other is None:
                    messagebox.showwarning(APP_TITLE, f"{mod['name']} could not be read.")
                    return
                self.remember()
                n = self.model.import_planets(other)
                self.model.save()
            finally:
                self.root.config(cursor="")
            self.show_excluded.set(True)
            self.redraw()
            self.status.set(f"{n} world(s) of {mod['name']} imported into Excluded Worlds (orange). 'Add to map' puts "
                            "one on the map with its files.")
        ttk.Button(win, text="Import...", command=go).pack(padx=12, pady=10, anchor="e")

    # --- menu buttons ---
    def slots_window(self):
        if self.dirty:
            self.save()
        win = tk.Toplevel(self.root)
        win.title("Menu buttons")
        set_icon(win)
        win.geometry("720x620")
        ttk.Label(win, wraplength=680, justify="left", text=(
            "The galactic conquest menu has 32 map buttons in each list. Drag a map onto another button of its list to "
            "move it there (a map already there swaps with it), or double click a map to choose its button. Maps of "
            "other uploads installed on this PC can't be moved: choose buttons they don't use.")).pack(
            anchor="w", padx=10, pady=8)
        frame = ttk.Frame(win)
        frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        tree = ttk.Treeview(frame, columns=("map", "who"), show="tree headings", selectmode="browse")
        bar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=bar.set)
        tree.heading("#0", text="Button")
        tree.heading("map", text="Map")
        tree.heading("who", text="")
        tree.column("#0", width=150)
        tree.column("map", width=340)
        tree.column("who", width=170)
        tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        state = {"layout": {}, "rows": {}}

        def refresh():
            tree.delete(*tree.get_children())
            layout = export.button_layout(self.game, self.projects())
            state["layout"], state["rows"] = layout, {}
            for cat, _, prefix in gamedata.CATEGORIES:
                parent = tree.insert("", "end", text=cat, open=True)
                for i in range(1, gamedata.SLOTS_PER_CATEGORY + 1):
                    b = f"{prefix}_map_{i:02d}"
                    entry = layout.get(b)
                    who = {"mod": self.game.mod["name"], "yours": "your map", "other": "another upload"}.get(
                        entry[0], "") if entry else ""
                    iid = tree.insert(parent, "end", text=b, values=(entry[2] if entry else "(free)", who))
                    state["rows"][iid] = b
        refresh()
        drag = {"from": None}

        def press(e):
            drag["from"] = state["rows"].get(tree.identify_row(e.y))

        def release(e):
            a, b = drag["from"], state["rows"].get(tree.identify_row(e.y))
            drag["from"] = None
            if a and b and a != b and a in state["layout"]:
                if self.move_button_map(a, b, state["layout"], win):
                    refresh()

        def double(e):
            a = state["rows"].get(tree.identify_row(e.y))
            if not a or a not in state["layout"]:
                return
            choices = export.tr_buttons(export.category_of_button(a))
            dlg = tk.Toplevel(win)
            dlg.title("Choose a button")
            set_icon(dlg)
            dlg.transient(win)
            ttk.Label(dlg, text=f"Move \"{state['layout'][a][2]}\" to:").pack(padx=12, pady=(12, 4), anchor="w")
            labels = [f"{b}  -  {state['layout'][b][2] if b in state['layout'] else 'free'}" for b in choices]
            box = ttk.Combobox(dlg, state="readonly", width=58, values=labels)
            box.pack(padx=12)
            box.current(choices.index(a) if a in choices else 0)

            def ok():
                b = choices[box.current()]
                dlg.destroy()
                if b != a and self.move_button_map(a, b, state["layout"], win):
                    refresh()
            ttk.Button(dlg, text="Move", command=ok).pack(padx=12, pady=10, anchor="e")
        tree.bind("<ButtonPress-1>", press)
        tree.bind("<ButtonRelease-1>", release)
        tree.bind("<Double-1>", double)

    def move_button_map(self, a, b, layout, parent):
        """Moves the map on button a to button b (swapping with b's map). True when done."""
        if export.category_of_button(a) != export.category_of_button(b):
            messagebox.showinfo(APP_TITLE, "A map can only move to a button of its own list.", parent=parent)
            return False
        ea, eb = layout.get(a), layout.get(b)
        for e in (ea, eb):
            if e and not e[3]:
                messagebox.showinfo(APP_TITLE, f"\"{e[2]}\" belongs to another upload and can't be moved.",
                                    parent=parent)
                return False
        if any(e and e[0] == "mod" for e in (ea, eb)):
            if not messagebox.askyesno(APP_TITLE, f"This moves one of {self.game.mod['name']}'s own maps to another "
                                       "button. Everyone who installs your maps gets the move.\n\nMove it?",
                                       icon="warning", parent=parent):
                return False
        self.assign_button(ea, b)
        if eb:
            self.assign_button(eb, a)
        if self.model and (self.model.folder / "project.json").exists():
            data = read_json(self.model.folder / "project.json")
            self.model.data["slot"], self.model.data["button"] = data.get("slot"), data.get("button")
        self.install(quiet=True)
        return True

    def assign_button(self, entry, button):
        kind, value, title, _ = entry
        if kind == "yours":
            f = Path(value) / "project.json"
            data = read_json(f)
            data["slot"] = button
            write_json(f, data)
        elif kind == "mod":
            folder = self.edit_folder(value)
            info = self.game.map_info(value)
            if (folder / "project.json").exists():
                data = read_json(folder / "project.json")
            else:
                data = project.new_project_data(self.game.mod_id, "edit", value, info["category"], info["layer"])
            data["button"] = None if button == info.get("button") else button
            write_json(folder / "project.json", data)

    # --- export ---
    def export_dialog(self):
        if not self.model:
            return
        m = self.model
        incomplete = m.incomplete()
        if incomplete:
            names = ", ".join(m.display_name(k) for k in incomplete[:6]) + (" ..." if len(incomplete) > 6 else "")
            if not messagebox.askyesno(APP_TITLE, f"{len(incomplete)} planet(s) on this map are incomplete ({names}): "
                                       "they lack a battle map or a galaxy map model.\n\nExporting the map in this state "
                                       "can cause crashes or errors in the game. Export anyway?", icon="warning"):
                return
        n = m.world_count()
        if n > SAFE_WORLDS and not messagebox.askyesno(APP_TITLE, f"The map has {n} worlds, more than any map known to "
                                                       f"run well in the unmodified game ({SAFE_WORLDS}). Players may "
                                                       "see long loading, slow turns or crashes. Export anyway?",
                                                       icon="warning"):
            return
        if m.is_new and not m.data.get("slot"):
            m.data["slot"] = self.free_slot(m.data["category"])
            if not m.data["slot"]:
                messagebox.showwarning(APP_TITLE, "Every button of this list is taken: free one in 'Menu buttons...'.")
                return
        win = tk.Toplevel(self.root)
        win.title("Export as mod")
        set_icon(win)
        win.transient(self.root)
        win.resizable(False, False)
        ttk.Label(win, text="Mod folder name").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 2))
        name = ttk.Entry(win, width=40)
        name.insert(0, m.data.get("export_name") or project.safe_name(m.title))
        name.grid(row=1, column=0, columnspan=3, sticky="w", padx=10)
        ttk.Label(win, text="Put it in").grid(row=2, column=0, sticky="w", padx=10, pady=(8, 2))
        where = ttk.Entry(win, width=52)
        where.insert(0, m.data.get("export_folder") or self.settings.get("export_folder")
                     or str(project.HOME / "Exports"))
        where.grid(row=3, column=0, columnspan=2, sticky="w", padx=10)

        def browse():
            d = filedialog.askdirectory(parent=win)
            if d:
                where.delete(0, "end")
                where.insert(0, d)
        ttk.Button(win, text="Browse...", command=browse).grid(row=3, column=2, padx=(0, 10))
        ttk.Label(win, wraplength=460, justify="left", foreground="#555", text=(
            "The folder is a complete mod, ready to upload to the Steam Workshop as it is: its modinfo.json names "
            "the mods it needs. To play it yourself, use Save.")).grid(row=4, column=0, columnspan=3,
                                                                               sticky="w", padx=10, pady=8)

        def go():
            folder_name = project.safe_name(name.get().strip())
            out = Path(where.get().strip() or str(project.HOME / "Exports")) / folder_name
            if out.exists() and any(out.iterdir()) and not (out / "Data").exists():
                messagebox.showwarning(APP_TITLE, f"{out} already holds other files: choose another name or folder.",
                                       parent=win)
                return
            m.data["export_name"], m.data["export_folder"] = folder_name, str(out.parent)
            self.settings["export_folder"] = str(out.parent)
            project.save_settings(self.settings)
            self.save()
            win.config(cursor="watch")
            win.update()
            try:
                count, notes = export.export_mod(self.game, m, out)
            except Exception as e:
                win.config(cursor="")
                messagebox.showerror(APP_TITLE, f"The export failed:\n\n{e}", parent=win)
                return
            win.destroy()
            text = f"Exported to {out} ({count} files)."
            if notes:
                text += "\n\n" + "\n".join(notes[:12]) + ("\n..." if len(notes) > 12 else "")
            if messagebox.askyesno(APP_TITLE, text + "\n\nOpen the folder?"):
                os.startfile(str(out))
        ttk.Button(win, text="Export", command=go).grid(row=5, column=2, sticky="e", padx=10, pady=(0, 10))


def already_running():
    """True when another copy of the editor runs (it is brought to the front instead)."""
    try:
        kernel = ctypes.windll.kernel32
        kernel.CreateMutexW(None, False, "GalaxyMapEditor_SingleInstance")
        if kernel.GetLastError() != 183:            # ERROR_ALREADY_EXISTS
            return False
        user = ctypes.windll.user32
        found = []

        def each(hwnd, _):
            buf = ctypes.create_unicode_buffer(256)
            user.GetWindowTextW(hwnd, buf, 256)
            if buf.value.startswith(APP_TITLE) and user.IsWindowVisible(hwnd):
                found.append(hwnd)
            return True
        proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(each)
        user.EnumWindows(proc, 0)
        for hwnd in found[:1]:
            user.ShowWindow(hwnd, 9)                  # SW_RESTORE
            user.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def report_error(exc, value, tb):
    """An error the editor didn't expect: shown, and written to error.log in its folder of Documents."""
    import traceback
    text = "".join(traceback.format_exception(exc, value, tb))
    try:
        project.HOME.mkdir(parents=True, exist_ok=True)
        with open(project.HOME / "error.log", "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError:
        pass
    messagebox.showerror(APP_TITLE, f"Something went wrong:\n\n{value}\n\nThe details are in "
                         f"{project.HOME / 'error.log'}.")


def main():
    if already_running():
        return
    root = tk.Tk()
    root.report_callback_exception = report_error
    set_icon(root)
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    settings = project.load_settings()
    if not isinstance(settings.get("last_map"), dict):      # (an older version kept a single map here)
        settings["last_map"] = {}

    def opened(game):
        try:
            Editor(root, game, settings, choose)
        except Exception:
            report_error(*sys.exc_info())

    def choose():
        root.title(APP_TITLE)
        root.geometry("")
        Chooser(root, settings, opened)
    choose()
    root.mainloop()


if __name__ == "__main__":
    main()
