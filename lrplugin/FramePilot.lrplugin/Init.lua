--[[
    FramePilot Plugin Initialization

    Sets up the background watcher task and shared state.
]]

local LrLogger = import "LrLogger"

local logger = LrLogger("FramePilot")
logger:enable("logfile")

-- Shared state for the watcher
_G.FramePilotWatching = false
_G.FramePilotWatchDirs = {}

logger:info("FramePilot plugin initialized")
