--[[
Auto-crop flow: settings dialog, render selected photos, run the FramePilot
engine, and apply the returned crops to the photos in the catalog.
]]

local LrApplication = import 'LrApplication'
local LrBinding = import 'LrBinding'
local LrDialogs = import 'LrDialogs'
local LrExportSession = import 'LrExportSession'
local LrFileUtils = import 'LrFileUtils'
local LrFunctionContext = import 'LrFunctionContext'
local LrPathUtils = import 'LrPathUtils'
local LrPrefs = import 'LrPrefs'
local LrProgressScope = import 'LrProgressScope'
local LrTasks = import 'LrTasks'
local LrView = import 'LrView'

local Core = require 'FramePilotCore'

local AutoCrop = {}

local RENDITION_LONG_EDGE = 2048
local DEFAULT_PADDING = 0.15
local MAX_LISTED_PHOTOS = 10

local function fileExists(path)
	return path ~= nil and path ~= '' and LrFileUtils.exists(path) == 'file'
end

local function readFile(path)
	local handle = io.open(path, 'r')
	if not handle then
		return nil
	end
	local text = handle:read('*a')
	handle:close()
	return text
end

local function writeFile(path, text)
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
function AutoCrop.resolveEngine(prefs)
	local custom = prefs.enginePath
	if custom and custom ~= '' then
		if not fileExists(custom) then
			return nil, 'The engine set in Plug-in Manager was not found:\n' .. custom
		end
		if custom:lower():match('%.py$') then
			return { pythonProgram(prefs), custom }
		end
		return { custom }
	end

	local installDir = LrPathUtils.parent(_PLUGIN.path)
	local exeName = WIN_ENV and 'framepilot-engine.exe' or 'framepilot-engine'
	local packaged = LrPathUtils.child(installDir, exeName)
	if fileExists(packaged) then
		return { packaged }
	end

	local sourceScript = LrPathUtils.child(LrPathUtils.parent(installDir), 'engine.py')
	if fileExists(sourceScript) then
		return { pythonProgram(prefs), sourceScript }
	end

	return nil, 'Could not find the FramePilot engine.\n\n'
		.. 'Keep FramePilot.lrplugin inside the FramePilot folder, next to '
		.. exeName .. ', or set the engine location in File > Plug-in Manager.'
end

