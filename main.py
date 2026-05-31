#!/usr/bin/env python3

import asyncio
import json
import webbrowser
from dataclasses import dataclass, field
from math import floor
from os import environ
from os.path import exists
from sys import argv
from time import time
from urllib.parse import quote
from urllib.request import Request, urlopen

import cv2
import numpy as np
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader
from PIL import ImageGrab
from playwright.async_api import Playwright, async_playwright
from pytesseract import image_to_string

NECC_PREFIX = "https://necc.leagueos.gg/match/"
NECC_V1_PREFIX = "https://necc.v1.leagueos.gg/league/matches/"
PCL_PREFIX = "https://esports.pcl.gg/matches/"
PCL_ROLE_COACH = "6f4da22c-7fe5-4c78-8876-eec2c87d1096"

hero_cache: dict[str, str] = {}


@dataclass
class Rank:
    name: str
    icon: str


@dataclass
class Hero:
    name: str
    wins: int = 0
    total: int = 0

    def win(self):
        self.wins += 1
        self.total += 1

    def lose(self):
        self.total += 1


@dataclass
class Player:
    name: str
    current: Rank | None = None
    peak: Rank | None = None
    heroes: list[tuple[int, Hero]] = field(default_factory=list)
    private: bool = False


def js_hash(s: str) -> int:
    h = 0
    for c in s:
        h = ((h << 5) - h + ord(c)) & ((1 << 32) - 1)
        if h & (1 << 31):
            h -= 1 << 32
    return h


def input_team() -> int:
    while True:
        match input("which team (l/r)? ").lower():
            case "l":
                return 0
            case "r":
                return 1
            case _:
                print("please input 'l' or 'r'")


def ocr(img: cv2.typing.MatLike) -> list[str]:
    blur = cv2.GaussianBlur(img, (3, 3), 0)
    cv2.addWeighted(img, 1.5, blur, -0.5, 0, img)
    mask = cv2.inRange(img, np.array([110, 9, 150]), np.array([140, 28, 220]))
    img = cv2.bitwise_and(img, img, mask=mask)
    cv2.cvtColor(img, cv2.COLOR_HSV2RGB, img)
    return [
        line[line.find(" "):].strip()
        for line in image_to_string(img).splitlines()
        if " " in line
    ]


def necc(match_id: str) -> list[str]:
    sid = environ["LOS_SID"]
    team_idx = input_team()

    aid = "los-league"
    did = js_hash("necc.leagueos.gg")
    ct = floor(time())
    headers = {
        "user-agent": "Mozilla/5.0",
        "x-leagueos-aid": aid,
        "x-leagueos-did": str(did),
        "x-leagueos-rid": str(js_hash(f"{ct - ct % 10}{did}{aid}")),
    }

    req = Request("https://api2.leagueos.gg/los/domains?hostname=necc.leagueos.gg", headers=headers)
    headers["x-leagueos-lid"] = json.load(urlopen(req))["data"]["leagueId"]
    headers["x-leagueos-sid"] = sid

    req = Request(f"https://api2.leagueos.gg/los/matches/{match_id}", headers=headers)
    data = json.load(urlopen(req))["data"]
    team_id = data["teamIds"][team_idx]
    roster = next(r for r in data["rosters"].values() if team_id in r["permissions"])

    names = []
    for user in roster["members"].values():
        if not user["roles"] & 1 << 20:
            continue
        if "marvelRivals" in user["connections"]:
            for acc in user["connections"]["marvelRivals"]["accounts"]:
                names.append(acc["name"])
        else:
            print(f"no account found for {user['leagueTag']}")

    return names


def pcl(url: str) -> list[str]:
    token = environ["PCL_TOKEN"]
    team_idx = input_team()

    league_id = json.load(urlopen(
        f"https://api.leaguespot.gg/api/v1/leagues/byUrl?url={quote(url)}"
    ))["league"]["id"]

    req = Request(
        f"https://api.leaguespot.gg/api/v1/matches/{url.removeprefix(PCL_PREFIX)}/participants",
        headers={"Authorization": f"Bearer {token}", "X-League-Id": league_id},
    )
    names = []
    for user in json.load(urlopen(req))[team_idx]["users"]:
        if user["teamRoleId"] == PCL_ROLE_COACH:
            continue
        name = user["gameHandle"]["handle"]
        if name is None:
            print(f"no account found for {user['gamerHandle']}")
        else:
            names.append(name)
    return names


