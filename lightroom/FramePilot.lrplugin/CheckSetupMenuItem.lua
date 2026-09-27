local LrDialogs = import 'LrDialogs'
local LrFunctionContext = import 'LrFunctionContext'

local CheckSetup = require 'FramePilotCheckSetup'

LrFunctionContext.postAsyncTaskWithContext('FramePilot check setup', function(context)
	LrDialogs.attachErrorDialogToFunctionContext(context)
	CheckSetup.run(context)
end)
