"""The game as installed: Empire at War, Forces of Corruption and every full mod found, each read through its stack of
Data folders and archives (its submods over the mod, the mod over the base game).

A "layer" is the set of submods a map is read with (a tuple of their ids): () is the mod alone; a map or world that
only a submod has needs that submod.
"""
import json
import re
import threading
import urllib.parse
import urllib.request
from pathlib import Path

import formats

APP_ID = "32470"
TR_MENU = r"Scripts\Story\GCMenuTranslator.lua"
CATEGORIES = [("Progressive", "ProgressiveMaps", "prog"), ("Regional", "RegionalMaps", "reg"),
              ("Historical", "HistoricalMaps", "hist"), ("Custom", "CustomMaps", "inf")]
STANDARD_CATEGORY = "Galactic Conquest"
SLOTS_PER_CATEGORY = 32
STANDARD_SLOTS = 64
HIDDEN_WORLDS = {"GALAXY_CORE_ART_MODEL"}
NUMBER_WORDS = ["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
                "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen", "Twenty"]
SKIP_MEGS = ("speech", "music", "movies", "cinematics")


# --- finding the game ---
def steam_libraries():
    roots = []
    try:
        import winreg
        for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam")):
            try:
                with winreg.OpenKey(hive, key) as k:
                    for value in ("SteamPath", "InstallPath"):
                        try:
                            roots.append(Path(winreg.QueryValueEx(k, value)[0]))
                        except OSError:
                            pass
            except OSError:
                pass
    except ImportError:
        pass
    roots += [Path(r"C:\Program Files (x86)\Steam"), Path(r"C:\Program Files\Steam")]
    libraries = []
    for root in roots:
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():
            for p in re.findall(r'"path"\s*"([^"]+)"', vdf.read_text(encoding="utf-8", errors="replace")):
                libraries.append(Path(p.replace("\\\\", "\\")) / "steamapps")
        libraries.append(root / "steamapps")
    out = []
    for lib in libraries:
        try:
            if lib.exists() and lib.resolve() not in [o.resolve() for o in out]:
                out.append(lib)
        except OSError:
            pass
    return out


def find_installs(settings):
    """(game folder ...\\Star Wars Empire at War, Workshop folder ...\\content\\32470); either may be None. A folder
    the user chose (settings) wins."""
    game = Path(settings["game"]) if settings.get("game") else None
    workshop = Path(settings["workshop"]) if settings.get("workshop") else None
    for lib in steam_libraries():
        if game is None and (lib / "common" / "Star Wars Empire at War").exists():
            game = lib / "common" / "Star Wars Empire at War"
        if workshop is None and (lib / "workshop" / "content" / APP_ID).exists():
            workshop = lib / "workshop" / "content" / APP_ID
    return game, workshop


def child(folder, name):
    """A file or folder in `folder`, whatever its case."""
    if not folder or not folder.exists():
        return None
    p = folder / name
    if p.exists():
        return p
    low = name.lower()
    for c in folder.iterdir():
        if c.name.lower() == low:
            return c
    return None


def is_full_mod(data):
    xml = child(data, "XML")
    return bool(xml and child(xml, "GameObjectFiles.xml") and child(xml, "CampaignFiles.xml")
                and child(xml, "Factions.xml"))


def modinfo(folder):
    """(name, [dependency ids]) from a mod's modinfo.json files, if it has them."""
    name, deps = None, []
    for f in sorted(folder.glob("*modinfo.json")):
        try:
            info = json.loads(f.read_text(encoding="utf-8-sig", errors="replace"))
        except ValueError:
            continue
        name = name or info.get("name")
        deps += [str(d.get("identifier")) for d in info.get("dependencies", []) if isinstance(d, dict)]
    return name, deps


