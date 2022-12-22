# pylint: disable=E0401
import sys
import random

from __init__ import run_ladder_game

# Load bot
from bot import SmoothBrainBot
from training_bots.pool12_allin import Pool12AllIn
from training_bots.worker_rush import WorkerRushBot

from sc2 import maps
from sc2.data import Difficulty, Race
from sc2.main import run_game
from sc2.player import Bot, Computer, Human

map_names = ["AcropolisLE", "DiscoBloodbathLE", "EphemeronLE", "ThunderbirdLE", "TritonLE", "WintersGateLE", "WorldofSleepersLE"]
bot = Bot(Race.Terran, SmoothBrainBot(), "SmoothBrainBot")
enemy = Bot(Race.Terran, WorkerRushBot(), "BadWorkerRush")
#enemy = Bot(Race.Zerg, Pool12AllIn(), "12pool")
enemycheat = Computer(Race.Random, Difficulty.VeryHard) # CheaterVision
human = Human(Race.Terran, "Hooman", True)

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
        run_game(maps.get(map_names[random.randint(0, len(map_names) - 1)]),
        #[enemy, enemycheat], realtime=False)
        [bot, enemycheat], realtime=False)
        #[human, bot], realtime=True)
