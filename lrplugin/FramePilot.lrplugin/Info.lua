--[[
    FramePilot Lightroom Classic Plugin

    Watches for .framepilot_ready signal files and auto-triggers
    "Read Metadata from Files" for processed images.
]]

return {
    LrSdkVersion = 10.0,
    LrSdkMinimumVersion = 6.0,
    LrToolkitIdentifier = "com.framepilot.lightroom",
    LrPluginName = "FramePilot",
    LrPluginInfoUrl = "https://github.com/framepilot",

    LrInitPlugin = "Init.lua",
    LrShutdownPlugin = "Shutdown.lua",

    LrLibraryMenuItems = {
        {
            title = "Watch for FramePilot Crops",
            file = "WatchMenu.lua",
        },
        {
            title = "Read FramePilot Metadata",
            file = "ReadMenu.lua",
        },
    },

    VERSION = { major = 1, minor = 0, revision = 0, display = "1.0.0" },
}