def workshop_titles(ids, cache):
    """Titles of Workshop items from Steam (remembered in `cache`); unknown ones are left out."""
    wanted = [i for i in ids if i not in cache]
    if wanted:
        try:
            body = {"itemcount": len(wanted)}
            for n, i in enumerate(wanted):
                body[f"publishedfileids[{n}]"] = i
            req = urllib.request.Request(
                "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/",
                data=urllib.parse.urlencode(body).encode(), method="POST")
            with urllib.request.urlopen(req, timeout=4) as r:
                for d in json.loads(r.read().decode("utf-8")).get("response", {}).get("publishedfiledetails", []):
                    if d.get("title"):
                        cache[str(d["publishedfileid"])] = d["title"]
        except Exception:
            pass
    return {i: cache[i] for i in ids if i in cache}


def detect(game_dir, workshop, settings):
    """[{id, name, kind: base | workshop | local, base: EAW | FOC, data: Path or None, submods: [...]}] of every game
    and full mod found; submods: [{id, name, data}] that go with it."""
    out = []
    if game_dir and child(child(game_dir / "GameData", "Data"), "Config.meg"):
        out.append({"id": "EAW", "name": "Empire at War", "kind": "base", "base": "EAW", "data": None, "submods": []})
    if game_dir and child(child(game_dir / "corruption", "Data"), "Config.meg"):
        out.append({"id": "FOC", "name": "Forces of Corruption", "kind": "base", "base": "FOC", "data": None,
                    "submods": []})
    mods, subs = [], []
    folders = []
    if workshop and workshop.exists():
        folders += [("workshop", d) for d in sorted(workshop.iterdir()) if d.is_dir()]
    for base, sub in (("FOC", "corruption"), ("EAW", "GameData")):
        if game_dir and (game_dir / sub / "Mods").exists():
            folders += [("local:" + base, d) for d in sorted((game_dir / sub / "Mods").iterdir()) if d.is_dir()]
    for kind, d in folders:
        data = child(d, "Data")
        if not data or d.name.startswith("GalaxyMaps_"):
            continue
        name, deps = modinfo(d)
        entry = {"id": d.name if kind == "workshop" else f"Mods\\{d.name}", "folder": d, "name": name, "deps": deps,
                 "data": data, "kind": "workshop" if kind == "workshop" else "local",
                 "base": "EAW" if kind == "local:EAW" else "FOC"}
        (mods if is_full_mod(data) else subs).append(entry)
    # a mod that lists object files it lacks and the base game lacks, but another full mod has, is that mod's submod
    base_xml = base_names(game_dir)
    for m in list(mods):
        if m["deps"]:
            mods.remove(m)
            subs.append(m)
            continue
        parent = parent_mod(m, [n for n in mods if n is not m], base_xml)
        if parent:
            mods.remove(m)
            subs.append(m)
            m["deps"] = [parent["id"]]
    cache = settings.setdefault("titles", {})
    titles = workshop_titles([m["id"] for m in mods + subs if m["kind"] == "workshop" and not m["name"]], cache)
    for m in mods + subs:
        if not m["name"]:
            m["name"] = titles.get(m["id"]) or (f"Workshop mod {m['id']}" if m["kind"] == "workshop" else m["folder"].name)
    for m in mods:
        m["submods"] = []
    for s in subs:
        owner = next((m for m in mods if m["id"] in s["deps"]), None) or best_overlap(s, mods)
        if owner:
            owner["submods"].append({"id": s["id"], "name": s["name"], "data": s["data"]})
    return out + [{k: m[k] for k in ("id", "name", "kind", "base", "data", "submods")} for m in mods]


def base_names(game_dir):
    """Upper-case XML file names the base games hold in their archives."""
    names = set()
    for sub in ("corruption", "GameData"):
        data = child(game_dir / sub, "Data") if game_dir else None
        if not data:
            continue
        for meg in ("Config.meg", "Patch.meg", "Patch2.meg", "64Patch.meg"):
            p = child(data, meg)
            if p:
                try:
                    names |= {n.rsplit("\\", 1)[-1] for n in formats.Meg(p).files if n.endswith(".XML")}
                except Exception:
                    pass
    return names