local function showSettingsDialog(prefs)
	return LrFunctionContext.callWithContext('FramePilot settings', function(context)
		local f = LrView.osFactory()
		local props = LrBinding.makePropertyTable(context)
		props.aspectRatio = prefs.aspectRatio or '4:5'
		props.strategy = prefs.strategy or 'highest_confidence'
		props.precise = prefs.precise or false

		local aspectItems = {}
		for _, ratio in ipairs(Core.ASPECT_RATIOS) do
			aspectItems[#aspectItems + 1] = { title = ratio, value = ratio }
		end

		local labelWidth = LrView.share('framepilot_label_width')
		local contents = f:column {
			bind_to_object = props,
			spacing = f:control_spacing(),
			f:row {
				f:static_text { title = 'Aspect ratio:', alignment = 'right', width = labelWidth },
				f:popup_menu { value = LrView.bind('aspectRatio'), items = aspectItems },
			},
			f:row {
				f:static_text { title = 'Subject:', alignment = 'right', width = labelWidth },
				f:popup_menu { value = LrView.bind('strategy'), items = Core.STRATEGIES },
			},
			f:row {
				f:static_text { title = '', width = labelWidth },
				f:checkbox { title = 'Precise mode (slower, tighter subject outline)', value = LrView.bind('precise') },
			},
			f:separator { fill_horizontal = 1 },
			f:static_text {
				title = 'The crop is applied to the selected photos and can be undone (Edit > Undo)\n'
					.. 'or adjusted with the Crop tool. To keep the original framing, create\n'
					.. 'virtual copies first (Photo > Create Virtual Copy) and crop those.',
				height_in_lines = 3,
			},
		}

		local action = LrDialogs.presentModalDialog {
			title = 'FramePilot Auto-crop',
			contents = contents,
			actionVerb = 'Crop',
		}
		if action ~= 'ok' then
			return nil
		end

		prefs.aspectRatio = props.aspectRatio
		prefs.strategy = props.strategy
		prefs.precise = props.precise
		return {
			aspect_ratio = props.aspectRatio,
			strategy = props.strategy,
			precise = props.precise,
			padding = DEFAULT_PADDING,
		}
	end)
end

local function renditionSettings(folder)
	return {
		LR_export_destinationType = 'specificFolder',
		LR_export_destinationPathPrefix = folder,
		LR_export_useSubfolder = false,
		LR_collisionHandling = 'rename',
		LR_format = 'JPEG',
		LR_jpeg_quality = 0.85,
		LR_export_colorSpace = 'sRGB',
		LR_size_doConstrain = true,
		LR_size_resizeType = 'wh',
		LR_size_maxWidth = RENDITION_LONG_EDGE,
		LR_size_maxHeight = RENDITION_LONG_EDGE,
		LR_size_units = 'pixels',
		LR_size_doNotEnlarge = true,
		LR_outputSharpeningOn = false,
		LR_useWatermark = false,
		LR_minimizeEmbeddedMetadata = true,
		LR_removeLocationMetadata = true,
		LR_reimportExportedPhoto = false,
		LR_includeVideoFiles = false,
	}
end

local function photoName(photo)
	local name = photo:getFormattedMetadata('fileName') or '?'
	local copyName = photo:getFormattedMetadata('copyName')
	if copyName and copyName ~= '' then
		name = name .. ' (' .. copyName .. ')'
	end
	return name
end

local function describeList(heading, entries)
	if #entries == 0 then
		return nil
	end
	local lines = { heading .. ' (' .. #entries .. '):' }
	for i = 1, math.min(#entries, MAX_LISTED_PHOTOS) do
		lines[#lines + 1] = '  ' .. entries[i]
	end
	if #entries > MAX_LISTED_PHOTOS then
		lines[#lines + 1] = '  ...and ' .. (#entries - MAX_LISTED_PHOTOS) .. ' more'
	end
	return table.concat(lines, '\n')
end

local function showSummary(cropped, notCropped, aspectRatio)
	local sections = {}
	for _, section in ipairs(notCropped) do
		local text = describeList(section.heading, section.entries)
		if text then
			sections[#sections + 1] = text
		end
	end
	local headline = string.format('Cropped %d photo%s to %s.', cropped, cropped == 1 and '' or 's', aspectRatio)
	LrDialogs.message(headline, table.concat(sections, '\n\n'), cropped > 0 and 'info' or 'warning')
end

function AutoCrop.run(context)
	local catalog = LrApplication.activeCatalog()
	local photos = catalog:getTargetPhotos()
	if #photos == 0 then
		LrDialogs.message('Select one or more photos first.', nil, 'info')
		return
	end

	local prefs = LrPrefs.prefsForPlugin()
	local engineArgs, engineError = AutoCrop.resolveEngine(prefs)
	if not engineArgs then
		LrDialogs.message('FramePilot', engineError, 'critical')
		return
	end

	local settings = showSettingsDialog(prefs)
	if not settings then
		return
	end

	local eligible, byId = {}, {}
	local skippedVideo, skippedAngle, renderFailed, noSubject, failed = {}, {}, {}, {}, {}
	for _, photo in ipairs(photos) do
		if photo:getRawMetadata('isVideo') then
			skippedVideo[#skippedVideo + 1] = photoName(photo)
		else
			local developSettings = photo:getDevelopSettings()
			if Core.isStraightened(developSettings) then
				skippedAngle[#skippedAngle + 1] = photoName(photo)
			else
				local id = tostring(photo.localIdentifier)
				eligible[#eligible + 1] = photo
				byId[id] = { photo = photo, develop = developSettings }
			end
		end
	end

	local notCropped = {
		{ heading = 'No subject found', entries = noSubject },
		{ heading = 'Skipped: straightened or rotated crop (reset the angle, then run again)', entries = skippedAngle },
		{ heading = 'Skipped: videos', entries = skippedVideo },
		{ heading = 'Could not render', entries = renderFailed },
		{ heading = 'Errors', entries = failed },
	}

	if #eligible == 0 then
		showSummary(0, notCropped, settings.aspect_ratio)
		return
	end

	local workDir = LrPathUtils.child(
		LrPathUtils.getStandardFilePath('temp'),
		string.format('FramePilot-%d-%d', os.time(), math.random(100000, 999999))
	)
	LrFileUtils.createAllDirectories(workDir)
	context:addCleanupHandler(function()
		LrFileUtils.delete(workDir)
	end)

	local progress = LrProgressScope {
		title = 'FramePilot: rendering ' .. #eligible .. ' photo' .. (#eligible == 1 and '' or 's'),
		functionContext = context,
	}

	local exportSession = LrExportSession {
		photosToExport = eligible,
		exportSettings = renditionSettings(workDir),
	}

	local jobPhotos = {}
	for _, rendition in exportSession:renditions { progressScope = progress, stopIfCanceled = true } do
		local id = tostring(rendition.photo.localIdentifier)
		local entry = byId[id]
		local success, pathOrMessage = rendition:waitForRender()
		if success and entry then
			jobPhotos[#jobPhotos + 1] = {
				id = id,
				path = pathOrMessage,
				orientation = entry.develop.orientation or 'AB',
				current_crop = Core.currentCrop(entry.develop),
			}
		else
			renderFailed[#renderFailed + 1] = photoName(rendition.photo) .. ': ' .. tostring(pathOrMessage)
		end
	end

	if progress:isCanceled() then
		return
	end
	if #jobPhotos == 0 then
		showSummary(0, notCropped, settings.aspect_ratio)
		return
	end

	progress:setCaption('Finding subjects (the first run loads the detection model)...')

	local jobPath = LrPathUtils.child(workDir, 'job.json')
	local resultPath = LrPathUtils.child(workDir, 'result.tsv')
	local logPath = LrPathUtils.child(workDir, 'engine.log')
	writeFile(jobPath, Core.encodeJson({ settings = settings, photos = jobPhotos }))

	local commandArgs = {}
	for _, arg in ipairs(engineArgs) do
		commandArgs[#commandArgs + 1] = arg
	end
	commandArgs[#commandArgs + 1] = jobPath
	commandArgs[#commandArgs + 1] = resultPath

	local exitCode = LrTasks.execute(Core.buildCommand(commandArgs, logPath, WIN_ENV))
	local resultText = readFile(resultPath)
	if exitCode ~= 0 or not resultText then
		LrDialogs.message(
			'FramePilot: the crop engine failed (exit code ' .. tostring(exitCode) .. ').',
			Core.tail(readFile(logPath), 1500),
			'critical'
		)
		return
	end

	local results = Core.parseResults(resultText)
	local toApply = {}
	for _, job in ipairs(jobPhotos) do
		local entry = byId[job.id]
		local result = results[job.id]
		if result and result.status == 'success' then
			toApply[#toApply + 1] = { photo = entry.photo, crop = result.crop }
		elseif result and result.status == 'no_subject' then
			noSubject[#noSubject + 1] = photoName(entry.photo)
		else
			local message = result and result.message or 'No result from engine'
			failed[#failed + 1] = photoName(entry.photo) .. ': ' .. message
		end
	end

	progress:setCaption('Applying crops...')
	local historyName = 'FramePilot ' .. settings.aspect_ratio
	catalog:withWriteAccessDo('FramePilot auto-crop', function()
		for _, item in ipairs(toApply) do
			item.photo:applyDevelopSettings({
				CropLeft = item.crop.left,
				CropTop = item.crop.top,
				CropRight = item.crop.right,
				CropBottom = item.crop.bottom,
				CropConstrainAspectRatio = true,
			}, historyName)
		end
	end, { timeout = 60 })

	progress:done()
	showSummary(#toApply, notCropped, settings.aspect_ratio)
end

return AutoCrop
