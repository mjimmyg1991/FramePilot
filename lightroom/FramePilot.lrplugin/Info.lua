--[[
FramePilot for Lightroom Classic.

Adds "Auto-crop Selected Photos..." to Library > Plug-in Extras and
File > Plug-in Extras. Selected photos are rendered with their edits, the
FramePilot engine finds the subject, and the crop is applied back to the
photos in the catalog.
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
	},

	LrExportMenuItems = {
		{
			title = 'FramePilot: Auto-crop Selected Photos...',
			file = 'AutoCropMenuItem.lua',
			enabledWhen = 'photosSelected',
		},
	},

	VERSION = { major = 0, minor = 1, revision = 0 },
}
