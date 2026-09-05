#!/usr/bin/env python3
"""Local web server for pairwise Nerd Font ranking."""

from __future__ import annotations

import argparse
import json
import math
import os
import queue
import random
import re
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
FONT_DIR = ROOT / "fonts"
RANKINGS_FILE = DATA_DIR / "rankings.json"
CATALOG_FILE = DATA_DIR / "catalog.json"
LATEST_RELEASE_API = "https://api.github.com/repos/ryanoasis/nerd-fonts/releases/latest"
USER_AGENT = "FontRanker/1.0 (+https://www.nerdfonts.com/font-downloads)"

FALLBACK_FONTS = """
0xProto 3270 AdwaitaMono Agave AnnotationMono AnonymousPro Arimo
AtkinsonHyperlegibleMono AurulentSansMono BigBlueTerminal BitstreamVeraSansMono
CascadiaCode CascadiaMono CodeNewRoman ComicShannsMono CommitMono Cousine D2Coding
DaddyTimeMono DejaVuSansMono DepartureMono DroidSansMono EnvyCodeR FantasqueSansMono
FiraCode FiraMono GeistMono Go-Mono Gohu GoogleSansCode Hack Hasklig HeavyData Hermit
iA-Writer IBMPlexMono Inconsolata InconsolataGo InconsolataLGC IntelOneMono Iosevka
IosevkaTerm IosevkaTermSlab JetBrainsMono Lekton LiberationMono Lilex MartianMono
Meslo Monaspace Monofur Monoid Mononoki MPlus Noto OpenDyslexic Overpass ProFont
ProggyClean Recursive RobotoMono ShareTechMono SourceCodePro SpaceMono Terminus Tinos
Ubuntu UbuntuMono UbuntuSans VictorMono ZedMono
""".split()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def display_name(identifier: str) -> str:
    special = {
        "0xProto": "0xProto", "3270": "IBM 3270", "IBMPlexMono": "IBM Plex Mono",
        "Go-Mono": "Go Mono", "iA-Writer": "iA Writer", "MPlus": "M+",
    }
    if identifier in special:
        return special[identifier]
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", identifier)


def fallback_catalog() -> dict:
    version = "v3.5.1"
    return {
        "version": version,
        "fetchedAt": utc_now(),
        "source": "bundled fallback",
        "fonts": [
            {
                "id": item,
                "name": display_name(item),
                "downloadUrl": f"https://github.com/ryanoasis/nerd-fonts/releases/download/{version}/{item}.zip",
            }
            for item in FALLBACK_FONTS
        ],
    }


def fetch_catalog() -> dict:
    request = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        release = json.load(response)
    fonts = []
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if not name.endswith(".zip"):
            continue
        identifier = name[:-4]
        if identifier in {"FontPatcher", "NerdFontsSymbolsOnly"}:
            continue
        fonts.append({
            "id": identifier,
            "name": display_name(identifier),
            "downloadUrl": asset["browser_download_url"],
        })
    if len(fonts) < 2:
        raise RuntimeError("GitHub release did not contain a usable font catalog")
    return {
        "version": release.get("tag_name", "latest"),
        "fetchedAt": utc_now(),
        "source": LATEST_RELEASE_API,
        "fonts": sorted(fonts, key=lambda font: font["name"].casefold()),
    }


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temp, path)


def load_catalog(refresh: bool = True) -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cached = None
    if CATALOG_FILE.exists():
        try:
            cached = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    if refresh:
        try:
            catalog = fetch_catalog()
            write_json_atomic(CATALOG_FILE, catalog)
            return catalog
        except (OSError, RuntimeError, urllib.error.URLError):
            pass
    return cached or fallback_catalog()


