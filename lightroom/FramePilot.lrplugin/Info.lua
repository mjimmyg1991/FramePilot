--[[
FramePilot for Lightroom Classic.

Adds "Auto-crop Selected Photos..." and "Check Setup..." to Library >
Plug-in Extras and File > Plug-in Extras. Selected photos are rendered with
their edits, the FramePilot engine finds the subject, and the crop is applied
back to the photos in the catalog. Check Setup runs the engine on a bundled
test photo.
]]

return {
	LrSdkVersion = 10.0,
	LrSdkMinimumVersion = 6.0,

	LrToolkitIdentifier = 'com.framepilot.lightroom',
	LrPluginName = 'FramePilot',
	LrPluginInfoUrl = 'https://github.com/mjimmyg1991/FramePilot',
	LrPluginInfoProvider = 'PluginInfoProvider.lua',

	LrLibraryMenuItems = {
		{
			title = 'Auto-crop Selected Photos...',
			file = 'AutoCropMenuItem.lua',
			enabledWhen = 'photosSelected',
		},
		{
			title = 'Check Setup...',
			file = 'CheckSetupMenuItem.lua',
		},
	},

	LrExportMenuItems = {
		{
			title = 'FramePilot: Auto-crop Selected Photos...',
			file = 'AutoCropMenuItem.lua',
			enabledWhen = 'photosSelected',
		},
		{
			title = 'FramePilot: Check Setup...',
			file = 'CheckSetupMenuItem.lua',
		},
	},

	VERSION = { major = 0, minor = 2, revision = 0 },
}
