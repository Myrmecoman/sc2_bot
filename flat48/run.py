# pylint: disable=E0401
import sys
import random

from __init__ import run_ladder_game

# Load bot
from bot import SmoothBrainFlat48
from training_bots.pool12_allin import Pool12AllIn
from training_bots.worker_rush import WorkerRushBot
from training_bots.lift_hide import Lift
from training_bots.lift_topright import LiftTopRight
from training_bots.PF_rush import PFrush
from training_bots.single_worker_attack import SingleWorker

from sc2 import maps
from sc2.data import Difficulty, Race
from sc2.main import run_game
from sc2.player import Bot, Computer, Human

map_names = ["BerlingradAIE", "HardwireAIE", "InsideAndOutAIE", "MoondanceAIE", "StargazersAIE", "WaterfallAIE"]
bot = Bot(Race.Terran, SmoothBrainFlat48(), "SmoothBrainFlat48")
enemycheat = Computer(Race.Random, Difficulty.CheatInsane) # CheatInsane, CheatVision
human = Human(Race.Terran, "Human", True)

#enemy = Bot(Race.Terran, SmoothBrainFlat48(), "SmoothBrainBotEnemy")
#enemy = Bot(Race.Terran, WorkerRushBot(), "BadWorkerRush")
enemy = Bot(Race.Terran, SingleWorker(), "SingleWorker")
#enemy = Bot(Race.Terran, Lift(), "Lift")
#enemy = Bot(Race.Terran, LiftTopRight(), "LiftTopRight")
#enemy = Bot(Race.Terran, PFrush(), "PFrush")
#enemy = Bot(Race.Zerg, Pool12AllIn(), "12pool")

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
        run_game(maps.get("Flat482Spawns"), [bot, enemy], realtime=True)
