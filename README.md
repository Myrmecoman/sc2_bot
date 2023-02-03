# sc2_bot - SmoothBrain bot

Simple sc2 bot using burnysc2 api.
Its name is SmoothBrain and SmoothBrainFlat48 on the ai arena ladders.
In the "normal" folder is located the normal macro bot. In the "flat48" folder is located the Flat48 version of this bot, which basically performs an all-in attack.
This bot is able to always beat the CheaterInsane AIs against every race, and even often the cheater AIs (with vision + money) especially Zerg and Protoss.

If you are a novice bot writter I suggest you pick some ideas from this bot and copy a few blocks of code. However I do not recommend to straight up copy it and modify it because you need to understand how everything works else you will break everything. :)

# TODO

Repairing not full life mechanical units.<br/>
Army grouping and bio splitting before attacking.<br/>
Better unit production (counter enemy army).<br/>
Build B2 uphill against zerg.<br/>
Do something about the APM bug, which cancels some actions.<br/>
Lift CC if too damaged.<br/>
Implement detection map for banshees.<br/>
Print cyclones against skytoss + handle cyclone micro.<br/>
Fix gas overfill bug.<br/>
Fix cloak air grid.<br/>

SmoothBrain Bot now uses the SC2MapAnalysis api : https://github.com/spudde123/SC2MapAnalysis/tree/develop
