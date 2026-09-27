local LrDialogs = import 'LrDialogs'
local LrFunctionContext = import 'LrFunctionContext'

local AutoCrop = require 'FramePilotAutoCrop'

LrFunctionContext.postAsyncTaskWithContext('FramePilot auto-crop', function(context)
	LrDialogs.attachErrorDialogToFunctionContext(context)
	AutoCrop.run(context)
end)
