# sc2_bot - SmoothBrain bot

Simple sc2 bot using burnysc2 api.
Its name is SmoothBrain and SmoothBrainFlat48 on the ai arena ladders.
In the "normal" folder is located the normal macro bot. In the "flat48" folder is located the Flat48 version of this bot, which basically performs an all-in attack.
This bot is able to almost always beat the CheaterInsane AIs against every race.

If you are a novice bot writter I suggest you pick some ideas from this bot and copy a few blocks of code. However I do not recommend to straight up copy it and modify it because you need to understand how everything works else you will break everything. :)

# TODO

Repairing not full life mechanical units.<br/>
Army grouping and bio splitting before attacking.<br/>
Do something about the APM bug, which cancels some actions.<br/>
Defend Zozo and sharkbot worker rushes.<br/>
Stop kitting against units that match our attack range (or reduce it).<br/>
Print cyclones against skytoss + handle cyclone micro.<br/>
Go factory before CC.<br/>
Play more mecha.<br/>
Siege the tanks while on defense waiting.<br/>
Fix raven dropping turrets even on useless units like changelings.<br/>

SmoothBrain Bot now uses the SC2MapAnalysis api : https://github.com/spudde123/SC2MapAnalysis/tree/develop
