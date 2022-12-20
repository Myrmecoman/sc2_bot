# pylint: disable=E0401
import sys

from __init__ import run_ladder_game

# Load bot
from bot import SmoothBrainBot
from training_bots.pool12_allin import Pool12AllIn
from training_bots.worker_rush import WorkerRushBot

from sc2 import maps
from sc2.data import Difficulty, Race
from sc2.main import run_game
from sc2.player import Bot, Computer

map_names = ["AcropolisLE", "DiscoBloodbathLE", "EphemeronLE", "ThunderbirdLE", "TritonLE", "WintersGateLE", "WorldofSleepersLE"]
bot = Bot(Race.Terran, SmoothBrainBot(), "SmoothBrainBot")
#enemy = Bot(Race.Terran, WorkerRushBot())
enemy = Bot(Race.Zerg, Pool12AllIn())
#enemyvanilla = Computer(Race.Random, Difficulty.CheatVision)

# Start game
if __name__ == "__main__":
    if "--LadderServer" in sys.argv:
        # Ladder game started by LadderManager
        print("Starting ladder game...")
        result, opponentid = run_ladder_game(bot)
        print(result, " against opponent ", opponentid)
    else:
        # Local game
        print("Starting local game...")
        run_game(maps.get("AcropolisLE"), # maps.get(map_names[random.randint(0, len(map_names) - 1)]),
        [bot, enemy], realtime=False)
