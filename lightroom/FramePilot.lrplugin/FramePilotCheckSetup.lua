--[[
Check Setup: finds the engine, asks it for its version, runs it on the
bundled test photo and reports the outcome.
]]

local LrApplication = import 'LrApplication'
local LrDialogs = import 'LrDialogs'
local LrFileUtils = import 'LrFileUtils'
local LrPathUtils = import 'LrPathUtils'
local LrPrefs = import 'LrPrefs'
local LrProgressScope = import 'LrProgressScope'

local Core = require 'FramePilotCore'
local Engine = require 'FramePilotEngine'

local CheckSetup = {}

CheckSetup.TEST_PHOTO = 'check-photo.jpg'

local function lightroomVersion()
	local ok, version = pcall(LrApplication.versionString)
	return ok and version or nil
end

local function engineCommand(engineArgs)
	local parts = {}
	for _, arg in ipairs(engineArgs) do
		parts[#parts + 1] = arg
	end
	return table.concat(parts, ' ')
end

local function showReport(ok, lines, workDir)
	local headline = ok and 'FramePilot is set up correctly.' or 'FramePilot setup check failed.'
	if workDir then
		lines[#lines + 1] = { 'Logs', workDir }
		Engine.writeFile(LrPathUtils.child(workDir, 'check.txt'), headline .. '\n' .. Core.setupReport(lines) .. '\n')
	end
	LrDialogs.message(headline, Core.setupReport(lines), ok and 'info' or 'critical')
end

-- Runs the whole check. Returns ok and the report lines (also shown in a dialog).
function CheckSetup.run(context)
	local prefs = LrPrefs.prefsForPlugin()
	local lines = {
		{ 'Plugin', Core.PLUGIN_VERSION },
		{ 'Lightroom', lightroomVersion() },
	}

	local okRun, workDir = pcall(Engine.newRunFolder, 'check')
	if not okRun then
		workDir = LrPathUtils.child(
			LrPathUtils.getStandardFilePath('temp'),
			string.format('FramePilot-check-%d-%d', os.time(), math.random(100000, 999999))
		)
		LrFileUtils.createAllDirectories(workDir)
	end

	local engineArgs, engineError = Engine.resolve(prefs)
	if not engineArgs then
		lines[#lines + 1] = { 'Engine', engineError }
		showReport(false, lines, workDir)
		return false, lines
	end
	lines[#lines + 1] = { 'Engine', engineArgs.path .. ' (' .. engineArgs.source .. ')' }
	lines[#lines + 1] = { 'Command', engineCommand(engineArgs) }

	local progress = LrProgressScope {
		title = 'FramePilot: checking setup',
		functionContext = context,
	}

	progress:setCaption('Asking the engine for its version...')
	local versionPath = LrPathUtils.child(workDir, 'version.txt')
	local versionExit = Engine.execute(engineArgs, { '--version' }, versionPath)
	local versionText = Engine.readFile(versionPath) or ''
	if versionExit ~= 0 then
		lines[#lines + 1] = { 'Engine version', 'the engine failed to start (exit code ' .. tostring(versionExit) .. ')' }
		lines[#lines + 1] = { 'Engine output', Core.tail(versionText, 1200) }
		progress:done()
		showReport(false, lines, workDir)
		return false, lines
	end
	lines[#lines + 1] = { 'Engine version', (versionText:gsub('%s+$', '')) }

	local testPhoto = LrPathUtils.child(_PLUGIN.path, CheckSetup.TEST_PHOTO)
	if not Engine.fileExists(testPhoto) then
		lines[#lines + 1] = { 'Test photo', 'missing from the plugin folder: ' .. testPhoto }
		progress:done()
		showReport(false, lines, workDir)
		return false, lines
	end

	progress:setCaption('Finding the subject in the test photo (loads the detection model)...')
	local jobPath = LrPathUtils.child(workDir, 'job.json')
	local resultPath = LrPathUtils.child(workDir, 'result.tsv')
	local logPath = LrPathUtils.child(workDir, 'engine.log')
	local framing = Core.framing('balanced')
	Engine.writeFile(jobPath, Core.encodeJson({
		settings = {
			aspect_ratio = '4:5',
			strategy = 'highest_confidence',
			precise = false,
			padding = framing.padding,
			min_scale = framing.min_scale,
		},
		photos = {
			{
				id = 'check',
				path = testPhoto,
				orientation = 'AB',
				current_crop = { left = 0, top = 0, right = 1, bottom = 1 },
			},
		},
	}))

	local started = os.time()
	local exitCode = Engine.execute(engineArgs, { jobPath, resultPath }, logPath)
	local seconds = os.time() - started
	local resultText = Engine.readFile(resultPath)
	progress:done()

	local ok, description
	if exitCode ~= 0 or not resultText then
		ok = false
		description = 'the engine failed (exit code ' .. tostring(exitCode) .. ')'
		lines[#lines + 1] = { 'Test photo', description }
		lines[#lines + 1] = { 'Engine output', Core.tail(Engine.readFile(logPath), 1200) }
	else
		ok, description = Core.describeCheckResult(Core.parseResults(resultText).check)
		lines[#lines + 1] = { 'Test photo', description .. ' Took ' .. seconds .. ' s.' }
	end

	showReport(ok, lines, workDir)
	return ok, lines
end

return CheckSetup
