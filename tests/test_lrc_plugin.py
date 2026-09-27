"""Tests for the Lightroom Classic plugin Lua code, run under Lua 5.1 via lupa.

The Lightroom SDK is replaced with small fakes so the plugin's glue logic
(job encoding, engine invocation, result parsing, applying crops) can be
exercised together with the real Python engine.
"""

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

lupa_lua51 = pytest.importorskip("lupa.lua51")

from src.detector import Detection
from src.lrc_bridge import run_job


PLUGIN_DIR = Path(__file__).parent.parent / "lightroom" / "FramePilot.lrplugin"
PLUGIN_FILES = sorted(PLUGIN_DIR.glob("*.lua"))


def make_runtime():
    lua = lupa_lua51.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(f"package.path = [[{PLUGIN_DIR}/?.lua;]] .. package.path")
    return lua


def lua_table_to_python(value):
    if lupa_lua51.lua_type(value) != "table":
        return value
    keys = list(value.keys())
    if keys and all(isinstance(k, int) for k in keys):
        return [lua_table_to_python(value[k]) for k in sorted(keys)]
    return {k: lua_table_to_python(value[k]) for k in keys}


@pytest.fixture
def lua():
    return make_runtime()


@pytest.fixture
def core(lua):
    return lua.eval("require('FramePilotCore')")


class TestPluginSyntax:
    """Every plugin file must compile under Lua 5.1, which Lightroom embeds."""

    @pytest.mark.parametrize("path", PLUGIN_FILES, ids=lambda p: p.name)
    def test_compiles(self, lua, path):
        source = path.read_text(encoding="utf-8")
        check = lua.eval("function(src, name) local f, err = loadstring(src, name); return f ~= nil, err end")
        compiled, error = check(source, path.name)
        assert compiled, error


class TestCoreJson:
    """Tests for the plugin's JSON encoder."""

    def test_job_round_trips_through_python(self, lua, core):
        job = lua.eval("""{
            settings = { aspect_ratio = '4:5', strategy = 'largest', precise = false, padding = 0.15 },
            photos = {
                { id = '12', path = 'C:\\\\Users\\\\Me\\\\Tmp\\\\IMG "1"\\n.jpg', orientation = 'BC',
                  current_crop = { left = 0, top = 0.25, right = 1, bottom = 0.75 } },
            },
        }""")
        decoded = json.loads(core.encodeJson(job))
        assert decoded["settings"] == {
            "aspect_ratio": "4:5", "strategy": "largest", "precise": False, "padding": 0.15,
        }
        photo = decoded["photos"][0]
        assert photo["path"] == 'C:\\Users\\Me\\Tmp\\IMG "1"\n.jpg'
        assert photo["current_crop"]["top"] == pytest.approx(0.25)

    def test_utf8_passes_through(self, lua, core):
        value = lua.eval("{ path = 'Fotos/Café/ß.jpg' }")
        assert json.loads(core.encodeJson(value)) == {"path": "Fotos/Café/ß.jpg"}


class TestCoreResults:
    """Tests for parsing the engine's tab-separated results."""

    def test_parse_statuses(self, core):
        text = (
            "5\tsuccess\t0.100000\t0.000000\t0.600000\t1.000000\t\n"
            "6\tno_subject\t\t\t\t\tNo subject detected\n"
            "7\terror\t\t\t\t\tCould not read rendition\r\n"
        )
        results = lua_table_to_python(core.parseResults(text))
        assert results["5"]["status"] == "success"
        assert results["5"]["crop"] == pytest.approx(
            {"left": 0.1, "top": 0.0, "right": 0.6, "bottom": 1.0}
        )
        assert results["6"]["status"] == "no_subject"
        assert results["7"]["message"] == "Could not read rendition"

    @pytest.mark.parametrize("coords", [
        "0.5\t0\t0.4\t1",
        "-0.1\t0\t0.4\t1",
        "0\t0\t1.2\t1",
        "x\t0\t1\t1",
    ])
    def test_invalid_crop_becomes_error(self, core, coords):
        results = lua_table_to_python(core.parseResults(f"9\tsuccess\t{coords}\t\n"))
        assert results["9"]["status"] == "error"


