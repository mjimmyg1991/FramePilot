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

local function pythonProgram(prefs)
	if prefs.pythonPath and prefs.pythonPath ~= '' then
		return prefs.pythonPath
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
			return { pythonProgram(prefs), custom, source = 'Plug-in Manager setting', path = custom }
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
		return { pythonProgram(prefs), sourceScript, source = 'source checkout', path = sourceScript }
	end

	return nil, 'Could not find the FramePilot engine.\n\n'
		.. 'Keep FramePilot.lrplugin inside the FramePilot folder, next to '
		.. exeName .. ', or set the engine location in File > Plug-in Manager.'
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
