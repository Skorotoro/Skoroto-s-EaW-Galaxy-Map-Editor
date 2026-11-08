"""A map being edited: one of the mod's maps with changes, or a new map started from one of them.

A project is a folder: project.json and Data\\Art\\{Maps,Models,Textures} (the art its worlds use). Each start of the
map is kept whole once it is changed (worlds, lanes, owners); starts never changed follow the mod's own files.
"""
import copy
import json
import re
import shutil
from pathlib import Path

import gamedata

TEXT_TAGS = ("History", "Population", "Terrain", "Weather", "Wildlife", "Advantage", "Tactical")
NEW_OWNER = "Independent_Forces"
VERSION = 2


def documents():
    try:
        import ctypes.wintypes
        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)
        if buf.value:
            return Path(buf.value)
    except Exception:
        pass
    return Path.home() / "Documents"


HOME = documents() / "Galaxy Map Editor"
SETTINGS = HOME / "settings.json"


def projects_dir(mod_id):
    return HOME / "Projects" / safe_name(mod_id)


def load_settings():
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(settings):
    HOME.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(settings, indent=1), encoding="utf-8")


def safe_name(text):
    s = re.sub(r"[^A-Za-z0-9]+", "_", str(text)).strip("_")
    return s or "Map"


def new_project_data(mod_id, kind, key, category, layer, template=None, blank=False, title="", description="",
                     year=None):
    return {"version": VERSION, "mod": mod_id, "kind": kind, "map": key, "category": category, "layer": list(layer),
            "template": template, "blank": blank, "title": title, "description": description, "slot": None,
            "button": None, "year": year, "eras": {}, "starts": {}, "planets": {}, "new_planets": {}, "imports": {}}


def list_projects(mod_id):
    out = []
    d = projects_dir(mod_id)
    if d.exists():
        for p in sorted(d.iterdir()):
            f = p / "project.json"
            if f.exists():
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    if data.get("version") == VERSION:
                        out.append((p, data))
                except (OSError, ValueError):
                    pass
    return out


def delete_project(folder):
    shutil.rmtree(folder, ignore_errors=True)


class Campaign:
    """One start of a map as the mod's file has it: the first campaign of its set (every faction's copy shares the
    worlds, lanes and starting forces)."""

    def __init__(self, rel, text, prefix=None, cset=None):
        self.rel, self.text = rel, text or ""
        self.prefix = prefix.upper() if prefix else None
        self.cset = cset
        blocks = list(re.finditer(r'<Campaign\s+Name\s*=\s*"([^"]+)"\s*>(.*?)</Campaign>', self.text, re.S))
        if cset:
            self.blocks = [m for m in blocks if re.search(r"<Campaign_Set>\s*" + re.escape(cset) + r"\s*<", m.group(2))]
        else:
            self.blocks = [m for m in blocks if m.group(1).upper().startswith(self.prefix)]
        body = self.blocks[0].group(2) if self.blocks else ""
        self.locations = self.names(body, "Locations")
        self.routes = self.names(body, "Trade_Routes")
        forces = [tuple(x.strip() for x in m.split(",")) for m in
                  re.findall(r"<Starting_Forces>\s*([^<]*?)\s*</Starting_Forces>", body)]
        self.forces = [f for f in forces if len(f) >= 3]
        self.factions = [m.strip() for m in re.findall(r"<AI_Player_Control>\s*([^,<]+),", body)]
        self.owners = {}
        for faction, planet, unit in [f[:3] for f in self.forces]:
            p = planet.upper()
            if unit.upper() == "GENERATE_FORCE" or p not in self.owners:
                self.owners[p] = faction

    @staticmethod
    def names(body, tag):
        out = []                                  # (long lists are split over several tags)
        for m in re.finditer(r"<" + tag + r">(.*?)</" + tag + ">", body, re.S):
            out += [n.strip() for n in re.split(r"[,\s]+", m.group(1)) if n.strip()]
        return out