class TestCoreCommand:
    """Tests for building the engine command line."""

    def test_windows_wraps_whole_command(self, lua, core):
        args = lua.eval(r"{ [[C:\Program Files\FramePilot\framepilot-engine.exe]], [[C:\T\job.json]], [[C:\T\r.tsv]] }")
        command = core.buildCommand(args, r"C:\T\engine.log", True)
        assert command == (
            r'""C:\Program Files\FramePilot\framepilot-engine.exe" "C:\T\job.json" '
            r'"C:\T\r.tsv" > "C:\T\engine.log" 2>&1"'
        )

    def test_posix_escapes_single_quotes(self, lua, core):
        args = lua.eval("{ 'python3', \"/Users/o'neil/engine.py\" }")
        command = core.buildCommand(args, "/tmp/log", False)
        assert command == "'python3' '/Users/o'\\''neil/engine.py' > '/tmp/log' 2>&1"


class TestCoreFraming:
    """Tests for the framing presets sent to the engine."""

    def test_known_framing(self, core):
        framing = core.framing("widest")
        assert framing.min_scale == pytest.approx(1.0)

    @pytest.mark.parametrize("value", [None, "", "huge"])
    def test_unknown_framing_is_balanced(self, core, value):
        assert core.framing(value).value == "balanced"

    def test_framings_zoom_in_order(self, core):
        framings = lua_table_to_python(core.FRAMINGS)
        paddings = [f["padding"] for f in framings if f["min_scale"] < 1]
        assert paddings == sorted(paddings)


class TestCoreDevelopSettings:
    """Tests for reading crop state from develop settings."""

    def test_current_crop_defaults_to_full_frame(self, lua, core):
        crop = lua_table_to_python(core.currentCrop(lua.eval("{}")))
        assert crop == {"left": 0, "top": 0, "right": 1, "bottom": 1}

    def test_current_crop_reads_values(self, lua, core):
        settings = lua.eval("{ CropLeft = 0.1, CropTop = 0.2, CropRight = 0.9, CropBottom = 0.8 }")
        crop = lua_table_to_python(core.currentCrop(settings))
        assert crop == pytest.approx({"left": 0.1, "top": 0.2, "right": 0.9, "bottom": 0.8})

    def test_is_straightened(self, lua, core):
        assert core.isStraightened(lua.eval("{ CropAngle = 1.5 }"))
        assert not core.isStraightened(lua.eval("{ CropAngle = 0 }"))
        assert not core.isStraightened(lua.eval("{}"))


FAKE_SDK = r"""
local fake = {
    messages = {},
    applied = {},
    commands = {},
    history = {},
    photos = {},
    dialogAction = 'ok',
    engineExists = true,
}

local function makePhoto(spec)
    local photo = { localIdentifier = spec.id, _spec = spec }
    function photo:getRawMetadata(key)
        if key == 'isVideo' then return spec.isVideo or false end
    end
    function photo:getFormattedMetadata(key)
        if key == 'fileName' then return spec.name end
        if key == 'copyName' then return spec.copyName end
    end
    function photo:getDevelopSettings()
        return spec.develop or {}
    end
    function photo:applyDevelopSettings(settings, historyName)
        assert(fake.inWriteAccess, 'applyDevelopSettings outside withWriteAccessDo')
        fake.applied[spec.id] = settings
        fake.history[spec.id] = historyName
    end
    return photo
end
fake.makePhoto = makePhoto

local catalog = {}
function catalog:getTargetPhotos() return fake.photos end
function catalog:withWriteAccessDo(name, fn)
    fake.inWriteAccess = true
    fn()
    fake.inWriteAccess = false
end

local progress = {}
function progress:isCanceled() return false end
function progress:setCaption() end
function progress:done() end

local modules = {
    LrApplication = { activeCatalog = function() return catalog end },
    LrBinding = { makePropertyTable = function() return {} end },
    LrDialogs = {
        message = function(message, info, style)
            fake.messages[#fake.messages + 1] = { message = message, info = info, style = style }
        end,
        presentModalDialog = function() return fake.dialogAction end,
        attachErrorDialogToFunctionContext = function() end,
    },
    LrExportSession = function(params)
        local session = {}
        function session:renditions()
            local i = 0
            return function()
                i = i + 1
                local photo = params.photosToExport[i]
                if not photo then return nil end
                local rendition = { photo = photo }
                function rendition:waitForRender()
                    return fake.render(photo._spec, params.exportSettings.LR_export_destinationPathPrefix)
                end
                return i, rendition
            end
        end
        return session
    end,
    LrFileUtils = {
        exists = function(path)
            if path:match('framepilot%-engine') then return fake.engineExists and 'file' or false end
            return false
        end,
        createAllDirectories = function(path) fake.workDir = path end,
        delete = function() end,
    },
    LrFunctionContext = {
        callWithContext = function(_, fn) return fn({ addCleanupHandler = function() end }) end,
    },
    LrPathUtils = {
        child = function(a, b) return a .. '/' .. b end,
        parent = function(p) return (p:gsub('/[^/]*$', '')) end,
        getStandardFilePath = function() return fake.tempRoot end,
    },
    LrPrefs = { prefsForPlugin = function() return fake.prefs end },
    LrProgressScope = function() return progress end,
    LrTasks = {
        execute = function(command)
            fake.commands[#fake.commands + 1] = command
            return fake.execute(command)
        end,
    },
    LrView = {
        osFactory = function()
            return setmetatable({}, { __index = function() return function(_, t) return t end end })
        end,
        share = function(name) return name end,
        bind = function(name) return name end,
    },
}

function import(name)
    return assert(modules[name], 'unexpected import ' .. name)
end

WIN_ENV = false
_PLUGIN = { path = '/Apps/FramePilot/FramePilot.lrplugin' }
return fake
"""