class RankStore:
    def __init__(self, path: Path, catalog: dict):
        self.path = path
        self.catalog = catalog
        self.lock = threading.RLock()
        self.state = self._load()

    def _load(self) -> dict:
        state = None
        if self.path.exists():
            try:
                state = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        if not state:
            state = {"schemaVersion": 1, "totalVotes": 0, "fonts": {}, "history": []}
        state.setdefault("history", [])
        state.setdefault("pairCounts", {})
        if not state["history"] and state.get("totalVotes") == 1:
            winners = [key for key, value in state.get("fonts", {}).items() if value.get("wins") == 1 and value.get("comparisons") == 1]
            losers = [key for key, value in state.get("fonts", {}).items() if value.get("losses") == 1 and value.get("comparisons") == 1]
            if len(winners) == 1 and len(losers) == 1:
                state["history"].append({
                    "winner": winners[0], "loser": losers[0],
                    "pair": [winners[0], losers[0]],
                    "winnerRatingBefore": 1000.0, "loserRatingBefore": 1000.0,
                    "votedAt": state.get("updatedAt", utc_now()),
                    "migrated": True,
                })
        if not state["pairCounts"] and state["history"]:
            for vote in state["history"]:
                key = self.pair_key(vote["winner"], vote["loser"])
                state["pairCounts"][key] = state["pairCounts"].get(key, 0) + 1
        state["catalogVersion"] = self.catalog["version"]
        valid_ids = {font["id"] for font in self.catalog["fonts"]}
        state["fonts"] = {
            key: value for key, value in state.get("fonts", {}).items() if key in valid_ids
        }
        for font in self.catalog["fonts"]:
            state["fonts"].setdefault(font["id"], {
                "name": font["name"], "rating": 1000.0, "wins": 0,
                "losses": 0, "comparisons": 0,
            })
            state["fonts"][font["id"]]["name"] = font["name"]
        self._save_state(state)
        return state

    @staticmethod
    def _ranked(state: dict) -> list[dict]:
        rows = [dict(id=identifier, **stats) for identifier, stats in state["fonts"].items()]
        rows.sort(key=lambda row: (-row["rating"], -row["wins"], row["name"].casefold()))
        for index, row in enumerate(rows, 1):
            row["rank"] = index
        return rows

    @staticmethod
    def pair_key(first: str, second: str) -> str:
        return "::".join(sorted((first, second)))

    def priority_pair(self, excluded: set[frozenset[str]] | None = None) -> list[str]:
        """Choose the comparison that adds the most useful ordering information."""
        excluded = excluded or set()
        with self.lock:
            ranked = self._ranked(self.state)
            unseen = [row for row in ranked if row["comparisons"] == 0]
            seen = [row for row in ranked if row["comparisons"] > 0]
            candidates: list[tuple[tuple, list[str]]] = []

            if unseen and seen:
                # Connect each unseen font to the established ranking, spreading
                # anchors across the table when several matchups are prefetched.
                for index, contender in enumerate(unseen):
                    anchor_index = round(index * (len(seen) - 1) / max(1, len(unseen) - 1))
                    anchor = seen[anchor_index]
                    pair = [contender["id"], anchor["id"]]
                    candidates.append(((contender["name"].casefold(),), pair))
            elif len(unseen) >= 2:
                for index in range(len(unseen) - 1):
                    pair = [unseen[index]["id"], unseen[index + 1]["id"]]
                    candidates.append(((index,), pair))
            else:
                # Once every font is connected, compare adjacent standings with
                # the least head-to-head evidence first.
                for index in range(len(ranked) - 1):
                    first, second = ranked[index], ranked[index + 1]
                    pair = [first["id"], second["id"]]
                    count = self.state["pairCounts"].get(self.pair_key(*pair), 0)
                    evidence = first["comparisons"] + second["comparisons"]
                    candidates.append(((count, evidence, index), pair))

            candidates.sort(key=lambda item: item[0])
            for _, pair in candidates:
                if frozenset(pair) not in excluded:
                    if random.SystemRandom().randrange(2):
                        pair.reverse()
                    return pair

            # A full prefetch buffer can reserve all top-priority adjacent pairs.
            # Fall back to the closest-rated unreserved pair.
            fallbacks = []
            for first_index, first in enumerate(ranked):
                for second in ranked[first_index + 1:]:
                    pair = [first["id"], second["id"]]
                    if frozenset(pair) not in excluded:
                        fallbacks.append((abs(first["rating"] - second["rating"]), pair))
            if not fallbacks:
                raise RuntimeError("No font pair is available")
            pair = min(fallbacks, key=lambda item: item[0])[1]
            if random.SystemRandom().randrange(2):
                pair.reverse()
            return pair

    def _save_state(self, state: dict) -> None:
        state["updatedAt"] = utc_now()
        state["ranking"] = self._ranked(state)
        write_json_atomic(self.path, state)

    def public_state(self) -> dict:
        with self.lock:
            return {
                "catalogVersion": self.state["catalogVersion"],
                "totalVotes": self.state["totalVotes"],
                "updatedAt": self.state["updatedAt"],
                "ranking": self._ranked(self.state),
            }

    def vote(self, winner: str, loser: str, pair: list[str] | None = None) -> dict:
        with self.lock:
            if winner == loser or winner not in self.state["fonts"] or loser not in self.state["fonts"]:
                raise ValueError("Vote must contain two different catalog font IDs")
            if pair is None:
                pair = [winner, loser]
            if len(pair) != 2 or set(pair) != {winner, loser}:
                raise ValueError("Pair must match the two voted font IDs")
            winner_stats = self.state["fonts"][winner]
            loser_stats = self.state["fonts"][loser]
            self.state["history"].append({
                "winner": winner,
                "loser": loser,
                "pair": pair,
                "winnerRatingBefore": winner_stats["rating"],
                "loserRatingBefore": loser_stats["rating"],
                "votedAt": utc_now(),
            })
            key = self.pair_key(winner, loser)
            self.state["pairCounts"][key] = self.state["pairCounts"].get(key, 0) + 1
            expected_winner = 1 / (1 + math.pow(10, (loser_stats["rating"] - winner_stats["rating"]) / 400))
            change = 32 * (1 - expected_winner)
            winner_stats["rating"] = round(winner_stats["rating"] + change, 2)
            loser_stats["rating"] = round(loser_stats["rating"] - change, 2)
            winner_stats["wins"] += 1
            loser_stats["losses"] += 1
            winner_stats["comparisons"] += 1
            loser_stats["comparisons"] += 1
            self.state["totalVotes"] += 1
            self._save_state(self.state)
            return self.public_state()

    def undo(self) -> tuple[dict, list[str]]:
        with self.lock:
            if not self.state["history"]:
                raise ValueError("There is no previous vote to revisit")
            vote = self.state["history"].pop()
            winner_stats = self.state["fonts"][vote["winner"]]
            loser_stats = self.state["fonts"][vote["loser"]]
            winner_stats["rating"] = vote["winnerRatingBefore"]
            loser_stats["rating"] = vote["loserRatingBefore"]
            winner_stats["wins"] -= 1
            loser_stats["losses"] -= 1
            winner_stats["comparisons"] -= 1
            loser_stats["comparisons"] -= 1
            key = self.pair_key(vote["winner"], vote["loser"])
            self.state["pairCounts"][key] = max(0, self.state["pairCounts"].get(key, 1) - 1)
            if self.state["pairCounts"][key] == 0:
                del self.state["pairCounts"][key]
            self.state["totalVotes"] -= 1
            self._save_state(self.state)
            return self.public_state(), vote.get("pair", [vote["winner"], vote["loser"]])