class Model:
    def __init__(self, game, folder, data):
        self.game, self.folder, self.data = game, Path(folder), data
        base_key = data["template"] if data["kind"] == "new" else data["map"]
        self.info = game.map_info(base_key)
        self.reload_layer()
        self.base = {}
        if self.info["eras"]:
            for n, rel in self.info["eras"].items():
                self.base[n] = Campaign(rel, game.read(rel, self.layer), prefix=f"{base_key}_Era_{n}_")
        else:
            rel = self.info["single"]
            text = game.read(rel, self.layer)
            if self.info.get("set"):
                self.base[0] = Campaign(rel, text, cset=self.info["set"])
            else:
                self.base[0] = Campaign(rel, text, prefix=f"{base_key}_")
        for n in self.base:
            data["eras"].setdefault(str(n), True)
        data.setdefault("imports", {})
        self.factions = []
        for c in self.base.values():
            for f in c.factions:
                if f not in self.factions:
                    self.factions.append(f)
        self.cache = {}

    def reload_layer(self):
        self.layer = tuple(self.data.get("layer") or self.info["layer"])
        self.planets = {k: v for k, v in self.game.planets(self.layer).items() if self.game.is_world(k, v)}
        self.route_pairs, self.route_names = self.game.routes(self.layer)

    # --- saving ---
    def save(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        for sub in ("Maps", "Models", "Textures"):
            (self.folder / "Data" / "Art" / sub).mkdir(parents=True, exist_ok=True)
        (self.folder / "project.json").write_text(json.dumps(self.data, indent=1, sort_keys=True), encoding="utf-8")

    def snapshot(self):
        return copy.deepcopy(self.data)

    def restore(self, data):
        self.data.clear()
        self.data.update(data)
        self.reload_layer()
        self.changed()

    def changed(self):
        self.cache = {}

    @property
    def is_new(self):
        return self.data["kind"] == "new"

    @property
    def single(self):
        return not self.info["eras"]

    @property
    def title(self):
        return self.data.get("title") or self.info["title"]

    # --- start dates ---
    def era_list(self):
        """The starts this map can have: every date the mod's menu knows (a map with one fixed start: [0])."""
        if self.single:
            return [0]
        return sorted(set(self.base) | {d["n"] for d in self.game.dates})

    def ticked(self, era):
        return self.data["eras"].get(str(era), era in self.base)

    def ticked_eras(self):
        return [e for e in self.era_list() if self.ticked(e)]

    def nearest_base(self, era):
        if era in self.base:
            return era
        return min(self.base, key=lambda b: (abs(b - era), -b))

    def has_content(self, era):
        d = self.game.date(era)
        return era in self.base or bool(d and d["content"])

    # --- the starts ---
    def base_state(self, era):
        """A start as the mod's file has it (a date the map lacks: its nearest date's)."""
        if self.data["blank"]:
            return {"worlds": [], "lanes": [], "owners": {}}
        c = self.base[self.nearest_base(era)]
        worlds = [w.upper() for w in c.locations if w.upper() in self.planets]
        lanes = []
        for r in c.routes:
            pair = self.route_names.get(r.upper())
            if pair and pair[0] in worlds and pair[1] in worlds:
                lanes.append(sorted(pair))
        return {"worlds": worlds, "lanes": lanes, "owners": {w: c.owners[w] for w in worlds if w in c.owners}}

    def state(self, era):
        key = ("state", era)
        if key not in self.cache:
            s = self.data["starts"].get(str(era)) or self.base_state(era)
            self.cache[key] = {"worlds": [w for w in s["worlds"] if self.planet(w)],
                               "lanes": {frozenset(p) for p in s["lanes"] if len(set(p)) == 2},
                               "owners": dict(s["owners"])}
        return self.cache[key]

    def edit_state(self, era):
        """The start, made the project's own (to be changed)."""
        if str(era) not in self.data["starts"]:
            self.data["starts"][str(era)] = copy.deepcopy(self.base_state(era))
        self.changed()
        return self.data["starts"][str(era)]

    def worlds(self, era):
        return self.state(era)["worlds"]

    def lanes(self, era):
        s = self.state(era)
        worlds = set(s["worlds"])
        return {p for p in s["lanes"] if p <= worlds}

    def owner(self, era, world):
        return self.state(era)["owners"].get(world.upper()) or NEW_OWNER

    def base_owner(self, era, world):
        if self.data["blank"] or era not in self.base:
            return None
        return self.base[era].owners.get(world.upper())

    def all_eras(self):
        return [e for e in self.era_list() if str(e) in self.data["starts"] or e in self.base]

    # --- worlds ---
    def planet(self, name):
        name = name.upper()
        if name in self.data["new_planets"]:
            p = dict(self.data["new_planets"][name])
            p.setdefault("pos", [0, 0, 0])
            p.setdefault("land_slots", 4)
            p.setdefault("space_slots", 99)
            p.setdefault("station", 3)
            p["new"] = True
            p["key"] = name
            return p
        base = self.planets.get(name)
        if not base:
            return None
        p = {k: v for k, v in base.items() if k != "body"}
        p["new"] = False
        p["key"] = name
        p.update(self.data["planets"].get(name, {}))
        return p

    def display_name(self, name):
        p = self.planet(name)
        if not p:
            return name.replace("_", " ").title()
        if p.get("display"):
            return p["display"]
        return name.replace("_", " ").title() if p["new"] else self.game.planet_name(p)

    def pool(self):
        names = set(self.planets) | set(self.data["new_planets"])
        return sorted(names)

    # --- worlds imported from other mods ---
    def imported(self, name):
        """(mod id, mod name, world) of a world imported from another mod and not on the map yet, or None."""
        name = name.upper()
        if name in self.data["new_planets"]:
            return None
        for mod_id, entry in self.data.get("imports", {}).items():
            if name in entry["planets"]:
                return mod_id, entry["name"], entry["planets"][name]
        return None

    def imported_names(self):
        out = []
        for entry in self.data.get("imports", {}).values():
            out += [n for n in entry["planets"] if n not in self.data["new_planets"] and n not in self.planets]
        return sorted(set(out))

    def import_planets(self, other):
        """Every world of another game or mod that this one lacks, kept as excluded worlds of this map."""
        have = set(self.game.planets(self.game.all_layer())) | set(self.data["new_planets"])
        worlds = {}
        for name, p in other.planets(other.all_layer()).items():
            if name in have or not other.is_world(name, p):
                continue
            texts = {tag: other.text(key) or "" for tag, key in p.get("describe", {}).items()}
            worlds[name] = {"name": p["name"], "display": other.planet_name(p), "pos": list(p["pos"]),
                            "land": p["land"], "space": p["space"], "model": p["model"], "surface": p["surface"],
                            "land_slots": p["land_slots"], "space_slots": p["space_slots"], "station": p["station"],
                            "texts": {k: v for k, v in texts.items() if v}}
        self.data.setdefault("imports", {})[other.mod_id] = {"name": other.mod["name"], "planets": worlds}
        self.changed()
        return len(worlds)

    def take_import(self, name, other):
        """An imported world becomes one of the map's new worlds: its definition, and its art copied from `other`."""
        mod_id, mod_name, w = self.imported(name)
        self.data["new_planets"][name.upper()] = dict(w, texts=dict(w.get("texts", {})))
        copied = []
        if other is not None:
            wanted = [("Maps", w.get("land")), ("Maps", w.get("space")), ("Models", w.get("model"))]
            stem = Path(w.get("land") if w.get("surface") and w.get("land") else (w.get("space") or "")).stem
            if stem:
                wanted += [("Textures", stem + ".dds"), ("Textures", stem + ".tga")]
            model = other.asset_bytes(w["model"]) if w.get("model") else None
            if model:
                for tex in set(re.findall(rb"[A-Za-z0-9_\-]+\.(?:dds|tga|DDS|TGA)", model)):
                    wanted.append(("Textures", tex.decode("latin-1")))
            for kind, fname in wanted:
                if not fname or (self.art_folder(kind) / Path(fname).name).exists():
                    continue
                if self.game.asset_exists(fname):            # (this mod has it already)
                    continue
                data = other.asset_bytes(fname)
                if data:
                    self.art_folder(kind).mkdir(parents=True, exist_ok=True)
                    (self.art_folder(kind) / Path(fname).name).write_bytes(data)
                    copied.append(fname)
        self.changed()
        return copied

    def add_world(self, name, eras):
        name = name.upper()
        for era in eras:
            s = self.edit_state(era)
            if name not in s["worlds"]:
                s["worlds"].append(name)
        self.changed()

    def remove_world(self, name, eras=None):
        name = name.upper()
        for era in (eras if eras is not None else self.all_eras()):
            if name in self.worlds(era) or str(era) in self.data["starts"]:
                s = self.edit_state(era)
                s["worlds"] = [w for w in s["worlds"] if w != name]
                s["lanes"] = [p for p in s["lanes"] if name not in p]
                s["owners"].pop(name, None)
        self.changed()

    def delete_world(self, name):
        """Takes a world off every start and forgets everything the project has for it (a new world: the world
        itself and its art)."""
        name = name.upper()
        self.remove_world(name)
        self.data["planets"].pop(name, None)
        for entry in self.data.get("imports", {}).values():
            entry["planets"].pop(name, None)
        p = self.data["new_planets"].pop(name, None)
        if p:
            for kind, field in (("Maps", "land"), ("Maps", "space"), ("Models", "model")):
                f = self.art_folder(kind) / Path(p.get(field) or "x").name
                if p.get(field) and f.exists() and not self.file_used_elsewhere(f.name, name):
                    f.unlink()
        self.changed()

    def file_used_elsewhere(self, filename, world):
        for other, p in self.data["new_planets"].items():
            if other != world and filename.upper() in {(p.get(k) or "").upper() for k in ("land", "space", "model")}:
                return True
        return False

    def toggle_lane(self, era, a, b):
        pair = frozenset((a, b))
        s = self.edit_state(era)
        listed = [p for p in s["lanes"] if frozenset(p) == pair]
        if listed:
            for p in listed:
                s["lanes"].remove(p)
            added = False
        else:
            s["lanes"].append(sorted(pair))
            added = True
        self.changed()
        return added

    def set_owner(self, era, world, faction):
        self.edit_state(era)["owners"][world.upper()] = faction
        self.changed()

    def copy_date(self, source, target):
        self.data["starts"][str(target)] = copy.deepcopy({k: (list(map(sorted, v)) if k == "lanes" else
                                                               (list(v) if k == "worlds" else dict(v)))
                                                           for k, v in self.state(source).items()})
        self.changed()

    def copy_map(self, other):
        """This map's starts become the other map's (the same date where it has one, else its first)."""
        for era in self.era_list():
            src = era if era in other.era_list() and (era in other.base or str(era) in other.data["starts"]) \
                else other.all_eras()[0]
            st = other.state(src)
            self.data["starts"][str(era)] = {"worlds": list(st["worlds"]), "lanes": [sorted(p) for p in st["lanes"]],
                                             "owners": dict(st["owners"])}
        for name, p in other.data["new_planets"].items():
            self.data["new_planets"].setdefault(name, copy.deepcopy(p))
        for name, p in other.data["planets"].items():
            self.data["planets"].setdefault(name, copy.deepcopy(p))
        if set(other.layer) - set(self.layer):
            self.data["layer"] = sorted(set(self.layer) | set(other.layer))
            self.reload_layer()
        self.changed()

    def edit_planet(self, name, **fields):
        name = name.upper()
        if name in self.data["new_planets"]:
            for k, v in fields.items():
                if k == "texts":
                    self.data["new_planets"][name].setdefault("texts", {}).update(v)
                else:
                    self.data["new_planets"][name][k] = v
        else:
            edit = self.data["planets"].setdefault(name, {})
            base = self.planets.get(name, {})
            for k, v in fields.items():
                if k == "texts":
                    edit.setdefault("texts", {}).update(v)
                elif base.get(k) == v:
                    edit.pop(k, None)
                else:
                    edit[k] = v
            if not edit:
                self.data["planets"].pop(name, None)
        self.changed()

    def create_planet(self, display, x, y, era):
        """A new world at (x, y): defined for the whole mod, on the map at `era` only."""
        base = safe_name(display)
        name, n = base, 2
        while name.upper() in self.game.planets(self.game.all_layer()) or name.upper() in self.data["new_planets"]:
            name = f"{base}_{n}"
            n += 1
        key = name.upper()
        self.data["new_planets"][key] = {
            "name": name, "display": display, "pos": [round(x), round(y), 0], "surface": True,
            "land": f"{name}_Land.ted", "space": f"{name}_Space.ted", "model": "", "texts": {},
            "land_slots": 4, "space_slots": 99, "station": 3}
        self.add_world(key, [era])
        return key

    def text_of(self, name, tag):
        p = self.planet(name)
        if not p:
            return ""
        if p["new"]:
            return p.get("texts", {}).get(tag, "")
        edit = self.data["planets"].get(name.upper(), {}).get("texts", {})
        if tag in edit:
            return edit[tag]
        return self.game.text(p.get("describe", {}).get(tag)) or ""

    # --- art and completeness ---
    def art_folder(self, kind):
        return self.folder / "Data" / "Art" / kind

    def art_exists(self, kind, name):
        if not name:
            return False
        if (self.art_folder(kind) / Path(name).name).exists():
            return True
        return self.game.asset_exists(name)

    def picture_name(self, name):
        p = self.planet(name)
        if not p:
            return None
        source = p.get("land") if p.get("surface") and p.get("land") else p.get("space")
        return Path(source).stem if source else None

    def missing(self, name):
        p = self.planet(name)
        if not p:
            return []
        edited = p["new"] or any(k in self.data["planets"].get(name.upper(), {}) for k in ("land", "space", "model"))
        if not edited:
            return []
        out = []
        if not self.art_exists("Models", p.get("model")):
            out.append("galaxy map model")
        if not self.art_exists("Maps", p.get("space")):
            out.append("space battle map")
        if p.get("surface") and not self.art_exists("Maps", p.get("land")):
            out.append("land battle map")
        return out

    def incomplete(self):
        names = set()
        for era in self.ticked_eras():
            names |= set(self.worlds(era))
        return sorted(n for n in names if self.missing(n))

    def world_count(self, era=None):
        eras = [era] if era is not None else self.ticked_eras()
        return max((len(self.worlds(e)) for e in eras), default=0)

    def needed_submods(self):
        """The submods this map needs: those its worlds come from."""
        used = set()
        for era in self.ticked_eras():
            used |= set(self.worlds(era))
        need = set(self.info["layer"])
        for w in used:
            s = self.game.submod_of_world(w)
            if s and w not in self.data["new_planets"]:
                need.add(s["id"])
        return sorted(need)
