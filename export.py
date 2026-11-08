"""Writes maps as a mod folder (Data\\ and modinfo.json): one map to upload, or every map of a game or mod to play.

Thrawn's-style menus: each map takes one of the menu's buttons (GalaxyMaps\\<button>.lua); the menu files every map
carries are the same, so maps from different uploads don't hide each other. Other games and mods: maps go into the
standard campaign list (GalaxyMaps\\std_map_NN). The game's file lists name a file for every button and map (it skips
the ones a mod lacks).
"""
import json
import re
import shutil
from pathlib import Path

import formats
import gamedata

MENU_FILES = ["GCMenuTranslator.lua", "GCMenu_FactionsbyMapEra.lua", "GCMenu_DescriptionText.lua",
              "GCMenu_MapText.lua", "GCMenu_FactionText.lua", "GCMenu_ProteusbyMapEra.lua"]
PLANET_TEMPLATE = "Bespin"
RESERVED_BUTTONS = {"inf_map_08"}          # taken by a widely used submod's own map
ROUTES_PER_LIST = 100                     # lanes per <Trade_Routes> list


def tr_buttons(category=None):
    out = []
    for cat, _, prefix in gamedata.CATEGORIES:
        if category and cat != category:
            continue
        for i in range(1, gamedata.SLOTS_PER_CATEGORY + 1):
            b = f"{prefix}_map_{i:02d}"
            if b not in RESERVED_BUTTONS:
                out.append(b)
    return out


def std_slots():
    return [f"std_map_{i:02d}" for i in range(1, gamedata.STANDARD_SLOTS + 1)]


def category_of_button(button):
    prefix = button.split("_map_")[0]
    return next((c for c, _, p in gamedata.CATEGORIES if p == prefix), None)


def lua_string(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "") + '"'


def lua_merge(source, code):
    i = source.find("return {")
    if i < 0:
        raise ValueError("unexpected menu file format")
    return source[:i] + "local T = {" + source[i + len("return {"):] + "\r\n\r\n" + code.strip().replace("\n", "\r\n") \
        + "\r\nreturn T\r\n"


def crlf(text):
    return text.replace("\r\n", "\n").replace("\n", "\r\n")


