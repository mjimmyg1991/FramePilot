--[[
    FramePilot Read Menu

    One-click manual trigger to read metadata for all images
    that have newer XMP sidecars (written by FramePilot).
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

local SIGNAL_FILENAME = ".framepilot_ready"


local function readSignalFile(signalPath)
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


LrFunctionContext.postAsyncTaskWithContext("FramePilotReadAll", function(context)
    local catalog = LrApplication.activeCatalog()
    if not catalog then
        LrDialogs.message("FramePilot", "No active catalog found.", "warning")
        return
    end

    LrDialogs.showBezel("FramePilot: Scanning for signal files...")

    -- Find all signal files across catalog folders
    local allPaths = {}
    local signalFilesToDelete = {}

    local folders = catalog:getFolders()
    if folders then
        for _, folder in ipairs(folders) do
            local folderPath = folder:getPath()
            if folderPath then
                local signalPath = LrPathUtils.child(folderPath, SIGNAL_FILENAME)
                if LrFileUtils.exists(signalPath) then
                    local paths = readSignalFile(signalPath)
                    for _, p in ipairs(paths) do
                        table.insert(allPaths, p)
                    end
                    table.insert(signalFilesToDelete, signalPath)
                end
            end
        end
    end

    if #allPaths == 0 then
        -- Fall back: read metadata for currently selected photos
        local selectedPhotos = catalog:getTargetPhotos()
        if selectedPhotos and #selectedPhotos > 0 then
            local readCount = 0
            catalog:withWriteAccessDo("FramePilot: Read Metadata", function()
                for _, photo in ipairs(selectedPhotos) do
                    photo:readMetadata()
                    readCount = readCount + 1
                end
            end)
            LrDialogs.showBezel("FramePilot: Read metadata for " .. readCount .. " selected photo(s)")
        else
            LrDialogs.message(
                "FramePilot",
                "No signal files found and no photos selected.\n\n" ..
                "Process images in FramePilot first, or select photos and try again.",
                "info"
            )
        end
        return
    end

    -- Process all found signal files
    local readCount = 0
    catalog:withWriteAccessDo("FramePilot: Read Metadata", function()
        for _, imagePath in ipairs(allPaths) do
            local photo = catalog:findPhotoByPath(imagePath)
            if photo then
                photo:readMetadata()
                readCount = readCount + 1
            end
        end
    end)

    -- Clean up signal files
    for _, signalPath in ipairs(signalFilesToDelete) do
        LrFileUtils.delete(signalPath)
    end

    LrDialogs.showBezel("FramePilot: Applied " .. readCount .. " crop(s) from " .. #signalFilesToDelete .. " batch(es)")
    logger:info("Manual read: " .. readCount .. " images from " .. #signalFilesToDelete .. " signal files")
end)
