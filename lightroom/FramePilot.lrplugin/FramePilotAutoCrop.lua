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
local LrView = import 'LrView'

local Core = require 'FramePilotCore'
local Engine = require 'FramePilotEngine'

local AutoCrop = {}

local RENDITION_LONG_EDGE = 2048
local CHECK_LONG_EDGE = 512
local MAX_LISTED_PHOTOS = 10

local function showSettingsDialog(prefs)
	return LrFunctionContext.callWithContext('FramePilot settings', function(context)
		local f = LrView.osFactory()
		local props = LrBinding.makePropertyTable(context)
		props.aspectRatio = prefs.aspectRatio or '4:5'
		props.strategy = prefs.strategy or 'highest_confidence'
		props.framing = Core.framing(prefs.framing).value
		props.precise = prefs.precise or false
		props.verifyCrops = prefs.verifyCrops ~= false

		local aspectItems = {}
		for _, ratio in ipairs(Core.ASPECT_RATIOS) do
			aspectItems[#aspectItems + 1] = { title = ratio, value = ratio }
		end
		local framingItems = {}
		for _, framing in ipairs(Core.FRAMINGS) do
			framingItems[#framingItems + 1] = { title = framing.title, value = framing.value }
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
				f:static_text { title = 'Framing:', alignment = 'right', width = labelWidth },
				f:popup_menu { value = LrView.bind('framing'), items = framingItems },
			},
			f:row {
				f:static_text { title = '', width = labelWidth },
				f:checkbox { title = 'Precise mode (slower, tighter subject outline)', value = LrView.bind('precise') },
			},
			f:row {
				f:static_text { title = '', width = labelWidth },
				f:checkbox {
					title = 'Check where each crop landed; put back the old crop if it is off',
					value = LrView.bind('verifyCrops'),
				},
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
		prefs.framing = props.framing
		prefs.precise = props.precise
		prefs.verifyCrops = props.verifyCrops
		local framing = Core.framing(props.framing)
		return {
			aspect_ratio = props.aspectRatio,
			strategy = props.strategy,
			precise = props.precise,
			padding = framing.padding,
			min_scale = framing.min_scale,
		}
	end)
end

local function renditionSettings(folder, longEdge)
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
		LR_size_maxWidth = longEdge,
		LR_size_maxHeight = longEdge,
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

local function showSummary(cropped, notCropped, aspectRatio, runDir)
	local sections = {}
	for _, section in ipairs(notCropped) do
		local text = describeList(section.heading, section.entries)
		if text then
			sections[#sections + 1] = text
		end
	end
	if runDir then
		sections[#sections + 1] = 'Logs: ' .. runDir
	end
	local headline = string.format('Cropped %d photo%s to %s.', cropped, cropped == 1 and '' or 's', aspectRatio)
	if runDir then
		Engine.log(runDir, headline)
	end
	LrDialogs.message(headline, table.concat(sections, '\n\n'), cropped > 0 and 'info' or 'warning')
end

local function copyForReport(source, runDir, name)
	if source and runDir then
		pcall(LrFileUtils.copy, source, LrPathUtils.child(runDir, name))
	end
end

-- Renders each cropped photo again, small, and has the engine compare it with
-- the region of the pre-crop rendition the crop was meant to show. Crops that
-- didn't land there are put back to the photo's previous crop. Returns the
-- number of photos restored.
local function checkCrops(args)
	local log, items = args.log, args.items
	args.progress:setCaption('Checking where the crops landed...')

	local byId, photos = {}, {}
	for _, item in ipairs(items) do
		item.applied = Core.currentCrop(item.photo:getDevelopSettings())
		byId[item.id] = item
		photos[#photos + 1] = item.photo
	end

	local checkDir = LrPathUtils.child(args.workDir, 'check')
	LrFileUtils.createAllDirectories(checkDir)
	local session = LrExportSession {
		photosToExport = photos,
		exportSettings = renditionSettings(checkDir, CHECK_LONG_EDGE),
	}

	local checkPhotos = {}
	for _, rendition in session:renditions { progressScope = args.progress } do
		local id = tostring(rendition.photo.localIdentifier)
		local item = byId[id]
		local success, pathOrMessage = rendition:waitForRender()
		if item and success then
			item.afterPath = pathOrMessage
			checkPhotos[#checkPhotos + 1] = {
				id = id,
				before = item.entry.renditionPath,
				after = pathOrMessage,
				orientation = item.entry.develop.orientation or 'AB',
				previous_crop = Core.currentCrop(item.entry.develop),
				applied_crop = item.applied,
			}
		elseif item then
			item.checkProblem = 'could not render it again: ' .. tostring(pathOrMessage)
		end
	end

	local results = {}
	if #checkPhotos > 0 then
		local jobPath = LrPathUtils.child(args.runDir, 'verify.json')
		local resultPath = LrPathUtils.child(args.runDir, 'verify.tsv')
		local logPath = LrPathUtils.child(args.runDir, 'verify.log')
		Engine.writeFile(jobPath, Core.encodeJson({ photos = checkPhotos }))
		local exitCode = Engine.execute(args.engineArgs, { '--verify', jobPath, resultPath }, logPath)
		local resultText = Engine.readFile(resultPath)
		log('Position check exit code ' .. tostring(exitCode))
		if exitCode == 0 and resultText then
			results = Core.parseVerifyResults(resultText)
		end
	end

	local toRestore = {}
	for _, item in ipairs(items) do
		local name = photoName(item.photo)
		local orientation = item.entry.develop.orientation or 'AB'
		local check = results[item.id]
		if check and check.status == 'mismatch' then
			local detail = Core.describeMismatch(orientation, check)
			toRestore[#toRestore + 1] = item
			args.mismatched[#args.mismatched + 1] = name .. ': ' .. detail
			copyForReport(item.entry.renditionPath, args.runDir, 'photo-' .. item.id .. '-before.jpg')
			copyForReport(item.afterPath, args.runDir, 'photo-' .. item.id .. '-after.jpg')
			log(string.format('Photo %s %s: crop did not land where expected; develop orientation %s, '
				.. 'best matching orientation %s (%s); previous crop %s; applied crop %s; restoring',
				item.id, name, orientation, check.bestOrientation ~= '' and check.bestOrientation or 'none',
				check.bestScore and string.format('%.3f', check.bestScore) or 'n/a',
				Core.formatCrop(Core.currentCrop(item.entry.develop)), Core.formatCrop(item.applied)))
		elseif check and check.status == 'match' then
			log(string.format('Photo %s: crop landed where expected (orientation %s, score %.3f, best %s)',
				item.id, orientation, check.score or 0, check.bestOrientation))
		else
			local reason = item.checkProblem
				or (check and check.message ~= '' and check.message)
				or 'the check did not run; see verify.log'
			args.unchecked[#args.unchecked + 1] = name .. ': ' .. reason
			log(string.format('Photo %s: position not checked (%s); orientation %s', item.id, reason, orientation))
		end
	end

	if #toRestore > 0 then
		args.catalog:withWriteAccessDo('FramePilot restore crop', function()
			for _, item in ipairs(toRestore) do
				item.photo:applyDevelopSettings(Core.restoreCropSettings(item.entry.develop), 'FramePilot: restored crop')
			end
		end, { timeout = 60 })
	end
	return #toRestore
end

function AutoCrop.run(context)
	local catalog = LrApplication.activeCatalog()
	local photos = catalog:getTargetPhotos()
	if #photos == 0 then
		LrDialogs.message('Select one or more photos first.', nil, 'info')
		return
	end

	local prefs = LrPrefs.prefsForPlugin()
	local engineArgs, engineError = Engine.resolve(prefs)
	if not engineArgs then
		LrDialogs.message('FramePilot', engineError, 'critical')
		return
	end

	local settings = showSettingsDialog(prefs)
	if not settings then
		return
	end

	local okRun, runDir = pcall(Engine.newRunFolder, 'autocrop')
	if not okRun then
		runDir = nil
	end
	local function log(line)
		if runDir then
			Engine.log(runDir, line)
		end
	end
	log(string.format('FramePilot plugin %s, Lightroom %s, %s', Core.PLUGIN_VERSION,
		tostring(LrApplication.versionString()), WIN_ENV and 'Windows' or 'macOS'))
	log('Engine: ' .. table.concat(engineArgs, ' ') .. ' (' .. engineArgs.source .. ')')
	log('Settings: ' .. Core.encodeJson(settings))

	local eligible, byId = {}, {}
	local skippedVideo, skippedAngle, renderFailed, noSubject, failed = {}, {}, {}, {}, {}
	local mismatched, unchecked = {}, {}
	for _, photo in ipairs(photos) do
		if photo:getRawMetadata('isVideo') then
			skippedVideo[#skippedVideo + 1] = photoName(photo)
			log('Skipped video: ' .. photoName(photo))
		else
			local developSettings = photo:getDevelopSettings()
			if Core.isStraightened(developSettings) then
				skippedAngle[#skippedAngle + 1] = photoName(photo)
				log('Skipped crop angle ' .. tostring(developSettings.CropAngle) .. ': ' .. photoName(photo))
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
		{ heading = "Crop didn't land where expected, so the previous crop was put back", entries = mismatched },
		{ heading = "Cropped, but the crop position couldn't be checked", entries = unchecked },
	}

	if #eligible == 0 then
		showSummary(0, notCropped, settings.aspect_ratio, runDir)
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
	runDir = runDir or workDir

	local progress = LrProgressScope {
		title = 'FramePilot: rendering ' .. #eligible .. ' photo' .. (#eligible == 1 and '' or 's'),
		functionContext = context,
	}

	local exportSession = LrExportSession {
		photosToExport = eligible,
		exportSettings = renditionSettings(workDir, RENDITION_LONG_EDGE),
	}

	local jobPhotos = {}
	for _, rendition in exportSession:renditions { progressScope = progress, stopIfCanceled = true } do
		local id = tostring(rendition.photo.localIdentifier)
		local entry = byId[id]
		local success, pathOrMessage = rendition:waitForRender()
		if success and entry then
			entry.renditionPath = pathOrMessage
			jobPhotos[#jobPhotos + 1] = {
				id = id,
				path = pathOrMessage,
				orientation = entry.develop.orientation or 'AB',
				current_crop = Core.currentCrop(entry.develop),
			}
			log(string.format('Photo %s %s: orientation %s, current crop %s', id, photoName(entry.photo),
				tostring(entry.develop.orientation), Core.formatCrop(Core.currentCrop(entry.develop))))
		else
			renderFailed[#renderFailed + 1] = photoName(rendition.photo) .. ': ' .. tostring(pathOrMessage)
			log('Render failed: ' .. photoName(rendition.photo) .. ': ' .. tostring(pathOrMessage))
		end
	end

	if progress:isCanceled() then
		return
	end
	if #jobPhotos == 0 then
		showSummary(0, notCropped, settings.aspect_ratio, runDir)
		return
	end

	progress:setCaption('Finding subjects (the first run loads the detection model)...')

	local jobPath = LrPathUtils.child(runDir, 'job.json')
	local resultPath = LrPathUtils.child(runDir, 'result.tsv')
	local logPath = LrPathUtils.child(runDir, 'engine.log')
	Engine.writeFile(jobPath, Core.encodeJson({ settings = settings, photos = jobPhotos }))

	local exitCode = Engine.execute(engineArgs, { jobPath, resultPath }, logPath)
	local resultText = Engine.readFile(resultPath)
	log('Engine exit code ' .. tostring(exitCode))
	if exitCode ~= 0 or not resultText then
		LrDialogs.message(
			'FramePilot: the crop engine failed (exit code ' .. tostring(exitCode) .. ').',
			Core.tail(Engine.readFile(logPath), 1200) .. '\n\n' .. Engine.logNote(runDir),
			'critical'
		)
		return
	end

	local results = Core.parseResults(resultText)
	local toApply = {}
	for _, job in ipairs(jobPhotos) do
		local entry = byId[job.id]
		local result = results[job.id]
		log(string.format('Photo %s result: %s %s %s', job.id, result and result.status or 'missing',
			result and result.crop and Core.formatCrop(result.crop) or '', result and result.message or ''))
		if result and result.status == 'success' then
			toApply[#toApply + 1] = { id = job.id, photo = entry.photo, crop = result.crop, entry = entry }
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

	local restored = 0
	if prefs.verifyCrops ~= false and #toApply > 0 then
		restored = checkCrops {
			catalog = catalog,
			items = toApply,
			engineArgs = engineArgs,
			workDir = workDir,
			runDir = runDir,
			progress = progress,
			mismatched = mismatched,
			unchecked = unchecked,
			log = log,
		}
	end

	progress:done()
	showSummary(#toApply - restored, notCropped, settings.aspect_ratio, runDir)
end

return AutoCrop
