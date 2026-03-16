--[[
    FramePilot Watch Menu

    Toggles background watching for .framepilot_ready signal files.
    When detected, auto-reads metadata for the listed images.
]]

local LrTasks = import "LrTasks"
local LrDialogs = import "LrDialogs"
local LrApplication = import "LrApplication"
local LrFileUtils = import "LrFileUtils"
local LrPathUtils = import "LrPathUtils"
local LrLogger = import "LrLogger"
local LrFunctionContext = import "LrFunctionContext"

local logger = LrLogger("FramePilot")
logger:enable("logfile")

local POLL_INTERVAL = 5  -- seconds between checks
local SIGNAL_FILENAME = ".framepilot_ready"


local function readSignalFile(signalPath)
    -- Read the signal file and return a list of image paths
    local paths = {}
    local file = io.open(signalPath, "r")
    if file then
        for line in file:lines() do
            local trimmed = line:match("^%s*(.-)%s*$")
            if trimmed and #trimmed > 0 then
                table.insert(paths, trimmed)
            end
        end
        file:close()
    end
    return paths
end


local function findSignalFiles(catalog)
    -- Search for .framepilot_ready files in known watch directories
    -- and near catalog sources
    local signalFiles = {}
    local catalogDir = LrPathUtils.parent(catalog:getPath())

    -- Check catalog directory
    local signalPath = LrPathUtils.child(catalogDir, SIGNAL_FILENAME)
    if LrFileUtils.exists(signalPath) then
        table.insert(signalFiles, signalPath)
    end

    -- Check user-configured watch directories
    if _G.FramePilotWatchDirs then
        for _, dir in ipairs(_G.FramePilotWatchDirs) do
            local path = LrPathUtils.child(dir, SIGNAL_FILENAME)
            if LrFileUtils.exists(path) then
                table.insert(signalFiles, path)
            end
        end
    end

    -- Search catalog source folders (top-level only)
    local folders = catalog:getFolders()
    if folders then
        for _, folder in ipairs(folders) do
            local folderPath = folder:getPath()
            if folderPath then
                local path = LrPathUtils.child(folderPath, SIGNAL_FILENAME)
                if LrFileUtils.exists(path) then
                    table.insert(signalFiles, path)
                end
            end
        end
    end

    return signalFiles
end


local function processSignalFile(catalog, signalPath)
    -- Read paths from signal file and trigger metadata read
    local imagePaths = readSignalFile(signalPath)
    if #imagePaths == 0 then
        logger:info("Signal file empty: " .. signalPath)
        return 0
    end

    logger:info("Processing signal file: " .. signalPath .. " with " .. #imagePaths .. " images")

    local readCount = 0

    catalog:withWriteAccessDo("FramePilot: Read Metadata", function()
        for _, imagePath in ipairs(imagePaths) do
            -- Find the photo in the catalog
            local photo = catalog:findPhotoByPath(imagePath)
            if photo then
                -- Trigger metadata read from XMP
                photo:readMetadata()
                readCount = readCount + 1
                logger:info("Read metadata for: " .. imagePath)
            else
                logger:warn("Photo not found in catalog: " .. imagePath)
            end
        end
    end)

    -- Delete the signal file after processing
    LrFileUtils.delete(signalPath)
    logger:info("Processed " .. readCount .. " images, deleted signal file")

    return readCount
end


local function watcherLoop()
    local catalog = LrApplication.activeCatalog()
    if not catalog then
        logger:warn("No active catalog")
        return
    end

    logger:info("FramePilot watcher started")

    while _G.FramePilotWatching do
        -- Look for signal files
        local signalFiles = findSignalFiles(catalog)

        for _, signalPath in ipairs(signalFiles) do
            local count = processSignalFile(catalog, signalPath)
            if count > 0 then
                LrDialogs.showBezel("FramePilot: Applied " .. count .. " crop(s)")
            end
        end

        -- Wait before next check
        LrTasks.sleep(POLL_INTERVAL)
    end

    logger:info("FramePilot watcher stopped")
end


-- Main menu action: toggle watching
LrFunctionContext.postAsyncTaskWithContext("FramePilotWatch", function(context)
    if _G.FramePilotWatching then
        -- Stop watching
        _G.FramePilotWatching = false
        LrDialogs.showBezel("FramePilot: Watcher stopped")
    else
        -- Start watching
        _G.FramePilotWatching = true
        LrDialogs.showBezel("FramePilot: Watching for crops...")

        LrTasks.startAsyncTask(function()
            watcherLoop()
        end)
    end
end)