def choose_font_member(archive: zipfile.ZipFile) -> str:
    candidates = [
        info.filename for info in archive.infolist()
        if not info.is_dir() and info.filename.lower().endswith((".ttf", ".otf"))
    ]
    if not candidates:
        raise RuntimeError("Font archive contains no TTF or OTF files")

    def score(filename: str) -> tuple[int, int, str]:
        lower = filename.lower()
        value = 0
        value += 80 if "nerdfontmono" in lower else 0
        value += 35 if "regular" in lower else 0
        value += 12 if "medium" in lower else 0
        value -= 80 if any(word in lower for word in ("italic", "bold", "light", "thin", "semibold")) else 0
        value -= 35 if "variable" in lower else 0
        value -= 15 if "windows compatible" in lower else 0
        return (-value, len(filename), filename)

    return min(candidates, key=score)


class FontCache:
    def __init__(self, directory: Path, catalog: dict):
        self.directory = directory
        self.fonts = {font["id"]: font for font in catalog["fonts"]}
        self.locks: dict[str, threading.Lock] = {}
        self.locks_guard = threading.Lock()

    def lock_for(self, identifier: str) -> threading.Lock:
        with self.locks_guard:
            return self.locks.setdefault(identifier, threading.Lock())

    def ensure(self, identifier: str) -> tuple[Path, str]:
        if identifier not in self.fonts:
            raise ValueError("Unknown font")
        destination_dir = self.directory / identifier
        metadata_path = destination_dir / "metadata.json"
        with self.lock_for(identifier):
            if metadata_path.exists():
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                cached = destination_dir / metadata["file"]
                if cached.exists():
                    return cached, metadata["format"]
            destination_dir.mkdir(parents=True, exist_ok=True)
            request = urllib.request.Request(self.fonts[identifier]["downloadUrl"], headers={"User-Agent": USER_AGENT})
            with tempfile.NamedTemporaryFile(suffix=".zip") as temp:
                with urllib.request.urlopen(request, timeout=120) as response:
                    shutil.copyfileobj(response, temp)
                temp.flush()
                with zipfile.ZipFile(temp.name) as archive:
                    member = choose_font_member(archive)
                    extension = Path(member).suffix.lower()
                    output = destination_dir / f"font{extension}"
                    with archive.open(member) as source, output.open("wb") as target:
                        shutil.copyfileobj(source, target)
            font_format = "truetype" if extension == ".ttf" else "opentype"
            write_json_atomic(metadata_path, {
                "file": output.name,
                "format": font_format,
                "source": self.fonts[identifier]["downloadUrl"],
                "archiveMember": member,
                "downloadedAt": utc_now(),
            })
            return output, font_format


CATALOG = load_catalog()
STORE = RankStore(RANKINGS_FILE, CATALOG)
CACHE = FontCache(FONT_DIR, CATALOG)
LAST_PAIR: frozenset[str] = frozenset()