class TestAutoCropFlow:
    """Runs the full plugin flow against the fake SDK and the real engine."""

    @pytest.fixture
    def harness(self, lua, tmp_path):
        fake = lua.execute(FAKE_SDK)
        fake.tempRoot = str(tmp_path)
        fake.prefs = lua.table()

        def render(spec, folder):
            if spec.renderFails:
                return False, "Source file is missing"
            path = Path(folder) / f"{spec.name}.jpg"
            path.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(path), np.zeros((spec.height or 400, spec.width or 600, 3), dtype=np.uint8))
            return True, str(path)

        subjects = {}

        class ByNameDetector:
            def detect(self, image_path):
                bbox = subjects.get(Path(image_path).stem)
                return [Detection(bbox=bbox, confidence=0.9, label="person")] if bbox else []

        def execute(command):
            parts = command.split("' '")
            job_path = parts[-2]
            result_path = parts[-1].split("'")[0]
            return run_job(job_path, result_path, detector=ByNameDetector())

        fake.render = render
        fake.execute = execute
        auto_crop = lua.eval("require('FramePilotAutoCrop')")
        return fake, auto_crop, subjects

    def add_photo(self, lua, fake, **spec):
        photo = fake.makePhoto(lua.table_from(spec))
        fake.photos[len(fake.photos) + 1] = photo
        return photo

    def run(self, lua, auto_crop):
        context = lua.eval("{ addCleanupHandler = function() end }")
        auto_crop.run(context)

    def test_crops_applied_and_problems_reported(self, lua, harness):
        fake, auto_crop, subjects = harness
        subjects["hero"] = (0.45, 0.1, 0.55, 0.9)
        self.add_photo(lua, fake, id=1, name="hero")
        self.add_photo(lua, fake, id=2, name="empty")
        self.add_photo(lua, fake, id=3, name="tilted", develop=lua.table_from({"CropAngle": 2.0}))
        self.add_photo(lua, fake, id=4, name="clip", isVideo=True)
        self.add_photo(lua, fake, id=5, name="offline", renderFails=True)

        self.run(lua, auto_crop)

        assert list(fake.applied.keys()) == [1]
        crop = lua_table_to_python(fake.applied[1])
        assert crop["CropConstrainAspectRatio"] is True
        assert crop["CropTop"] == pytest.approx(0.0)
        assert crop["CropBottom"] == pytest.approx(1.0)
        width = (crop["CropRight"] - crop["CropLeft"]) * 600
        assert width / 400 == pytest.approx(0.8, abs=1e-3)
        assert fake.history[1] == "FramePilot 4:5"

        messages = lua_table_to_python(fake.messages)
        assert len(messages) == 1
        summary = messages[0]
        assert summary["message"] == "Cropped 1 photo to 4:5."
        for expected in ["No subject found (1)", "empty", "tilted", "clip", "offline"]:
            assert expected in summary["info"]

    def test_rotated_photo_gets_stored_coordinates(self, lua, harness):
        fake, auto_crop, subjects = harness
        subjects["rotated"] = (0.0, 0.1, 0.1, 0.9)
        self.add_photo(
            lua, fake, id=1, name="rotated", develop=lua.table_from({"orientation": "BC"}),
        )

        self.run(lua, auto_crop)

        crop = lua_table_to_python(fake.applied[1])
        assert crop["CropLeft"] == pytest.approx(0.0)
        assert crop["CropRight"] == pytest.approx(1.0)
        assert crop["CropTop"] == pytest.approx(0.0)

    def test_settings_saved_and_sent_to_engine(self, lua, harness, tmp_path):
        fake, auto_crop, subjects = harness
        subjects["hero"] = (0.4, 0.1, 0.6, 0.9)
        fake.prefs.aspectRatio = "9:16"
        fake.prefs.strategy = "largest"
        self.add_photo(lua, fake, id=1, name="hero")

        self.run(lua, auto_crop)

        job = json.loads((Path(fake.workDir) / "job.json").read_text(encoding="utf-8"))
        assert job["settings"]["aspect_ratio"] == "9:16"
        assert job["settings"]["strategy"] == "largest"
        assert job["settings"]["padding"] == pytest.approx(0.15)
        assert job["settings"]["min_scale"] == pytest.approx(0.5)
        assert fake.history[1] == "FramePilot 9:16"
        assert "/Apps/FramePilot/framepilot-engine" in fake.commands[1]

    def test_widest_framing_keeps_full_height(self, lua, harness):
        fake, auto_crop, subjects = harness
        subjects["small"] = (0.48, 0.5, 0.52, 0.6)
        fake.prefs.framing = "widest"
        self.add_photo(lua, fake, id=1, name="small")

        self.run(lua, auto_crop)

        crop = lua_table_to_python(fake.applied[1])
        assert crop["CropTop"] == pytest.approx(0.0)
        assert crop["CropBottom"] == pytest.approx(1.0)
        assert fake.prefs.framing == "widest"

    def test_default_framing_zooms_small_subject(self, lua, harness):
        fake, auto_crop, subjects = harness
        subjects["small"] = (0.48, 0.5, 0.52, 0.6)
        self.add_photo(lua, fake, id=1, name="small")

        self.run(lua, auto_crop)

        crop = lua_table_to_python(fake.applied[1])
        assert crop["CropBottom"] - crop["CropTop"] == pytest.approx(0.5, abs=1e-5)
        assert crop["CropTop"] < 0.5 and crop["CropBottom"] > 0.6

    def test_cancelled_dialog_does_nothing(self, lua, harness):
        fake, auto_crop, _ = harness
        fake.dialogAction = "cancel"
        self.add_photo(lua, fake, id=1, name="hero")

        self.run(lua, auto_crop)

        assert len(fake.commands) == 0
        assert len(fake.applied) == 0

    def test_missing_engine_reports_error(self, lua, harness):
        fake, auto_crop, _ = harness
        fake.engineExists = False
        self.add_photo(lua, fake, id=1, name="hero")

        self.run(lua, auto_crop)

        messages = lua_table_to_python(fake.messages)
        assert messages[0]["style"] == "critical"
        assert "Could not find the FramePilot engine" in messages[0]["info"]

    def test_engine_failure_shows_log(self, lua, harness):
        fake, auto_crop, _ = harness

        def failing_execute(command):
            log_path = command.split("> '")[1].split("'")[0]
            Path(log_path).write_text("Traceback: model missing", encoding="utf-8")
            return 1

        fake.execute = failing_execute
        self.add_photo(lua, fake, id=1, name="hero")

        self.run(lua, auto_crop)

        messages = lua_table_to_python(fake.messages)
        assert "exit code 1" in messages[0]["message"]
        assert "model missing" in messages[0]["info"]
        assert len(fake.applied) == 0