def parent_mod(m, others, base_xml):
    """The full mod a complete-looking mod builds on: the object files it lists but neither it nor the base game has
    are (mostly) that mod's."""
    xml = child(m["data"], "XML")
    listed = formats.file_list(formats.decode(child(xml, "GameObjectFiles.xml").read_bytes()))
    foreign = [f for f in listed if not (xml / f.replace("\\", "/")).exists()
               and f.rsplit("\\", 1)[-1].upper() not in base_xml]
    if len(foreign) < 10 or len(foreign) * 5 < len(listed):
        return None
    best, score = None, 0
    for n in others:
        n_xml = child(n["data"], "XML")
        hits = sum(1 for f in foreign if n_xml and (n_xml / f.replace("\\", "/")).exists())
        if hits > score:
            best, score = n, hits
    return best if score * 2 >= len(foreign) else None


def best_overlap(sub, mods):
    """The mod a submod goes with when it doesn't say: the one most of its files replace."""
    files = []
    for p in sub["data"].rglob("*"):
        if p.is_file():
            files.append(p.relative_to(sub["data"]))
        if len(files) > 400:
            break
    best, score = None, 0
    for m in mods:
        n = sum(1 for f in files if (m["data"] / f).exists())
        if n > score:
            best, score = m, n
    return best if score >= 2 else None


# --- reading through a stack ---
class Stack:
    """Data folders and archives, highest first: a file is taken from the first that has it."""

    def __init__(self, sources):
        self.sources = sources            # [("dir", Path) | ("megs", MegList)]

    def find(self, rel):
        rel = rel.replace("/", "\\")
        for kind, s in self.sources:
            if kind == "dir":
                p = s / rel
                if p.exists():
                    return p
        return None

    def read_bytes(self, rel):
        rel = rel.replace("/", "\\")
        for kind, s in self.sources:
            if kind == "dir":
                p = s / rel
                if p.exists():
                    return p.read_bytes()
            else:
                data = s.read("DATA\\" + rel)
                if data is not None:
                    return data
        return None


class MegList:
    """The archives a Data folder lists (MegaFiles.xml), read on first use; later archives replace earlier ones."""

    def __init__(self, data_dir, game_root=None):
        self.data_dir, self.game_root = data_dir, game_root
        self.megs = None
        self.lock = threading.Lock()

    def load(self):
        with self.lock:
            if self.megs is not None:
                return
            megs = []
            root = self.game_root or self.data_dir.parent
            listed = child(self.data_dir, "MegaFiles.xml")
            names = formats.file_list(formats.decode(listed.read_bytes())) if listed else []
            paths = [root / n.strip().replace("/", "\\") for n in names]
            for patch in ("Patch.meg", "Patch2.meg", "64Patch.meg"):
                p = child(self.data_dir, patch)
                if p:
                    paths.append(p)
            for p in paths:
                p = child(p.parent, p.name) if p.parent.exists() else None
                if p and not any(s in p.name.lower() for s in SKIP_MEGS):
                    try:
                        megs.append(formats.Meg(p))
                    except Exception:
                        pass
            self.megs = list(reversed(megs))

    def read(self, name):
        self.load()
        name = name.upper()
        for m in self.megs:
            if name in m.files:
                return m.read(name)
        return None

    def names(self):
        self.load()
        out = {}
        for m in reversed(self.megs):
            for full in m.files:
                out[full.rsplit("\\", 1)[-1]] = (m, full)
        return out


