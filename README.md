# sc2_bot - SmoothBrain bot

Simple sc2 bot using burnysc2 api.
Its name is SmoothBrain on the ai arena ladders.
This bot is able to almost always beat the CheaterInsane AIs against every race.

If you are a novice bot writter I suggest you pick some ideas from this bot and copy a few blocks of code. However I do not recommend to straight up copy it and modify it because you need to understand how everything works else you will break everything. :)

Pathing (grid-based movement, danger-zone avoidance) is implemented in-house at
`normal/bot/pathing/grid_pathing.py` - no third-party map-analysis library, no compiled C
extension. This replaced a vendored dependency (SC2MapAnalysis) that caused repeated deployment
failures on the AI Arena ladder across several different compiled-binary/platform/ABI mismatches.

# TODO

