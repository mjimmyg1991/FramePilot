local LrDialogs = import 'LrDialogs'
local LrFunctionContext = import 'LrFunctionContext'
local LrPrefs = import 'LrPrefs'
local LrView = import 'LrView'

return {
	sectionsForTopOfDialog = function(f, _)
		local prefs = LrPrefs.prefsForPlugin()
		local labelWidth = LrView.share('framepilot_prefs_label_width')

		return {
			{
				title = 'FramePilot Engine',
				bind_to_object = prefs,

				f:static_text {
					title = 'Leave the engine empty when this plugin sits inside the FramePilot folder;\n'
						.. 'it finds framepilot-engine automatically. For a source checkout, point it\n'
						.. 'at engine.py and set the Python interpreter.',
					height_in_lines = 3,
				},
				f:row {
					f:static_text { title = 'Engine:', alignment = 'right', width = labelWidth },
					f:edit_field { value = LrView.bind('enginePath'), width_in_chars = 45 },
					f:push_button {
						title = 'Browse...',
						action = function()
							local chosen = LrDialogs.runOpenPanel {
								title = 'Choose the FramePilot engine',
								canChooseFiles = true,
								canChooseDirectories = false,
								allowsMultipleSelection = false,
							}
							if chosen and chosen[1] then
								prefs.enginePath = chosen[1]
							end
						end,
					},
				},
				f:row {
					f:static_text { title = 'Python:', alignment = 'right', width = labelWidth },
					f:edit_field { value = LrView.bind('pythonPath'), width_in_chars = 45 },
				},
				f:row {
					f:static_text { title = '', width = labelWidth },
					f:push_button {
						title = 'Check Setup...',
						action = function()
							LrFunctionContext.postAsyncTaskWithContext('FramePilot check setup', function(context)
								LrDialogs.attachErrorDialogToFunctionContext(context)
								require('FramePilotCheckSetup').run(context)
							end)
						end,
					},
				},
			},
		}
	end,
}
