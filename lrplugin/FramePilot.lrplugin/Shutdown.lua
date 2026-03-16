--[[
    FramePilot Plugin Shutdown

    Stops the background watcher task.
]]

local LrLogger = import "LrLogger"

local logger = LrLogger("FramePilot")
logger:enable("logfile")

-- Stop the watcher
_G.FramePilotWatching = false
_G.FramePilotWatchDirs = {}

logger:info("FramePilot plugin shutdown")
