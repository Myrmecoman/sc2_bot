# pylint: disable=E0401
import sys
import random

from __init__ import run_ladder_game

# Load bot
from bot.bot import SmoothBrainBot

from sc2 import maps
from sc2.data import Difficulty, Race, AIBuild
from sc2.main import run_game
from sc2.player import Bot, Computer, Human

map_names = ["IncorporealAIE_v4",
             "LeyLinesAIE_v3",
             "MagannathaAIE_v2",
             "PersephoneAIE_v4",
             "PylonAIE_v4",
             "TorchesAIE_v4",
             "UltraloveAIE_v2"]

bot = Bot(Race.Terran, SmoothBrainBot(), "SmoothBrainBot")
human = Human(Race.Terran, "Human", True)

# Start game
if __name__ == "__main__":
    if "--LadderServer" in sys.argv:
        # Ladder game started by LadderManager
        print("Starting ladder game...")
        result, opponentid = run_ladder_game(bot)
        print(result, " against opponent ", opponentid)
    else:
         
        from training_bots.worker_rush import WorkerRushBot
        from training_bots.lift_hide import Lift
        from training_bots.lift_topright import LiftTopRight
        from training_bots.PF_rush import PFrush
        from training_bots.single_worker_attack import SingleWorker
        from training_bots.resume_building_tester import ResumeBuilding
        from training_bots.MassReaper.main import MassReaper

        # enemy is chosen here, after the imports above, not at module level - each option
        # depends on an import that's deliberately deferred into this block (so a broken
        # training bot can't crash a real ladder submission, which never reaches this branch);
        # picking one at module level runs before its import exists and fails with NameError
        enemy = Computer(Race.Zerg, Difficulty.CheatInsane, AIBuild.Macro)
        #enemy = Computer(Race.Zerg, Difficulty.CheatInsane, AIBuild.Rush)
        #enemy = Computer(Race.Protoss, Difficulty.CheatInsane, AIBuild.Air)
        #enemy = Computer(Race.Terran, Difficulty.CheatInsane, AIBuild.Macro)
        #enemy = Bot(Race.Terran, SmoothBrainBot(), "SmoothBrainBotEnemy")
        #enemy = Bot(Race.Terran, MassReaper(), "MassReaper")
        #enemy = Bot(Race.Protoss, WorkerRushBot(), "WorkerRush")
        #enemy = Bot(Race.Terran, ResumeBuilding(), "ResumeBuilding")
        #enemy = Bot(Race.Terran, SingleWorker(), "SingleWorker")
        #enemy = Bot(Race.Terran, Lift(), "Lift")
        #enemy = Bot(Race.Terran, LiftTopRight(), "LiftTopRight")
        #enemy = Bot(Race.Terran, PFrush(), "PFrush")

        # Local game
        print("Starting local game...")
        run_game(
        maps.get(map_names[random.randint(0, len(map_names) - 1)]),
        [bot, enemy], realtime=False
        #[human, bot], realtime=True
        )