# --- one game or mod ---
class Game:
    def __init__(self, game_dir, mod):
        self.game_dir = Path(game_dir) if game_dir else None
        self.mod = mod
        self.submods = mod.get("submods", [])
        self.sub_by_id = {s["id"]: s for s in self.submods}
        sub = "GameData" if mod["base"] == "EAW" else "corruption"
        base_data = child(self.game_dir / sub, "Data") if self.game_dir else None
        self.exe = child(self.game_dir / sub, "StarWarsG.exe") if self.game_dir else None
        self.mods_dir = (self.game_dir / sub / "Mods") if self.game_dir else None
        self.base_sources = []
        if base_data:
            self.base_sources = [("dir", base_data), ("megs", MegList(base_data, self.game_dir / sub))]
        if mod["base"] == "FOC" and self.game_dir and child(self.game_dir / "GameData", "Data"):
            gd = child(self.game_dir / "GameData", "Data")
            self.art_sources = [("megs", MegList(gd, self.game_dir / "GameData"))]
        else:
            self.art_sources = []
        self.mod_sources = []
        if mod.get("data"):
            self.mod_sources = [("dir", mod["data"]), ("megs", MegList(mod["data"]))]
        self._cache = {}
        self.assets_ready = threading.Event()
        self.loose, self.packed = {}, {}
        threading.Thread(target=self._index_assets, daemon=True).start()
        self.tr_menu = self.read(TR_MENU) is not None
        self.texts = self._texts()
        self.faction_names, self.colors = self._factions()
        self.dates = self._dates() if self.tr_menu else []
        self.maps = self._maps()
        self.warlords = self._warlords()
        self.era_dummies = sorted(set(re.findall(r'Name\s*=\s*"(Era_\w+?_Dummy)"', self.read_all_xml("Era_Dummies"))))

    @property
    def mod_id(self):
        return self.mod["id"]

    # stacks
    def stack(self, layer=()):
        key = ("stack", tuple(layer))
        if key not in self._cache:
            sources = []
            for sid in layer:
                s = self.sub_by_id.get(sid)
                if s:
                    sources += [("dir", s["data"]), ("megs", MegList(s["data"]))]
            self._cache[key] = Stack(sources + self.mod_sources + self.base_sources)
        return self._cache[key]

    def all_layer(self):
        return tuple(s["id"] for s in self.submods)

    def read(self, rel, layer=()):
        key = ("read", rel.lower(), tuple(layer))
        if key not in self._cache:
            data = self.stack(layer).read_bytes(rel)
            self._cache[key] = formats.decode(data) if data is not None else None
        return self._cache[key]

    def read_all_xml(self, stem, layer=()):
        return self.read(f"XML\\{stem}.xml", layer) or ""

    def text(self, key):
        return self.texts.get(key or "", None)

    def _texts(self):
        texts = {}
        for sources in ([self.base_sources[0]] if self.base_sources else [], self.mod_sources[:1],
                        *[[("dir", s["data"])] for s in reversed(self.submods)]):
            for kind, d in sources:
                text_dir = child(d, "Text")
                f = child(text_dir, "MasterTextFile_ENGLISH.dat") if text_dir else None
                if f:
                    try:
                        texts.update(formats.read_dat(f.read_bytes()))
                    except Exception:
                        pass
        return texts

    def base_dat(self, layer=()):
        """The text file a submod of this mod would replace (the highest one in the stack)."""
        for kind, d in self.stack(layer).sources:
            if kind == "dir":
                text_dir = child(d, "Text")
                f = child(text_dir, "MasterTextFile_ENGLISH.dat") if text_dir else None
                if f:
                    return f.read_bytes()
        return None

    # factions
    def _factions(self):
        names, colors = {}, {}
        text = self.read(r"XML\Factions.xml", self.all_layer()) or ""
        for m in re.finditer(r'<Faction\s+Name\s*=\s*"([^"]+)"\s*>(.*?)</Faction>', text, re.S):
            f, body = m.group(1).upper(), m.group(2)
            label = self.text(formats.tag(body, "Text_ID"))
            if label:
                names[f] = label.strip()
            c = formats.tag(body, "Color")
            if c:
                parts = [p for p in re.split(r"[,\s]+", c) if p]
                try:
                    r, g, b = (int(float(x)) for x in parts[:3])
                    colors[f] = "#%02x%02x%02x" % (r, g, b)
                except ValueError:
                    pass
        constants = self.read(r"Scripts\Library\eawx-mod-icw\GameConstants.lua", self.all_layer())
        table = formats.lua_table(constants, "FACTION_COLORS") if constants else None
        for f, c in (table or {}).items():
            if isinstance(c, dict) and all(k in c for k in "rgb"):
                colors[str(f).upper()] = "#%02x%02x%02x" % (int(c["r"]), int(c["g"]), int(c["b"]))
        if self.tr_menu:
            desc = formats.lua_table(self.read(r"Scripts\Story\GCMenu_DescriptionText.lua", self.all_layer()) or "") or {}
            for f, entry in (desc.get("Default_Faction_Text") or {}).items():
                titles = entry.get("Titles") if isinstance(entry, dict) else None
                if isinstance(titles, dict) and isinstance(titles.get("DEFAULT"), str):
                    names[str(f).upper()] = titles["DEFAULT"]
        return names, colors

    def faction_label(self, faction):
        return self.faction_names.get(faction.upper()) or faction.replace("_", " ").title()

    # start dates (Thrawn's menu)
    def _dates(self):
        """[{n, key, label, year, content}] of every start date the mod's menu knows, by its campaign number (Era_N).
        content: some map of the mod offers it."""
        translator = formats.lua_table(self.read(TR_MENU) or "") or {}
        nums = translator.get("Era_XML_Nums") or {}
        offered = formats.lua_table(self.read(r"Scripts\Story\GCMenu_FactionsbyMapEra.lua") or "") or {}
        used = set()
        for entry in offered.values():
            if isinstance(entry, dict):
                used |= {k for k in entry if isinstance(k, str)}
        by_n = {}
        for key, era in nums.items():
            m = re.match(r"Era_(\d+)$", str(era))
            y = re.match(r"([\d.]+)", str(key))
            if not m or not y:
                continue
            n, year = int(m.group(1)), float(y.group(1))
            if n not in by_n or year < by_n[n]["year"]:
                by_n[n] = {"n": n, "key": key, "year": year, "label": f"{year:g} ABY"}
        for d in by_n.values():
            d["content"] = d["key"] in used
        return [by_n[n] for n in sorted(by_n)]

    def date(self, n):
        return next((d for d in self.dates if d["n"] == n), None)

    def date_label(self, n):
        d = self.date(n)
        return d["label"] if d else f"Start {n}"

    # maps
    def _maps(self):
        """[{key, category, title, description, layer, eras: {n: rel}, single: rel or None, year, date, set}]"""
        return self._tr_maps() if self.tr_menu else self._standard_maps()

    def _tr_maps(self):
        out = []
        for layer in [()] + [(s["id"],) for s in self.submods]:
            if layer and not (self.sub_by_id[layer[0]]["data"] / "Scripts" / "Story" / "GCMenuTranslator.lua").exists():
                continue
            source = self.read(TR_MENU, layer) or ""
            translator = formats.lua_table(source) or {}
            # maps a submod adds with code after the table: T["Key"] = "prog_map_07"; table.insert(T["List"], "Key")
            for key, button in re.findall(r'\bT\["(\w+)"\]\s*=\s*"((?:prog|reg|hist|inf)_map_\d+)"', source):
                translator[key] = button
            for list_name, key in re.findall(r'table\.insert\(\s*T\["(\w+)"\]\s*,\s*"(\w+)"\s*\)', source):
                lst = translator.setdefault(list_name, {})
                if isinstance(lst, dict) and key not in formats.lua_list(lst):
                    lst[len(formats.lua_list(lst)) + 1] = key
            desc = self.read(r"Scripts\Story\GCMenu_DescriptionText.lua", layer) or ""
            texts = formats.lua_table(desc) or {}
            map_text = texts.get("Map_Text") or {}
            for title, key in re.findall(r'map\.Title\s*=\s*"([^"]*)"(?:(?!map\.Title).)*?T\.Map_Text\["(\w+)"\]\s*=\s*map',
                                         desc, re.S):
                map_text.setdefault(key, {})["Title"] = title
            for d, key in re.findall(r'map\.Description\s*=\s*"((?:\\.|[^"\\])*)"(?:(?!map\.Description).)*?'
                                     r'T\.Map_Text\["(\w+)"\]\s*=\s*map', desc, re.S):
                if isinstance(map_text.get(key), dict):
                    map_text[key].setdefault("Description", d)
            index = self.campaign_index(layer)
            for category, list_name, prefix in CATEGORIES:
                for key in formats.lua_list(translator.get(list_name)):
                    if any(m["key"] == key for m in out):
                        continue
                    eras = {}
                    for n in range(1, 30):
                        rel = index.get(f"{key}_ERA_{n}".upper())
                        if rel:
                            eras[n] = rel
                    single = None if eras else index.get(key.upper())
                    if not eras and not single:
                        continue
                    entry = map_text.get(key) if isinstance(map_text.get(key), dict) else {}
                    rel = single or eras[min(eras)]
                    year = re.search(r"(\d+(?:\.\d+)?)_ABY", rel)
                    out.append({"key": key, "category": category, "button": translator.get(key),
                                "title": entry.get("Title") or key, "description": entry.get("Description") or "",
                                "layer": layer, "eras": eras, "single": single, "set": None,
                                "date": entry.get("DateOverride") if isinstance(entry.get("DateOverride"), str) else None,
                                "year": float(year.group(1)) if year else 4})
        return out

    def _standard_maps(self):
        out = []
        for layer in [()] + [(s["id"],) for s in self.submods]:
            for rel in formats.file_list(self.read(r"XML\CampaignFiles.xml", layer) or ""):
                text = self.read("XML\\" + rel, layer)
                if not text:
                    continue
                for m in re.finditer(r'<Campaign\s+Name\s*=\s*"([^"]+)"\s*>(.*?)</Campaign>', text, re.S):
                    body = m.group(2)
                    listed = (formats.tag(body, "Is_Listed") or "true").strip().lower()
                    cset = (formats.tag(body, "Campaign_Set") or "").strip()
                    if listed in ("false", "no") or not cset or any(x["key"] == cset for x in out):
                        continue
                    if any(w in cset.upper() for w in ("MULTIPLAYER", "TUTORIAL", "DIVIDER", "SHELL", "SPACER")):
                        continue
                    if not re.search(r"<Locations>\s*\S", body):
                        continue
                    title = self.text(formats.tag(body, "Text_ID")) or cset.replace("_", " ")
                    if title.strip().startswith("="):
                        continue
                    if any(x["title"] == title.strip() for x in out):
                        title = f"{title.strip()} ({cset})"
                    stem = Path(rel.replace("\\", "/")).stem
                    group = re.sub(r"^(Campaigns?|Conquests?)_", "", stem, flags=re.I).replace("_", " ").strip()
                    category = group.title() if group and group.lower() not in ("gc", "campaigns") else STANDARD_CATEGORY
                    out.append({"key": cset, "category": category, "button": None, "title": title.strip(),
                                "description": (self.text(formats.tag(body, "Description_Text")) or "").strip(),
                                "layer": layer, "eras": {}, "single": "XML\\" + rel, "set": cset, "date": None,
                                "year": 0})
        return out

    def campaign_index(self, layer):
        key = ("campaigns", tuple(layer))
        if key in self._cache:
            return self._cache[key]
        out = {}
        for rel in formats.file_list(self.read(r"XML\CampaignFiles.xml", layer) or ""):
            text = self.read("XML\\" + rel, layer)
            if not text:
                continue
            for name in re.findall(r'<Campaign\s+Name\s*=\s*"([^"]+)"', text):
                up = name.upper()
                m = re.match(r"(.+_ERA_\d+)_", up)
                if m:
                    out.setdefault(m.group(1), "XML\\" + rel)
                parts = up.split("_")
                for i in range(1, len(parts)):
                    out.setdefault("_".join(parts[:i]), "XML\\" + rel)
        self._cache[key] = out
        return out

    def map_info(self, key):
        return next((m for m in self.maps if m["key"] == key), None)

    def map_keys(self):
        return {m["key"].upper() for m in self.maps}

    # worlds
    def planets(self, layer=()):
        """{NAME: {name, rel, pos, text_id, land, space, model, surface, land_slots, space_slots, station, body}}"""
        key_ = ("planets", tuple(layer))
        if key_ in self._cache:
            return self._cache[key_]
        raw = {}
        for f in formats.file_list(self.read(r"XML\GameObjectFiles.xml", layer) or ""):
            rel = "XML\\" + f
            text = self.read(rel, layer)
            if not text or "<Planet" not in text:
                continue
            for m in re.finditer(r'<Planet\s+Name\s*=\s*"([^"]+)"\s*>(.*?)</Planet>', formats.strip_comments(text), re.S):
                raw.setdefault(m.group(1).upper(), (m.group(1), rel, m.group(2)))

        def get(name, tag_name, depth=0):
            """A field of a world, or of the world it is a variant of."""
            entry = raw.get(name)
            if not entry or depth > 8:
                return None
            value = formats.tag(entry[2], tag_name)
            if value is not None:
                return value
            parent = formats.tag(entry[2], "Variant_Of_Existing_Type")
            return get(parent.upper(), tag_name, depth + 1) if parent else None

        out = {}
        for key, (name, rel, body) in raw.items():
            pos = get(key, "Galactic_Position")
            if not pos:
                continue
            try:
                xyz = [float(v) for v in pos.split(",")[:3]]
            except ValueError:
                continue
            while len(xyz) < 3:
                xyz.append(0.0)

            def num(tag_name):
                try:
                    return int(float(get(key, tag_name) or 0))
                except ValueError:
                    return 0
            describe = {}
            for t_name in ("History", "Population", "Terrain", "Weather", "Wildlife", "Advantage", "Tactical"):
                v = get(key, "Describe_" + t_name)
                if v:
                    describe[t_name] = v.strip()
            out[key] = {"name": name, "rel": rel, "pos": xyz, "text_id": get(key, "Text_ID"),
                        "land": get(key, "Land_Tactical_Map") or "", "space": get(key, "Space_Tactical_Map") or "",
                        "model": get(key, "Galactic_Model_Name") or "",
                        "surface": (get(key, "Planet_Surface_Accessible") or "").strip().lower().startswith("y"),
                        "land_slots": num("Special_Structures_Land"), "space_slots": num("Special_Structures_Space"),
                        "station": num("Max_Space_Base"), "body": body, "describe": describe,
                        "template": name.upper().endswith("_TEMPLATE")}
        self._cache[key_] = out
        return out

    def planet_name(self, planet):
        return (self.text(planet.get("text_id")) or planet["name"].replace("_", " ")).strip()

    def is_world(self, name, planet):
        if name in HIDDEN_WORLDS or name in self.map_keys() or planet.get("template"):
            return False
        return not self.planet_name(planet).lower().startswith("loading")

    def submod_of_world(self, name):
        """The submod a world comes from (None: the mod has it)."""
        if name in self.planets(()):
            return None
        for s in self.submods:
            if name in self.planets((s["id"],)):
                return s
        return None

    # hyperlanes
    def routes(self, layer=()):
        key = ("routes", tuple(layer))
        if key in self._cache:
            return self._cache[key]
        by_pair, by_name = {}, {}
        for f in formats.file_list(self.read(r"XML\TradeRouteFiles.xml", layer) or ""):
            text = self.read("XML\\" + f, layer)
            if not text:
                continue
            for m in re.finditer(r'<TradeRoute\s+Name\s*=\s*"([^"]+)"\s*>(.*?)</TradeRoute>', formats.strip_comments(text), re.S):
                a, b = formats.tag(m.group(2), "Point_A"), formats.tag(m.group(2), "Point_B")
                if a and b:
                    pair = frozenset((a.upper(), b.upper()))
                    by_pair.setdefault(pair, m.group(1))
                    by_name[m.group(1).upper()] = (a.upper(), b.upper())
        self._cache[key] = (by_pair, by_name)
        return by_pair, by_name

    # Proteus warlords
    def _warlords(self):
        rel = r"Scripts\Library\ProteusWarlordLibrary.lua"
        base_text = self.read(rel)
        if base_text is None and not any((s["data"] / "Scripts" / "Library" / "ProteusWarlordLibrary.lua").exists()
                                         for s in self.submods):
            return []
        lib = dict(formats.lua_table(base_text) or {}) if base_text else {}
        base_keys = set(lib)
        for s in self.submods:
            p = s["data"] / "Scripts" / "Library" / "ProteusWarlordLibrary.lua"
            if p.exists():
                lib.update(formats.lua_table(formats.decode(p.read_bytes())) or {})
        out = []
        for key, e in lib.items():
            if not isinstance(e, dict):
                continue
            overrides = [str(e[k]).upper() for k in ("FactionOverride", "FactionOverride2", "FactionOverride3")
                         if isinstance(e.get(k), str)]
            name = e.get("FriendlyName")
            out.append({"key": key, "name": name if isinstance(name, str) else key.replace("_", " ").title(),
                        "start": e.get("StartYear"), "last": e.get("LastYear"), "planets": e.get("Planets"),
                        "overrides": overrides, "extra": key not in base_keys})
        return out

    @staticmethod
    def warlord_planets(entry, year):
        planets = entry["planets"]
        if not isinstance(planets, dict):
            return []
        if isinstance(planets.get(1), dict):
            best, chosen = 0, planets[1]
            for k, v in planets.items():
                if isinstance(k, (int, float)) and year >= k > best and isinstance(v, dict):
                    best, chosen = k, v
            planets = chosen
        return [str(p).upper() for p in formats.lua_list(planets)]

    def era_dummy(self, n):
        name = f"Era_{NUMBER_WORDS[n]}_Dummy" if n < len(NUMBER_WORDS) else None
        return name if name and name.upper() in {d.upper() for d in self.era_dummies} else None

    # art
    def _index_assets(self):
        try:
            dirs = [s["data"] for s in self.submods] + ([self.mod["data"]] if self.mod.get("data") else [])
            dirs += [d for k, d in self.base_sources if k == "dir"]
            for root in dirs:
                art = child(root, "Art")
                for folder in ("Maps", "Models", "Textures"):
                    d = child(art, folder) if art else None
                    if d:
                        for p in d.iterdir():
                            self.loose.setdefault(p.name.upper(), p)
            megs = [s for k, s in self.mod_sources + self.base_sources + self.art_sources if k == "megs"]
            for s in self.submods:
                megs.append(MegList(s["data"]))
            for ml in megs:
                try:
                    for name, ref in ml.names().items():
                        self.packed.setdefault(name, ref)
                except Exception:
                    pass
        finally:
            self.assets_ready.set()

    def asset_exists(self, name):
        if not name:
            return False
        self.assets_ready.wait()
        base = Path(name.replace("\\", "/")).name.upper()
        return base in self.loose or base in self.packed

    def asset_bytes(self, name):
        self.assets_ready.wait()
        base = Path(name.replace("\\", "/")).name.upper()
        if base in self.loose:
            return self.loose[base].read_bytes()
        if base in self.packed:
            meg, full = self.packed[base]
            return meg.read(full)
        return None

    def asset_folder(self, name):
        self.assets_ready.wait()
        p = self.loose.get(Path(name.replace("\\", "/")).name.upper())
        return p.parent if p else None

    def asset_names(self, extension):
        self.assets_ready.wait()
        ext = extension.upper()
        return sorted({n for n in list(self.loose) + list(self.packed) if n.endswith(ext)})