async def tracker(pw: Playwright, name: str) -> Player | None:
    def make_rank(stat: dict) -> Rank:
        meta = stat["metadata"]
        return Rank(meta["tierShortName"], meta["iconUrl"])

    browser = await pw.firefox.launch()
    page = await (await browser.new_context()).new_page()
    quoted = quote(name, safe="")

    await page.goto(f"https://api.tracker.gg/api/v2/marvel-rivals/standard/profile/ign/{quoted}")
    resp = json.loads(await page.locator("pre").inner_html(timeout=2000))

    if "errors" in resp:
        for err in resp["errors"]:
            if err["code"] == "CollectorResultStatus::Private":
                return Player(name, private=True)
        print(f"failed to load {name}")
        return None

    data = resp["data"]
    segments = data["segments"]
    current = make_rank(segments[0]["stats"]["ranked"])
    player = Player(
        data["platformInfo"]["platformUserIdentifier"],
        current=current,
        peak=make_rank(segments[1]["stats"]["lifetimePeakRanked"]) if len(segments) > 1 else current,
    )

    await page.goto(
        f"https://api.tracker.gg/api/v2/marvel-rivals/standard/matches/ign/{quoted}?mode=competitive"
    )
    resp = json.loads(await page.locator("pre").inner_html(timeout=2000))

    if "errors" in resp:
        player.private = True
        return player

    stats: dict[str, Hero] = {}
    for match in resp["data"]["matches"]:
        meta = match["segments"][0]["metadata"]
        if not meta["heroes"]:
            continue
        hero = meta["heroes"][0]
        hero_id = hero["heroId"]
        if hero_id not in stats:
            stats[hero_id] = Hero(hero["name"])
        match meta["result"]:
            case "win":
                stats[hero_id].win()
            case "loss":
                stats[hero_id].lose()

    player.heroes = sorted(stats.items(), key=lambda item: item[1].total, reverse=True)
    return player


async def rivalsmeta(pw: Playwright, player: Player) -> Player:
    headers = {"Content-Type": "Application/json", "User-Agent": "Mozilla/5.0"}

    # TODO: find a more stable name-to-uid api
    req = Request(
        url="https://rivalsmeta.com/api/find-player",
        data=json.dumps({"name": player.name}).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    lower = player.name.lower()
    uid = None
    for _ in range(10):
        found = next((u for u in json.load(urlopen(req)) if u["name"].lower() == lower), None)
        if found is not None:
            player.name = found["name"]
            uid = found["aid"]
            break
        await asyncio.sleep(0.2)

    if uid is None:
        print(f"failed to find {player.name}")
        return player

    req = Request(
        url=f"https://rivalsmeta.com/api/player-match-history/{uid}?game_mode_id=2&hero_id=0",
        headers=headers,
    )
    stats: dict[int, Hero] = {}
    for match in json.load(urlopen(req)):
        hero_id = match["match_player"]["player_hero"]["hero_id"]
        if hero_id not in stats:
            stats[hero_id] = Hero(await get_hero_name(pw, hero_id))
        if match["match_player"]["is_win"]:
            stats[hero_id].win()
        else:
            stats[hero_id].lose()

    player.heroes = sorted(stats.items(), key=lambda item: item[1].total, reverse=True)
    return player


async def get_hero_name(pw: Playwright, hero_id: int) -> str:
    if not hero_cache:
        browser = await pw.firefox.launch()
        page = await (await browser.new_context()).new_page()
        await page.goto("https://api.tracker.gg/api/v1/marvel-rivals/metadata/type/hero")
        resp = json.loads(await page.locator("pre").inner_html(timeout=2000))
        for hero in resp["data"]["items"]:
            hero_cache[hero["key"]] = hero["name"]
    return hero_cache[str(hero_id)]


async def get_player(pw: Playwright, name: str) -> Player | None:
    player = await tracker(pw, name)
    if player and player.private:
        player = await rivalsmeta(pw, player)
    if player and (player.current or player.peak or player.heroes):
        return player
    return None


async def main(names: list[str], share: bool):
    async with async_playwright() as pw:
        results = await asyncio.gather(*[get_player(pw, name) for name in names])
        players = [p for p in results if p is not None]

        rendered = Environment(loader=FileSystemLoader(".")).get_template("tmpl.html").render(players=players)
        with open("index.html", "w") as f:
            f.write(rendered)
            print("saved to index.html")

        if share:
            browser = await pw.firefox.launch()
            page = await (await browser.new_context()).new_page()
            await page.goto("https://jsbin.com")
            await page.evaluate(f"jsbin.panels.panels.html.setCode({json.dumps(rendered)});")
            await page.evaluate('document.getElementsByClassName("save")[0].click();')
            await page.wait_for_url("https://jsbin.com/**/edit*")
            webbrowser.open(page.url.rsplit("/", 1)[0])
        else:
            webbrowser.open("index.html")


def parse_args() -> tuple[list[str], bool]:
    args = argv[1:]
    share = False

    if args and args[0] == "share":
        share = True
        args = args[1:]

    if len(args) == 1 and exists(args[0]):
        img = cv2.imread(args[0])
        assert img is not None
        cv2.cvtColor(img, cv2.COLOR_BGR2HSV, img)
        names = ocr(img)
    elif len(args) == 1 and args[0].startswith((NECC_PREFIX, NECC_V1_PREFIX)):
        match_id = args[0].removeprefix(NECC_PREFIX).removeprefix(NECC_V1_PREFIX)
        names = necc(match_id)
    elif len(args) == 1 and args[0].startswith(PCL_PREFIX):
        names = pcl(args[0])
    elif args:
        names = list(args)
    else:
        names = ocr(cv2.cvtColor(np.array(ImageGrab.grabclipboard()), cv2.COLOR_RGB2HSV))

    return names, share


if __name__ == "__main__":
    load_dotenv()
    names, share = parse_args()
    print("players:", ", ".join(names))
    asyncio.run(main(names, share))