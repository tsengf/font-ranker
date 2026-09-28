# Glyph Fight

Glyph Fight is a local, keyboard-first web app for ranking the programming fonts
listed by [Nerd Fonts](https://www.nerdfonts.com/font-downloads). It presents the
same code in two prioritized contenders and maintains an Elo leaderboard from
your choices.

## Start the server

Requires Python 3.10 or newer. No packages need to be installed.

From a terminal, change into the project directory and start the server:

```bash
cd font-ranker
npm start
```

Then open <http://127.0.0.1:8787> in a browser. Leave the terminal running while
you use the app. Press `Ctrl-C` in that terminal to stop the server; run
`npm start` again to restart it.

You can also start it directly with Python:

```bash
python3 server.py
```

Vote with `1` / `2` or the left / right arrow keys. Press `P` to pass on a
matchup without changing any ratings. Press `U` to undo the most recent vote,
restore that exact matchup, and rank it again. Code starts at 12 px and keeps its
size when the browser window changes. Enter a code font size in pixels,
or use `+` / `=` to enlarge it and `-` to reduce it while retaining the visible
line. Drag the grip below both code windows to resize the previews, or focus it
and use the up/down arrow keys.

Contender names are hidden by default to reduce bias. Press `T` to show or hide
both names across matchups.

The latest Nerd Fonts release catalog is fetched at startup. Each matchup
downloads only the missing font archives, extracts a regular monospace variant,
and caches it under `fonts/`. Rankings are written atomically after every vote to
`data/rankings.json`, so progress survives server and browser restarts.

Two background workers keep a bounded queue of three downloaded matchups ready,
reducing the wait between choices without downloading the entire catalog at once.

Matchups are scheduled to establish a total order efficiently: unseen fonts are
connected to the existing standings first, then adjacent fonts with the least
head-to-head evidence are prioritized. Left/right placement remains randomized.

Edit `snippet.c` to change the shared comparison sample. The page checks it for
changes every 1.5 seconds and before every matchup, so saved edits appear without
a browser or server restart.

Both panes use C-aware syntax colors and synchronize their vertical and
horizontal scroll positions in either direction. The vertical position is
retained when moving to the next matchup.

## Tests

```bash
python3 -m unittest discover -s tests -v
```
