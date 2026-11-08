# Galaxy Map Editor

A map editor for the galactic conquest maps of Star Wars: Empire at War, Forces of Corruption and their mods.
Edit ownership, hyperlanes and planets, make new maps, and export them as a mod for the Steam Workshop.

The ready-to-use program is on Nexus Mods. See "How to use.txt" for how to use the editor.

## Files

| File | What it does |
|---|---|
| `app.py` | The windows and tools (start here) |
| `gamedata.py` | Finds the game and installed mods and reads their maps, worlds and files |
| `project.py` | Your saved maps and every edit made to them |
| `export.py` | Writes maps into a mod folder the game can load |
| `formats.py` | Reads and writes the game's file formats (.meg archives, .dat texts, XML, Lua tables) |
| `make_icon.py` | Draws `editor.ico` |
| `GalaxyMapEditor.spec` | PyInstaller recipe for the release build |

## Running from source

Needs Windows and Python 3 (the release is built with Python 3.13).

    pip install -r requirements.txt
    python app.py

## Building the release

    python -m PyInstaller --noconfirm GalaxyMapEditor.spec

The program is written to `dist\Galaxy Map Editor`. Copy `How to use.txt` into it and zip the folder.
