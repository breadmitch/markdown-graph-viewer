# Markdown Graph Viewer

A standalone local GUI that visualizes relationships between ordinary Markdown/text files.


It simply opens a folder, scans files, and draws a graph from links and tags.

## Run

```bash
python md_graph_gui.py
```

Or open a folder directly:

```bash
python md_graph_gui.py "C:\path\to\your\markdown-folder"
```

On Windows you can use:

```text
run_windows.bat
```

## What it reads

File types:

- `.md`
- `.markdown`
- `.txt`

Relationships:

- Wiki-style links: `[[Some Note]]`
- Markdown links: `[Some Note](some-note.md)`
- Tags: `#project`, `#person/jane`, `#idea`
- Optional unresolved link nodes
- Optional external URL nodes

## Features

- Local desktop GUI
- Folder picker
- Force-directed graph
- Zoom, pan, drag nodes
- Pin/unpin nodes
- Search/filter
- Local graph mode with depth control
- Hide isolated files
- File preview panel
- Connection list
- Read-only file scanning

## Notes

This is a first standalone version designed to be easy to package later with PyInstaller:

```bash
pyinstaller --onefile --windowed md_graph_gui.py
```

No third-party Python packages are required.
