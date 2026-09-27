--[[
Finding and running the FramePilot engine, shared by Auto-crop and Check Setup.
]]

local LrFileUtils = import 'LrFileUtils'
local LrPathUtils = import 'LrPathUtils'
local LrTasks = import 'LrTasks'

local Core = require 'FramePilotCore'

local Engine = {}

function Engine.fileExists(path)
	return path ~= nil and path ~= '' and LrFileUtils.exists(path) == 'file'
end

function Engine.readFile(path)
	local handle = io.open(path, 'r')
	if not handle then
		return nil
	end
	local text = handle:read('*a')
	handle:close()
	return text
end

function Engine.writeFile(path, text)
	local handle = assert(io.open(path, 'w'))
	handle:write(text)
	handle:close()
end

-- The Python to run engine.py with: the Plug-in Manager setting, then a
-- .venv or venv next to engine.py, then python/python3 on the PATH. Lightroom's
-- PATH on macOS doesn't include Homebrew or pyenv, so a venv is the safer bet.
local function pythonProgram(prefs, scriptDir)
	if prefs.pythonPath and prefs.pythonPath ~= '' then
		return prefs.pythonPath
	end
	if scriptDir then
		for _, venv in ipairs({ '.venv', 'venv' }) do
			local candidate = WIN_ENV
				and LrPathUtils.child(LrPathUtils.child(LrPathUtils.child(scriptDir, venv), 'Scripts'), 'python.exe')
				or LrPathUtils.child(LrPathUtils.child(LrPathUtils.child(scriptDir, venv), 'bin'), 'python')
			if Engine.fileExists(candidate) then
				return candidate
			end
		end
	end
	return WIN_ENV and 'python' or 'python3'
end

-- Finds the engine: the Plug-in Manager setting, then framepilot-engine next
-- to the plugin folder (packaged build), then engine.py in a source checkout.
-- Returns the command's leading arguments, with `source` naming where the
-- engine was found and `path` the engine file, or nil and an error message.
function Engine.resolve(prefs)
	local custom = prefs.enginePath
	if custom and custom ~= '' then
		if not Engine.fileExists(custom) then
			return nil, 'The engine set in Plug-in Manager was not found:\n' .. custom
		end
		if custom:lower():match('%.py$') then
			return { pythonProgram(prefs, LrPathUtils.parent(custom)), custom, source = 'Plug-in Manager setting', path = custom }
		end
		return { custom, source = 'Plug-in Manager setting', path = custom }
	end

	local installDir = LrPathUtils.parent(_PLUGIN.path)
	local exeName = WIN_ENV and 'framepilot-engine.exe' or 'framepilot-engine'
	local packaged = LrPathUtils.child(installDir, exeName)
	if Engine.fileExists(packaged) then
		return { packaged, source = 'next to the plugin', path = packaged }
	end

	local sourceScript = LrPathUtils.child(LrPathUtils.parent(installDir), 'engine.py')
	if Engine.fileExists(sourceScript) then
		return { pythonProgram(prefs, LrPathUtils.parent(sourceScript)), sourceScript, source = 'source checkout', path = sourceScript }
	end

	return nil, 'Could not find the FramePilot engine.\n\n'
		.. 'Keep FramePilot.lrplugin inside the FramePilot folder, next to '
		.. exeName .. ', or set the engine location in File > Plug-in Manager.'
end

local function standardFolder(name)
	local ok, path = pcall(LrPathUtils.getStandardFilePath, name)
	if ok and path and path ~= '' then
		return path
	end
	return nil
end

-- Folder that keeps the last few runs' job, results and logs:
-- %APPDATA%\FramePilot\logs on Windows, ~/Library/Application Support/FramePilot/logs on macOS.
function Engine.logRoot()
	local base = standardFolder('appData') or standardFolder('documents') or standardFolder('temp')
	return LrPathUtils.child(LrPathUtils.child(base, 'FramePilot'), 'logs')
end

local function baseName(path)
	return path:match('([^/\\]+)[/\\]*$') or path
end

-- Removes older run folders so that `keep` remain.
function Engine.pruneRuns(root, keep)
	local names = {}
	for path in LrFileUtils.directoryEntries(root) do
		names[#names + 1] = baseName(path)
	end
	for _, name in ipairs(Core.runsToPrune(names, keep)) do
		local folder = LrPathUtils.child(root, name)
		for file in LrFileUtils.files(folder) do
			LrFileUtils.delete(file)
		end
		LrFileUtils.delete(folder)
	end
end

-- Creates a new run folder in the log folder, keeping the last few runs.
-- Returns the folder path.
function Engine.newRunFolder(kind)
	local root = Engine.logRoot()
	LrFileUtils.createAllDirectories(root)
	local timestamp = os.date('%Y%m%d-%H%M%S')
	local attempt = 1
	local folder = LrPathUtils.child(root, Core.runFolderName(timestamp, kind))
	while LrFileUtils.exists(folder) do
		attempt = attempt + 1
		folder = LrPathUtils.child(root, Core.runFolderName(timestamp, kind, attempt))
	end
	LrFileUtils.createAllDirectories(folder)
	Engine.pruneRuns(root, Core.KEEP_RUNS)
	return folder
end

-- Appends a line to the plugin's log in the run folder.
function Engine.log(runDir, line)
	local handle = io.open(LrPathUtils.child(runDir, 'plugin.log'), 'a')
	if handle then
		handle:write(os.date('%H:%M:%S') .. '  ' .. line .. '\n')
		handle:close()
	end
end

-- Text naming the run's log folder, for dialogs.
function Engine.logNote(runDir)
	return 'Logs for this run (job.json, result.tsv, engine.log, plugin.log) are in:\n' .. runDir
end

-- Advice for an engine that won't start, or nil. A packaged engine unzipped
-- from a download is quarantined by macOS, which stops it from running.
function Engine.startupHint(engineArgs)
	if WIN_ENV then
		return nil
	end
	if engineArgs.source == 'next to the plugin' then
		return 'macOS may be blocking the downloaded engine. In Terminal, run:\n'
			.. "xattr -dr com.apple.quarantine '" .. LrPathUtils.parent(engineArgs.path) .. "'\n"
			.. 'then run Check Setup again.'
	end
	if engineArgs.source == 'source checkout' then
		return 'Python ' .. engineArgs[1] .. ' could not run engine.py. It needs Python 3.11+ with '
			.. 'requirements.txt installed; create a .venv next to engine.py or set the Python path in Plug-in Manager.'
	end
	return nil
end

-- Runs the engine with extra arguments, sending its output to logPath.
-- Returns the exit code.
function Engine.execute(engineArgs, extraArgs, logPath)
	local commandArgs = {}
	for _, arg in ipairs(engineArgs) do
		commandArgs[#commandArgs + 1] = arg
	end
	for _, arg in ipairs(extraArgs) do
		commandArgs[#commandArgs + 1] = arg
	end
	return LrTasks.execute(Core.buildCommand(commandArgs, logPath, WIN_ENV))
end

return Engine