def prepare_pair(identifiers: list[str]) -> list[dict]:
    catalog_by_id = {font["id"]: font for font in CATALOG["fonts"]}
    result = []
    for identifier in identifiers:
        font = catalog_by_id[identifier]
        font_path, font_format = CACHE.ensure(identifier)
        result.append({
            "id": identifier,
            "name": font["name"],
            "fontUrl": f"/fonts/{identifier}/{font_path.name}",
            "format": font_format,
        })
    return result


class PairPrefetcher:
    """Keep a small queue of fully downloaded matchups ready to display."""

    def __init__(self, store: RankStore, buffer_size: int = 3, workers: int = 2):
        self.store = store
        self.ready: queue.Queue[list[dict]] = queue.Queue(maxsize=buffer_size)
        self.reserved: set[frozenset[str]] = set()
        self.recent: set[frozenset[str]] = set()
        self.reservation_lock = threading.Lock()
        for index in range(workers):
            thread = threading.Thread(
                target=self._worker,
                name=f"font-prefetch-{index + 1}",
                daemon=True,
            )
            thread.start()

    def _worker(self) -> None:
        while True:
            with self.reservation_lock:
                identifiers = self.store.priority_pair(self.reserved | self.recent)
                key = frozenset(identifiers)
                self.reserved.add(key)
            try:
                pair = prepare_pair(identifiers)
                self.ready.put(pair)
            except Exception as error:
                with self.reservation_lock:
                    self.reserved.discard(key)
                print(f"Background font download failed: {error}")
                time.sleep(2)

    def next_pair(self) -> list[dict]:
        pair = self.ready.get(timeout=180)
        key = frozenset(font["id"] for font in pair)
        with self.reservation_lock:
            self.reserved.discard(key)
            self.recent = {key}
        return pair


PREFETCHER: PairPrefetcher | None = None


class Handler(BaseHTTPRequestHandler):
    server_version = "FontRanker/1.0"

    def log_message(self, message: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {message % args}")

    def json_response(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def file_response(self, path: Path, content_type: str, cache: bool = False) -> None:
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=31536000, immutable" if cache else "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        global LAST_PAIR
        path = unquote(urlparse(self.path).path)
        if path == "/api/state":
            self.json_response(STORE.public_state())
            return
        if path == "/api/pair":
            try:
                if PREFETCHER is None:
                    raise RuntimeError("Font prefetcher is not running")
                pair = PREFETCHER.next_pair()
                for _ in range(8):
                    if frozenset(font["id"] for font in pair) != LAST_PAIR:
                        break
                    pair = PREFETCHER.next_pair()
                LAST_PAIR = frozenset(font["id"] for font in pair)
                self.json_response({"pair": pair})
            except Exception as error:
                self.json_response({"error": str(error)}, 502)
            return
        match = re.fullmatch(r"/fonts/([A-Za-z0-9+_-]+)/font\.(ttf|otf)", path)
        if match:
            identifier, extension = match.groups()
            if identifier not in CACHE.fonts:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content_type = "font/ttf" if extension == "ttf" else "font/otf"
            self.file_response(FONT_DIR / identifier / f"font.{extension}", content_type, cache=True)
            return
        static = {
            "/": (ROOT / "index.html", "text/html; charset=utf-8"),
            "/index.html": (ROOT / "index.html", "text/html; charset=utf-8"),
            "/styles.css": (ROOT / "styles.css", "text/css; charset=utf-8"),
            "/app.js": (ROOT / "app.js", "text/javascript; charset=utf-8"),
            "/snippet.c": (ROOT / "snippet.c", "text/plain; charset=utf-8"),
        }
        if path in static:
            self.file_response(*static[path])
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/undo":
            try:
                state, identifiers = STORE.undo()
                self.json_response({"state": state, "pair": prepare_pair(identifiers)})
            except ValueError as error:
                self.json_response({"error": str(error)}, 409)
            except Exception as error:
                self.json_response({"error": str(error)}, 502)
            return
        if path != "/api/vote":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 4096:
                raise ValueError("Invalid request size")
            payload = json.loads(self.rfile.read(length))
            self.json_response(STORE.vote(payload.get("winner"), payload.get("loser"), payload.get("pair")))
        except (ValueError, json.JSONDecodeError) as error:
            self.json_response({"error": str(error)}, 400)


def main() -> None:
    global PREFETCHER
    parser = argparse.ArgumentParser(description="Run Font Ranker locally")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    PREFETCHER = PairPrefetcher(STORE)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Font Ranker is running at http://{args.host}:{args.port}")
    print(f"Votes are saved to {RANKINGS_FILE}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Font Ranker.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