class Writer:
    def __init__(self, root):
        self.root = Path(root)
        self.count = 0

    def write(self, rel, data):
        path = self.root / rel.replace("\\", "/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        self.count += 1


# --- who uses which button ---
def installed_slots(game, skip=()):
    """{button: description} of buttons that maps of other uploads installed on this PC use."""
    taken = {}
    folders = []
    if game.mod.get("data"):
        folders += [s["data"].parent for s in game.submods]
    if game.mods_dir and game.mods_dir.exists():
        folders += [d for d in game.mods_dir.iterdir() if d.is_dir()]
    for d in folders:
        if d.name in skip:
            continue
        slots = gamedata.child(gamedata.child(gamedata.child(gamedata.child(d, "Data"), "Scripts"), "Library"),
                               "GalaxyMaps") if gamedata.child(d, "Data") else None
        if slots:
            for f in slots.glob("*_map_*.lua"):
                m = re.search(r'title\s*=\s*"((?:\\.|[^"\\])*)"', f.read_text(encoding="latin-1"))
                taken.setdefault(f.stem, f"{m.group(1) if m else 'a map'} ({d.name})")
    return taken


def button_layout(game, projects):
    """{button: (kind, key, title, movable)} for the mod's own maps (with the projects' moves) and the projects'
    new maps; kind: mod | yours | other."""
    out = {}
    translator = formats.lua_table(game.read(gamedata.TR_MENU, game.all_layer()) or "") or {}
    moved = {d["map"]: d.get("button") for _, d in projects if d["kind"] == "edit" and d.get("button")}
    for m in game.maps:
        b = moved.get(m["key"]) or translator.get(m["key"]) or m.get("button")
        if isinstance(b, str):
            out[b] = ("mod", m["key"], m["title"], b not in RESERVED_BUTTONS)
    for folder, d in projects:
        if d["kind"] == "new" and d.get("slot"):
            out[d["slot"]] = ("yours", str(folder), d.get("title") or folder.name, True)
    skip = {f"GalaxyMaps_{gamedata_name(game)}"}
    for b, who in installed_slots(game, skip).items():
        out.setdefault(b, ("other", None, who, False))
    for b in RESERVED_BUTTONS:
        out.setdefault(b, ("other", None, "a submod's own map", False))
    return out


def gamedata_name(game):
    import project
    return project.safe_name(game.mod["name"])


# --- shared menu support (Thrawn's-style menus) ---
MENU_HELPER = """-- Maps made with the Galaxy Map Editor. Each one takes a button of the galactic conquest menu: its file
-- GalaxyMaps\\<button>.lua names the map, the map it was started from, and its start dates. GalaxyMaps\\Edit_<map>.lua
-- changes one of the mod's own maps (its start dates, or the button it uses).
local Menu = {slots = {}, labels = {}}
local CATEGORIES = {{"prog", "ProgressiveMaps"}, {"reg", "RegionalMaps"}, {"hist", "HistoricalMaps"}, {"inf", "CustomMaps"}}
local RESERVED = {inf_map_08 = true}

function Menu.label(map)
\tif map.worlds then
\t\treturn map.title .. " (" .. map.worlds .. ")"
\tend
\treturn map.title
end

for _, c in ipairs(CATEGORIES) do
\tfor i = 1, 32 do
\t\tlocal button = c[1] .. "_map_" .. ((i < 10) and "0" or "") .. i
\t\tif not RESERVED[button] then
\t\t\tlocal ok, map = pcall(require, "GalaxyMaps/" .. button)
\t\t\tif ok and type(map) == "table" and map.key then
\t\t\t\tmap.button = button
\t\t\t\tmap.list = c[2]
\t\t\t\ttable.insert(Menu.slots, map)
\t\t\t\tMenu.labels[map.key] = Menu.label(map)
\t\t\tend
\t\tend
\tend
end

Menu.edits = {}
function Menu.edit(key)
\tif Menu.edits[key] == nil then
\t\tlocal ok, e = pcall(require, "GalaxyMaps/Edit_" .. key)
\t\tif ok and type(e) == "table" then
\t\t\tMenu.edits[key] = e
\t\t\tif e.button and e.title then
\t\t\t\tMenu.labels[key] = Menu.label(e)
\t\t\tend
\t\telse
\t\t\tMenu.edits[key] = false
\t\tend
\tend
\treturn Menu.edits[key] or nil
end

function Menu.copy(t)
\tif type(t) ~= "table" then
\t\treturn t
\tend
\tlocal out = {}
\tfor k, v in pairs(t) do
\t\tout[k] = Menu.copy(v)
\tend
\treturn out
end

-- t: {[start date] = ...}: the dates listed (a date the source lacks: the one era_from names); all when none listed
function Menu.keep_eras(t, eras, era_from)
\tif type(t) ~= "table" then
\t\treturn t
\tend
\tif eras == nil or table.getn(eras) == 0 then
\t\treturn Menu.copy(t)
\tend
\tlocal out = {}
\tfor _, era in ipairs(eras) do
\t\tlocal source = t[era]
\t\tif source == nil and era_from then
\t\t\tsource = t[era_from[era]]
\t\tend
\t\tif source ~= nil then
\t\t\tout[era] = Menu.copy(source)
\t\tend
\tend
\treturn out
end

function Menu.keys(T)
\tlocal keys = {}
\tfor key, _ in pairs(T) do
\t\tif type(key) == "string" then
\t\t\ttable.insert(keys, key)
\t\tend
\tend
\treturn keys
end

return Menu
"""

MERGES = {
    "GCMenuTranslator.lua": """
local GalaxyMaps = require("GalaxyMaps/Menu")
for _, key in ipairs(T["AllMaps"]) do
\tlocal edit = GalaxyMaps.edit(key)
\tif edit and edit.button then
\t\tT[key] = edit.button
\tend
end
for _, map in ipairs(GalaxyMaps.slots) do
\tT[map.key] = map.button
\ttable.insert(T["AllMaps"], map.key)
\ttable.insert(T[map.list], map.key)
end""",
    "GCMenu_FactionsbyMapEra.lua": """
local GalaxyMaps = require("GalaxyMaps/Menu")
local thrawn = GalaxyMaps.keys(T)
for _, map in ipairs(GalaxyMaps.slots) do
\tif T[map.template] then
\t\tT[map.key] = GalaxyMaps.keep_eras(T[map.template], map.eras, map.era_from)
\tend
end
for _, key in ipairs(thrawn) do
\tlocal edit = GalaxyMaps.edit(key)
\tif edit and edit.eras then
\t\tT[key] = GalaxyMaps.keep_eras(T[key], edit.eras, edit.era_from)
\tend
end""",
    "GCMenu_ProteusbyMapEra.lua": """
local GalaxyMaps = require("GalaxyMaps/Menu")
for _, maps in pairs(T) do
\tif type(maps) == "table" then
\t\tfor _, key in ipairs(GalaxyMaps.keys(maps)) do
\t\t\tlocal edit = GalaxyMaps.edit(key)
\t\t\tif edit and edit.eras then
\t\t\t\tmaps[key] = GalaxyMaps.keep_eras(maps[key], edit.eras, edit.era_from)
\t\t\tend
\t\tend
\t\tfor _, map in ipairs(GalaxyMaps.slots) do
\t\t\tif maps[map.template] then
\t\t\t\tmaps[map.key] = GalaxyMaps.keep_eras(maps[map.template], map.eras, map.era_from)
\t\t\tend
\t\tend
\tend
end""",
    "GCMenu_DescriptionText.lua": """
local GalaxyMaps = require("GalaxyMaps/Menu")
local function fill_eras(era_from)
\tif T.Default_Era_Text == nil or era_from == nil then
\t\treturn
\tend
\tfor era, source in pairs(era_from) do
\t\tif T.Default_Era_Text[era] == nil and T.Default_Era_Text[source] then
\t\t\tlocal entry = GalaxyMaps.copy(T.Default_Era_Text[source])
\t\t\tentry.Title = (string.gsub(era, "ABY", " ABY"))
\t\t\tT.Default_Era_Text[era] = entry
\t\tend
\tend
end
for _, map in ipairs(GalaxyMaps.slots) do
\tfill_eras(map.era_from)
end
if T.Map_Text then
\tfor _, key in ipairs(GalaxyMaps.keys(T.Map_Text)) do
\t\tlocal edit = GalaxyMaps.edit(key)
\t\tif edit then
\t\t\tfill_eras(edit.era_from)
\t\tend
\tend
\tfor _, map in ipairs(GalaxyMaps.slots) do
\t\tlocal entry = GalaxyMaps.copy(T.Map_Text[map.template] or {})
\t\tentry.Title = map.title
\t\tentry.Description = map.description
\t\tif map.date then
\t\t\tentry.DateOverride = map.date
\t\tend
\t\tT.Map_Text[map.key] = entry
\tend
end""",
    "GCMenu_MapText.lua": """
local GalaxyMaps = require("GalaxyMaps/Menu")
for _, map in ipairs(GalaxyMaps.slots) do
\tfor i = 1, 11 do
\t\tif T[map.template .. i] ~= nil and T[map.key .. i] == nil then
\t\t\tT[map.key .. i] = T[map.template .. i]
\t\tend
\tend
end""",
    "GCMenu_FactionText.lua": """
local GalaxyMaps = require("GalaxyMaps/Menu")
for _, map in ipairs(GalaxyMaps.slots) do
\tif T[map.template .. "_TITLE"] then
\t\tT[map.key .. "_TITLE"] = map.title
\tend
\tif T[map.template] then
\t\tT[map.key] = T[map.template]
\tend
end""",
}

MASTER_SCRIPT = """

-- Map buttons (GalaxyMaps\\Menu.lua): any button may hold any map of its list.
GalaxyMapsMenu = require("GalaxyMaps/Menu")
GalaxyMapsButtons = {%s}

function GalaxyMaps_Key(button)
\tif Translator_Table == nil or Translator_Table["AllMaps"] == nil then
\t\treturn nil
\tend
\tfor _, key in ipairs(Translator_Table["AllMaps"]) do
\t\tif Translator_Table[key] == button then
\t\t\treturn key
\t\tend
\tend
\treturn nil
end

function GalaxyMaps_Click(button, message)
\tif message == OnEnter then
\t\tlocal key = GalaxyMaps_Key(button)
\t\tif key then
\t\t\tMap_Selected = Toggle_Check(key, Map_Selected)
\t\t\tSetup_Map_Text(Map_Selected)
\t\tend
\telseif message == OnUpdate then
\t\tcrossplot:update()
\tend
end

function GalaxyMaps_Handler(button)
\treturn function(message)
\t\tGalaxyMaps_Click(button, message)
\tend
end

GalaxyMaps_Definitions = Definitions
function Definitions()
\tGalaxyMaps_Definitions()
\tfor _, button in ipairs(GalaxyMapsButtons) do
\t\tStoryModeEvents[button .. "_click"] = GalaxyMaps_Handler(button)
\tend
end

GalaxyMaps_Load_GC_Selector = State_Load_GC_Selector
function State_Load_GC_Selector(message)
\tGalaxyMaps_Load_GC_Selector(message)
\tif message == OnEnter then
\t\tfor _, button in ipairs(GalaxyMapsButtons) do
\t\t\tlocal key = GalaxyMaps_Key(button)
\t\t\tif key == nil then
\t\t\t\tDisable_and_Hide_Button(button)
\t\t\t\tDisable_and_Hide_Button("enabled_" .. button)
\t\t\t\tDisable_and_Hide_Button("disabled_" .. button)
\t\t\telseif GalaxyMapsMenu.labels[key] then
\t\t\t\tGUI_Component_Text(button, GalaxyMapsMenu.labels[key])
\t\t\tend
\t\tend
\tend
end
"""

LISTENER = "Scripts\\Library\\eawx-plugins\\selected-planet-listener\\"
OLD_EVENT = 'local event = ctx.plot.Get_Event("Zoom_Into_" .. planetName)'
NEW_EVENT = ('local event = nil\n            if GalaxyMapsZoomEvents[string.upper(planetName)] then\n'
             '                event = ctx.plot.Get_Event("Zoom_Into_" .. planetName)\n            end')
OLD_FLAG = 'if Check_Story_Flag(self.player, "ZOOMED_INTO_" .. planet:get_name(), nil, true) then'
NEW_FLAG = ('if GalaxyMapsZoomEvents[string.upper(planet:get_name())] and '
            'Check_Story_Flag(self.player, "ZOOMED_INTO_" .. planet:get_name(), nil, true) then')
ZOOM_REQUIRE = 'GalaxyMapsZoomEvents = require("GalaxyMaps/ZoomEvents")\n'


def write_menu_support(game, layer, w):
    buttons = tr_buttons()
    components = game.read(r"XML\CommandBarComponents_TR.xml", layer) or ""
    master = game.read(r"Scripts\Story\GC_MasterScript_GCMenu.lua", layer)
    story = game.read(r"XML\Conquests\Story_GCMenu.xml", layer)
    own = [b for b in buttons if f'Name="{b}"' not in components]
    blocks = []
    for b in own:
        prefix = b.split("_map_")[0]
        for variant in ("", "enabled_", "disabled_"):
            m = re.search(r'<CommandBarComponent Name="' + variant + prefix + r'_map_01">.*?</CommandBarComponent>',
                          components, re.S)
            if m:
                blocks.append("\t" + re.sub(r"<!--.*?-->", "", m.group(0).replace(f"{prefix}_map_01", b)))
    w.write(r"Data\XML\CommandBarComponents_GalaxyMaps.xml",
            crlf('<?xml version="1.0" encoding="UTF-8"?>\n<Bar_Components>\n' + "\n\n".join(blocks)
                 + "\n</Bar_Components>\n"))
    w.write(r"Data\XML\CommandBarComponentFiles.xml",
            crlf(merged_list(game, r"XML\CommandBarComponentFiles.xml", "</CommandBar_Component_Files>", layer,
                             ["CommandBarComponents_GalaxyMaps.xml"])))
    events = "".join(
        f'\t<Event Name="{b}_click">\n\t\t<Event_Type>STORY_CLICK_GUI</Event_Type>\n\t\t<Event_Param1>{b}</Event_Param1>\n'
        f"\t\t<Reward_Type>TRIGGER_AI</Reward_Type>\n\t\t<Reward_Param1>{b.upper()}_CLICKED</Reward_Param1>\n"
        f"\t\t<Reward_Param2></Reward_Param2>\n\t\t<Perpetual>true</Perpetual>\n\t</Event>\n\n"
        for b in buttons if f'<Event Name="{b}_click">' not in story)
    i = story.rindex("</Story>")
    w.write(r"Data\XML\Conquests\Story_GCMenu.xml", crlf(story[:i] + events + story[i:]))
    w.write(r"Data\Scripts\Story\GC_MasterScript_GCMenu.lua",
            crlf(master + MASTER_SCRIPT % ", ".join(f'"{b}"' for b in buttons)))
    for name in MENU_FILES:
        w.write("Data\\Scripts\\Story\\" + name, crlf(lua_merge(game.read("Scripts\\Story\\" + name, layer), MERGES[name])))
    w.write(r"Data\Scripts\Library\GalaxyMaps\Menu.lua", crlf(MENU_HELPER))
    write_zoom_guard(game, layer, w)


def write_zoom_guard(game, layer, w):
    """Thrawn's planet listener looks up a story event and a story flag for every world; a world with no event stops
    the script. The worlds that have one are listed, and the listener skips the others (new worlds)."""
    init = game.read(LISTENER + "init.lua", layer)
    event = game.read(LISTENER + "SelectedPlanetChangedEvent.lua", layer)
    if not init or not event or OLD_EVENT not in init or OLD_FLAG not in event:
        return
    plot = game.read(r"XML\Conquests\Player_Agnostic_Plot.xml", layer) or ""
    names = sorted({n.upper() for n in re.findall(r'<Event\s+Name\s*=\s*"Zoom_Into_([^"]+)"', plot)})
    w.write(r"Data\Scripts\Library\GalaxyMaps\ZoomEvents.lua",
            crlf("-- The worlds Player_Agnostic_Plot.xml has a Zoom_Into_ event for.\nreturn {\n"
                 + "".join(f"\t[{lua_string(n)}] = true,\n" for n in names) + "}\n"))
    w.write("Data\\" + LISTENER + "init.lua", crlf(ZOOM_REQUIRE + init.replace(OLD_EVENT, NEW_EVENT)))
    w.write("Data\\" + LISTENER + "SelectedPlanetChangedEvent.lua",
            crlf(ZOOM_REQUIRE + event.replace(OLD_FLAG, NEW_FLAG)))


def merged_list(game, rel, closing, layer, extra):
    """A file list (GameObjectFiles.xml, ...) as the game would load it, with the entries of every installed version
    of it (the mod's and each submod's): a submod that replaces the list keeps its own files listed. The game skips
    listed files that aren't there."""
    text = game.read(rel, layer)
    if not text:
        return None
    entries = formats.file_list(game.read(rel, ()) or "")
    for s in game.submods:
        p = s["data"] / rel.replace("\\", "/")
        if p.exists():
            entries += formats.file_list(formats.decode(p.read_bytes()))
    return formats.add_files(text, closing, entries + extra)


def write_file_lists(game, layer, w, ids):
    entries = [(r"XML\CampaignFiles.xml", "</Campaign_Files>", [f"Conquests\\GalaxyMaps\\{i}.xml" for i in ids]),
               (r"XML\TradeRouteFiles.xml", "</Trade_Route_Files>", [f"GalaxyMaps\\TradeRoutes_{i}.xml" for i in ids]),
               (r"XML\GameObjectFiles.xml", "</Game_Object_Files>", [f"GalaxyMaps\\Planets_{i}.xml" for i in ids])]
    for rel, closing, files in entries:
        text = merged_list(game, rel, closing, layer, files)
        if text:
            w.write("Data\\" + rel, crlf(text))
    megs = [f"Data\\GalaxyMaps_{i}.meg" for i in ids]
    mega = merged_list(game, "MegaFiles.xml", "</Mega_Files>", layer, megs) if game.mod.get("data") else None
    if mega is None:
        mega = formats.add_files('<?xml version="1.0" ?>\n<Mega_Files>\n</Mega_Files>\n', "</Mega_Files>", megs)
    w.write(r"Data\MegaFiles.xml", crlf(mega))


# --- one map ---
class MapExport:
    def __init__(self, game, model, shared):
        self.game, self.model, self.d = game, model, model.data
        self.shared = shared                    # texts and planet changes of every map written
        if model.is_new:
            self.id = self.d["slot"]
            self.key = f"{self.d['template']}_{self.id}" if game.tr_menu else f"GM_{self.id}"
        else:
            self.id = self.key = self.d["map"]
        self.new_routes = {}
        self.notes = []

    def xml_name(self, world):
        p = self.model.planet(world)
        return p["name"] if p else world

    def route_name(self, pair):
        name = self.model.route_pairs.get(pair)
        if name:
            return name
        a, b = sorted(pair)
        name = f"GM_{self.id}_{self.xml_name(a)}_{self.xml_name(b)}"
        self.new_routes[name] = (self.xml_name(a), self.xml_name(b))
        return name

    def label(self, era):
        return self.game.date_label(era) if era else "Start"

    def edit_campaign(self, body, era, source_era):
        m = self.model
        worlds = m.worlds(era)
        hidden = [w for w in m.base[source_era].locations if w.upper() not in m.planets
                  and not m.planet(w)] if not m.data["blank"] else []
        names = hidden + [self.xml_name(w) for w in worlds]
        body = re.sub(r"<Locations>.*?</Locations>",
                      "<Locations>\n" + "".join(f"\t\t\t{n},\n" for n in names) + "</Locations>", body, count=1, flags=re.S)
        routes = sorted(self.route_name(p) for p in m.lanes(era))
        # (the game drops a lane list that is too long: lists of at most ROUTES_PER_LIST, as large maps have them)
        lists = "".join("<Trade_Routes>\n" + "".join(f"\t\t\t{r},\n" for r in routes[i:i + ROUTES_PER_LIST])
                        + "</Trade_Routes>\n\t\t" for i in range(0, max(len(routes), 1), ROUTES_PER_LIST)).rstrip()
        first = re.search(r"<Trade_Routes>.*?</Trade_Routes>", body, re.S)
        if first:
            body = body[:first.start()] + "\x00ROUTES\x00" + re.sub(r"\s*<Trade_Routes>.*?</Trade_Routes>", "",
                                                                    body[first.end():], flags=re.S)
            body = body.replace("\x00ROUTES\x00", lists)
        present = set(worlds)
        base = m.base[source_era].owners if not m.data["blank"] else {}
        lines, kept, era_dummies = [], set(), []
        matches = list(re.finditer(r"[ \t]*<Starting_Forces>\s*([^<]*?)\s*</Starting_Forces>[ \t]*\r?\n?", body))
        indent = re.match(r"[ \t]*", matches[0].group(0)).group(0) if matches else "\t\t"
        for match in matches:
            parts = [x.strip() for x in match.group(1).split(",")]
            if len(parts) < 3:
                continue
            faction, planet, unit = parts[0], parts[1], parts[2]
            p, u = planet.upper(), unit.upper()
            if u.startswith("ERA_") and u.endswith("_DUMMY"):
                if era and era != source_era:
                    unit = self.game.era_dummy(era)
                    if not unit:
                        continue
                if p not in present:
                    era_dummies.append(unit)
                    continue
            if p not in present:
                continue
            owner = m.owner(era, p)
            if owner.upper() != (base.get(p) or "").upper() and owner.upper() != faction.upper():
                if u == "GENERATE_FORCE":
                    faction = owner
                elif not ("DUMMY" in u or "MARKER" in u or u.startswith("CUSTOM_GC")):
                    self.notes.append(f"{self.label(era)}: {unit} ({faction}) left out at {m.display_name(p)}, which "
                                      f"now starts with {self.game.faction_label(owner)}.")
                    continue
            lines.append(f"{indent}<Starting_Forces>{faction}, {planet}, {unit}</Starting_Forces>\n")
            kept.add(p)
        for w in worlds:
            if w not in kept:
                lines.append(f"{indent}<Starting_Forces>{m.owner(era, w)}, {self.xml_name(w)}, Generate_Force"
                             "</Starting_Forces>\n")
        if era_dummies and worlds:
            first = worlds[0]
            for unit in era_dummies:
                lines.append(f"{indent}<Starting_Forces>{m.owner(era, first)}, {self.xml_name(first)}, {unit}"
                             "</Starting_Forces>\n")
        if matches:
            start = matches[0].start()
            out, last = [], 0
            for match in matches:
                out.append(body[last:match.start()])
                last = match.end()
            out.append(body[last:])
            rest = "".join(out)
            body = rest[:start] + "".join(lines) + rest[start:]
        else:
            i = body.rfind("</Trade_Routes>")
            i = body.find("\n", i) + 1
            body = body[:i] + "".join(lines) + body[i:]
        return body

    def blocks(self, era):
        """The campaigns of one start: (original match or None, new text)."""
        m = self.model
        source_era = m.nearest_base(era)
        c = m.base[source_era]
        base_key = self.d["template"] if m.is_new else self.d["map"]
        out = []
        for n, block in enumerate(c.blocks):
            name, body = block.group(1), block.group(2)
            body = self.edit_campaign(body, era, source_era)
            renamed = m.is_new or era != source_era
            if renamed:
                if self.game.tr_menu:
                    old = f"{base_key}_Era_{source_era}_" if source_era else f"{base_key}_"
                    new = f"{self.key}_Era_{era}_" if era else f"{self.key}_"
                    name = new + name[len(old):]
                    cset = f"{self.key}_Era_{era}" if era else self.key
                else:
                    name = f"{self.key}_{n + 1}"
                    cset = self.key
                    body = self.standard_texts(body)
                body = re.sub(r"<Campaign_Set>\s*[^<]*\s*</Campaign_Set>", f"<Campaign_Set>{cset}</Campaign_Set>",
                              body, count=1)
                if era:
                    body = re.sub(r"<Era_Start>\s*\d+\s*</Era_Start>", f"<Era_Start>{era}</Era_Start>", body, count=1)
                if m.is_new and self.d.get("year") and self.d["category"] == "Historical":
                    body = self.historical_year(body)
            out.append((None if renamed else block, f'<Campaign Name="{name}">{body}</Campaign>'))
        return out

    def standard_texts(self, body):
        title_key, desc_key = f"TEXT_GALAXYMAP_{self.id.upper()}_TITLE", f"TEXT_GALAXYMAP_{self.id.upper()}_DESCRIPTION"
        self.shared["texts"][title_key] = self.d.get("title") or self.key
        self.shared["texts"][desc_key] = self.d.get("description") or ""
        body = re.sub(r"<Text_ID>[^<]*</Text_ID>", f"<Text_ID>{title_key}</Text_ID>", body, count=1)
        body = re.sub(r"<Description_Text>[^<]*</Description_Text>", f"<Description_Text>{desc_key}</Description_Text>",
                      body, count=1)
        body = re.sub(r"<Is_Listed>[^<]*</Is_Listed>", "<Is_Listed>True</Is_Listed>", body, count=1)
        return body

    def historical_year(self, body):
        """A new historical map's own date: a copy of its story start script with the year changed."""
        year = self.d["year"]
        for container in re.findall(r"(Conquests\\[^,<]*?Container\.xml)", body):
            text = self.game.read("XML\\" + container, self.model.layer)
            if not text:
                continue
            for script in re.findall(r"<Lua_Script>\s*([^<\s]+)\s*</Lua_Script>", text):
                lua = self.game.read(f"Scripts\\Story\\{script}.lua", self.model.layer)
                if lua and re.search(r"year_start\s*=\s*[\d.]+", lua):
                    new_script = f"GalaxyMaps_{self.id}"
                    self.shared["files"][f"Data\\Scripts\\Story\\{new_script}.lua"] = crlf(
                        re.sub(r"(year_start\s*=\s*)[\d.]+", lambda mm: mm.group(1) + f"{year:g}", lua))
                    plots = f"Conquests\\GalaxyMaps\\{self.id}_Plots.xml"
                    self.shared["files"]["Data\\XML\\" + plots] = crlf(text.replace(
                        f"<Lua_Script>{script}</Lua_Script>", f"<Lua_Script>{new_script}</Lua_Script>"))
                    return body.replace(container, plots)
        self.notes.append("The start year could not be changed: the map's story keeps its own year.")
        return body

    def write_campaigns(self, w):
        m = self.model
        eras = m.ticked_eras() if not m.single else [0]
        new_blocks = []
        if m.is_new:
            for era in eras:
                new_blocks += [text for _, text in self.blocks(era)]
        else:
            by_file = {}
            for era in m.all_eras() if not m.single else [0]:
                if era not in m.base:
                    if era in eras:
                        new_blocks += [text for _, text in self.blocks(era)]
                    continue
                c = m.base[era]
                text = by_file.get(c.rel, c.text)
                for block, new in reversed(self.blocks(era)):
                    if block is not None and block.group(0) in text:
                        text = text.replace(block.group(0), new, 1)
                by_file[c.rel] = text
            for rel, text in by_file.items():
                w.write("Data\\" + rel, crlf(text))
        if new_blocks:
            w.write(f"Data\\XML\\Conquests\\GalaxyMaps\\{self.id}.xml",
                    crlf('<?xml version="1.0" ?>\n<Campaigns>\n\n' + "\n\n".join(new_blocks) + "\n\n</Campaigns>\n"))

    def era_lists(self):
        m = self.model
        eras = [e for e in m.ticked_eras() if e]
        keys = [self.game.date(e)["key"] for e in eras if self.game.date(e)]
        era_from = {self.game.date(e)["key"]: self.game.date(m.nearest_base(e))["key"]
                    for e in eras if e not in m.base and self.game.date(e) and self.game.date(m.nearest_base(e))}
        lua = "{" + ", ".join(lua_string(k) for k in keys) + "}"
        frm = "{" + ", ".join(f"[{lua_string(k)}] = {lua_string(v)}" for k, v in era_from.items()) + "}"
        return lua, frm, keys

    def write_menu(self, w):
        if not self.game.tr_menu:
            return
        m = self.model
        eras, era_from, keys = self.era_lists()
        if m.is_new:
            date = f"\tdate = {lua_string(format(self.d['year'], 'g') + ' ABY')},\n" if self.d.get("year") else ""
            w.write(f"Data\\Scripts\\Library\\GalaxyMaps\\{self.id}.lua", crlf(
                f"return {{\n\tkey = {lua_string(self.key)},\n\ttemplate = {lua_string(self.d['template'])},\n"
                f"\ttitle = {lua_string(self.d.get('title') or self.key)},\n"
                f"\tdescription = {lua_string(self.d.get('description') or '')},\n"
                f"\teras = {eras if not m.single else '{}'},\n\tera_from = {era_from},\n{date}"
                f"\tworlds = {m.world_count(m.ticked_eras()[0])},\n}}\n"))
            return
        base_keys = sorted(self.game.date(e)["key"] for e in m.base if e and self.game.date(e))
        changed_eras = not m.single and sorted(keys) != base_keys
        if changed_eras or self.d.get("button"):
            lines = [f"\tkey = {lua_string(self.key)},"]
            if changed_eras:
                lines += [f"\teras = {eras},", f"\tera_from = {era_from},"]
            if self.d.get("button"):
                lines += [f"\tbutton = {lua_string(self.d['button'])},", f"\ttitle = {lua_string(m.title)},",
                          f"\tworlds = {m.world_count(m.ticked_eras()[0])},"]
            w.write(f"Data\\Scripts\\Library\\GalaxyMaps\\Edit_{self.key}.lua", crlf("return {\n" + "\n".join(lines)
                                                                                  + "\n}\n"))

    def write_routes(self, w):
        if not self.new_routes:
            return
        blocks = [f'\t<TradeRoute Name="{n}">\n\t\t<Point_A>{a}</Point_A>\n\t\t<Point_B>{b}</Point_B>\n'
                  "\t\t<HS_Speed_Factor>1.0</HS_Speed_Factor>\n\t\t<Political_Control_Gain>0</Political_Control_Gain>\n"
                  "\t\t<Credit_Gain_Factor>0</Credit_Gain_Factor>\n\t\t<Visible_Line_Name>DEFAULT</Visible_Line_Name>\n"
                  "\t</TradeRoute>" for n, (a, b) in sorted(self.new_routes.items())]
        w.write(f"Data\\XML\\GalaxyMaps\\TradeRoutes_{self.id}.xml",
                crlf('<?xml version="1.0" ?>\n<TradeRoutes>\n' + "\n".join(blocks) + "\n</TradeRoutes>\n"))

    def collect_planets(self):
        """The map's changes to the mod's worlds go into the shared copies; its new worlds into a file of its own."""
        m = self.model
        for world, edit in self.d["planets"].items():
            base = m.planets.get(world)
            if base and edit:
                self.shared["planets"][world] = (m, edit)

    def write_new_planets(self, w):
        m = self.model
        used = set()
        for era in m.ticked_eras():
            used |= set(m.worlds(era))
        new = [n for n in self.d["new_planets"] if n in used]
        if not new:
            return
        whole = [p for p in self.game.planets(m.layer).values()
                 if "<Galactic_Position>" in p["body"] and "<Behavior>" in p["body"]]
        template = m.planets.get(PLANET_TEMPLATE.upper())
        if not template or template not in whole:
            template = whole[0] if whole else next(iter(m.planets.values()))
        blocks = []
        for world in new:
            p = m.planet(world)
            body = planet_body(template["body"], p, world, True, self.shared["texts"])
            blocks.append(f'\t<Planet Name="{p["name"]}">{body}</Planet>')
        w.write(f"Data\\XML\\GalaxyMaps\\Planets_{self.id}.xml",
                crlf('<?xml version="1.0" ?>\n<Planets>\n' + "\n\n".join(blocks) + "\n</Planets>\n"))

    def write_art(self, w):
        files = []
        art = self.model.folder / "Data" / "Art"
        for kind in ("Maps", "Models", "Textures"):
            folder = art / kind
            if folder.exists():
                for f in sorted(folder.iterdir()):
                    if f.is_file():
                        files.append((f"DATA\\ART\\{kind.upper()}\\{f.name.upper()}", f.read_bytes()))
                        w.write(f"Data/Art/{kind}/{f.name}", f.read_bytes())
        if files:
            w.write(f"Data\\GalaxyMaps_{self.id}.meg", formats.write_meg(files))


def text_key(world, tag):
    return f"TEXT_GALAXYMAP_{world.upper()}_{tag.upper()}"


def planet_body(body, p, world, new, texts, edit=None):
    """A world's definition with its changes (a new world: every field of its own)."""
    edit = p if new else (edit or {})
    if new or "pos" in edit:
        pos = p["pos"]
        z = pos[2] if len(pos) > 2 else 0
        body = formats.set_tag(body, "Galactic_Position", f"{pos[0]:g}, {pos[1]:g}, {z:g}")
    if new or "model" in edit:
        body = formats.set_tag(body, "Galactic_Model_Name", Path(p.get("model") or "").name)
    if new or "space" in edit:
        space = Path(p.get("space") or "").name
        body = formats.set_tag(body, "Space_Tactical_Map", space)
        body = formats.set_tag(body, "Destroyed_Space_Tactical_Map", space)
    if new or "land" in edit or "surface" in edit:
        body = formats.set_tag(body, "Land_Tactical_Map", Path(p.get("land") or "").name if p.get("surface") else "")
        body = formats.set_tag(body, "Planet_Surface_Accessible", " Yes " if p.get("surface") else " No ")
    for field, tag_name in (("land_slots", "Special_Structures_Land"), ("space_slots", "Special_Structures_Space"),
                            ("station", "Max_Space_Base")):
        if new or field in edit:
            body = formats.set_tag(body, tag_name, str(int(p.get(field) or 0)))
    if new or edit.get("display"):
        key = f"TEXT_GALAXYMAP_{world.upper()}"
        texts[key] = p.get("display") or world.replace("_", " ").title()
        body = formats.set_tag(body, "Text_ID", key)
    for tag_name, value in (edit.get("texts") or {}).items():
        key = text_key(world, tag_name)
        texts[key] = value
        body = formats.set_tag(body, "Describe_" + tag_name, key)
    if new:
        for tag_name in ("History", "Population", "Terrain", "Weather", "Wildlife", "Advantage", "Tactical"):
            if tag_name not in (edit.get("texts") or {}):
                key = text_key(world, tag_name)
                texts[key] = ""
                body = formats.set_tag(body, "Describe_" + tag_name, key)
        for tag_name in ("Encyclopedia_Text", "Planet_Ability_Name", "Planet_Ability_Description", "Native_Icon_Name",
                         "Encyclopedia_Weather_Icon", "Encyclopedia_Weather_Name", "Encyclopedia_Weather_Info"):
            body = formats.set_tag(body, tag_name, "")
    return body


def write_shared_planets(game, layer, w, shared):
    """The mod's planet files that hold changed worlds, whole, with every map's changes."""
    by_file = {}
    for world, (m, edit) in shared["planets"].items():
        by_file.setdefault(m.planets[world]["rel"], []).append((world, m, edit))
    for rel, items in by_file.items():
        text = game.read(rel, layer)
        if not text:
            continue
        for world, m, edit in items:
            base = m.planets[world]
            match = re.search(r'(<Planet\s+Name\s*=\s*"' + re.escape(base["name"]) + r'"\s*>)(.*?)(</Planet>)', text, re.S)
            if match:
                body = planet_body(match.group(2), m.planet(world), world, False, shared["texts"], edit)
                text = text[:match.start(2)] + body + text[match.end(2):]
        w.write("Data\\" + rel, crlf(text))


# --- the whole ---
def write_maps(game, models, folder, modinfo=None, installed=False):
    """Writes `models` into `folder` (a mod folder: Data\\ and modinfo.json). Returns (files written, notes).
    installed: for this PC (built over every installed submod); otherwise for upload (over those the maps need)."""
    folder = Path(folder)
    if (folder / "Data").exists():
        shutil.rmtree(folder / "Data")
    w = Writer(folder)
    layer = tuple(sorted({s for m in models for s in m.needed_submods()}))
    shared = {"texts": {}, "planets": {}, "files": {}}
    ids = (tr_buttons() if game.tr_menu else std_slots()) + [m["key"] for m in game.maps]
    if game.tr_menu:
        write_menu_support(game, layer, w)
    write_file_lists(game, layer, w, ids)
    notes = []
    for model in models:
        e = MapExport(game, model, shared)
        e.write_campaigns(w)
        e.write_menu(w)
        e.write_routes(w)
        e.collect_planets()
        e.write_new_planets(w)
        e.write_art(w)
        notes += [f"{model.title}: {n}" for n in e.notes]
    write_shared_planets(game, layer, w, shared)
    for rel, text in shared["files"].items():
        w.write(rel, text)
    if shared["texts"]:
        base = game.base_dat(layer)
        if base:
            texts = formats.read_dat(base)
            texts.update(shared["texts"])
            w.write(r"Data\Text\MasterTextFile_ENGLISH.dat", formats.write_dat(texts))
    if modinfo:
        w.write("modinfo.json", json.dumps(modinfo, indent=2))
    return w.count, list(dict.fromkeys(notes))


def dependencies(game, models):
    """The Workshop items the maps need: the mod and the submods their worlds come from."""
    ids = []
    if game.mod["kind"] == "workshop":
        ids.append(game.mod["id"])
    for m in models:
        for s in m.needed_submods():
            if s not in ids and s.isdigit():
                ids.insert(0, s)
    return ids


def export_mod(game, model, folder):
    deps = dependencies(game, [model])
    info = {"name": model.title, "summary": model.data.get("description") or "",
            "dependencies": [{"modtype": 1, "identifier": i} for i in deps]}
    return write_maps(game, [model], folder, info)


def launch_line(game, models, folder_name):
    parts = [f"MODPATH=Mods\\{folder_name}"]
    for i in dependencies(game, models):
        parts.append(f"STEAMMOD={i}")
    return " ".join(parts)
