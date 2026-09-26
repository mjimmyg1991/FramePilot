--[[
Pure helpers for the FramePilot plugin: JSON encoding, result parsing,
command building and develop-setting helpers. No Lightroom imports here so
the module can be tested outside Lightroom.
]]

local Core = {}

Core.ASPECT_RATIOS = { '4:5', '9:16', '1:1', '2:3', '3:4', '5:4', '16:9' }

Core.STRATEGIES = {
	{ title = 'Smart Select', value = 'highest_confidence' },
	{ title = 'Main Subject', value = 'largest' },
	{ title = 'Center Stage', value = 'centered' },
	{ title = 'Whole Group', value = 'group' },
}

local JSON_ESCAPES = {
	['"'] = '\\"',
	['\\'] = '\\\\',
	['\b'] = '\\b',
	['\f'] = '\\f',
	['\n'] = '\\n',
	['\r'] = '\\r',
	['\t'] = '\\t',
}

local function encodeString(value)
	local escaped = value:gsub('[%c"\\]', function(char)
		return JSON_ESCAPES[char] or string.format('\\u%04x', char:byte())
	end)
	return '"' .. escaped .. '"'
end

local function isArray(tbl)
	local count = 0
	for _ in pairs(tbl) do
		count = count + 1
	end
	for i = 1, count do
		if tbl[i] == nil then
			return false
		end
	end
	return count > 0
end

function Core.encodeJson(value)
	local kind = type(value)
	if value == nil then
		return 'null'
	elseif kind == 'boolean' then
		return value and 'true' or 'false'
	elseif kind == 'number' then
		if value ~= value or value == math.huge or value == -math.huge then
			error('Cannot encode non-finite number as JSON')
		end
		return string.format('%.10g', value)
	elseif kind == 'string' then
		return encodeString(value)
	elseif kind == 'table' then
		local parts = {}
		if isArray(value) then
			for i = 1, #value do
				parts[#parts + 1] = Core.encodeJson(value[i])
			end
			return '[' .. table.concat(parts, ',') .. ']'
		end
		local keys = {}
		for key in pairs(value) do
			keys[#keys + 1] = tostring(key)
		end
		table.sort(keys)
		for _, key in ipairs(keys) do
			parts[#parts + 1] = encodeString(key) .. ':' .. Core.encodeJson(value[key])
		end
		return '{' .. table.concat(parts, ',') .. '}'
	end
	error('Cannot encode ' .. kind .. ' as JSON')
end

local function splitFields(line, separator)
	local fields = {}
	local start = 1
	while true do
		local found = string.find(line, separator, start, true)
		if not found then
			fields[#fields + 1] = line:sub(start)
			return fields
		end
		fields[#fields + 1] = line:sub(start, found - 1)
		start = found + 1
	end
end

local function validCrop(left, top, right, bottom)
	if not (left and top and right and bottom) then
		return false
	end
	return left >= 0 and top >= 0 and right <= 1 and bottom <= 1
		and right > left and bottom > top
end

-- Parses the engine's tab-separated results into a table keyed by photo id.
-- Each line: id, status, left, top, right, bottom, message.
function Core.parseResults(text)
	local results = {}
	for line in text:gmatch('[^\r\n]+') do
		local fields = splitFields(line, '\t')
		local id, status = fields[1], fields[2]
		if id and id ~= '' and status then
			local result = { status = status, message = fields[7] or '' }
			if status == 'success' then
				local left, top = tonumber(fields[3]), tonumber(fields[4])
				local right, bottom = tonumber(fields[5]), tonumber(fields[6])
				if validCrop(left, top, right, bottom) then
					result.crop = { left = left, top = top, right = right, bottom = bottom }
				else
					result.status = 'error'
					result.message = 'Engine returned an invalid crop'
				end
			end
			results[id] = result
		end
	end
	return results
end

local function quoteArg(arg, isWindows)
	if isWindows then
		return '"' .. arg .. '"'
	end
	return "'" .. arg:gsub("'", "'\\''") .. "'"
end

-- Builds the shell command for LrTasks.execute. On Windows cmd.exe strips the
-- outermost pair of quotes, so the whole command gets wrapped once more.
function Core.buildCommand(args, logPath, isWindows)
	local quoted = {}
	for i, arg in ipairs(args) do
		quoted[i] = quoteArg(arg, isWindows)
	end
	local command = table.concat(quoted, ' ') .. ' > ' .. quoteArg(logPath, isWindows) .. ' 2>&1'
	if isWindows then
		return '"' .. command .. '"'
	end
	return command
end

-- Returns the photo's current crop in develop coordinates, or the full frame.
function Core.currentCrop(developSettings)
	local left = tonumber(developSettings.CropLeft) or 0
	local top = tonumber(developSettings.CropTop) or 0
	local right = tonumber(developSettings.CropRight) or 1
	local bottom = tonumber(developSettings.CropBottom) or 1
	if not validCrop(left, top, right, bottom) then
		return { left = 0, top = 0, right = 1, bottom = 1 }
	end
	return { left = left, top = top, right = right, bottom = bottom }
end

-- True when the crop is rotated. Rotated crops aren't axis-aligned in develop
-- coordinates, so FramePilot skips them rather than guess.
function Core.isStraightened(developSettings)
	return math.abs(tonumber(developSettings.CropAngle) or 0) > 0.001
end

-- Keeps the last maxLength characters of a log for display in a dialog.
function Core.tail(text, maxLength)
	if not text or #text <= maxLength then
		return text or ''
	end
	return '...' .. text:sub(#text - maxLength + 1)
end

return Core
