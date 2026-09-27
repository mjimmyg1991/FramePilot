"""Tests for the Lightroom Classic plugin Lua code, run under Lua 5.1 via lupa.

The Lightroom SDK is replaced with small fakes so the plugin's glue logic
(job encoding, engine invocation, result parsing, applying crops) can be
exercised together with the real Python engine.
"""

import contextlib
import json
import shlex
from pathlib import Path

import cv2
import numpy as np
import pytest

lupa_lua51 = pytest.importorskip("lupa.lua51")

from src.detector import Detection, SceneDetections
from src.engine_info import version_text
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


def install_file_system(lua, fake, tmp_path):
    """Back the fake LrFileUtils with the real file system under tmp_path."""
    fake.tempRoot = str(tmp_path / "temp")
    fake.appDataRoot = str(tmp_path / "AppData")
    fake.mkdir = lambda path: Path(path).mkdir(parents=True, exist_ok=True)

    def path_kind(path):
        path = Path(path)
        return "directory" if path.is_dir() else "file" if path.is_file() else False

    def list_dir(path, files_only):
        path = Path(path)
        entries = sorted(path.iterdir()) if path.is_dir() else []
        return lua.table_from([str(p) for p in entries if p.is_file() or not files_only])

    def remove(path):
        path = Path(path)
        if path.is_dir():
            path.rmdir()
        elif path.exists():
            path.unlink()

    fake.pathKind = path_kind
    fake.listDir = list_dir
    fake.remove = remove


def log_root(tmp_path: Path) -> Path:
    return tmp_path / "AppData" / "FramePilot" / "logs"


def run_folders(tmp_path: Path, kind: str) -> list[Path]:
    root = log_root(tmp_path)
    return sorted(p for p in root.iterdir() if p.name.endswith(kind) or f"-{kind}-" in p.name)


def split_command(command: str) -> tuple[list[str], str]:
    """Split a POSIX engine command from buildCommand into (args, log path)."""
    parts = shlex.split(command)
    redirect = parts.index(">")
    return parts[:redirect], parts[redirect + 1]


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
    LrApplication = {
        activeCatalog = function() return catalog end,
        versionString = function() return '14.5 [ 202507031254-fake ]' end,
    },
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
            return fake.pathKind(path)
        end,
        createAllDirectories = function(path)
            fake.workDir = path
            fake.mkdir(path)
        end,
        directoryEntries = function(path)
            local entries, i = fake.listDir(path, false), 0
            return function() i = i + 1; return entries[i] end
        end,
        files = function(path)
            local entries, i = fake.listDir(path, true), 0
            return function() i = i + 1; return entries[i] end
        end,
        delete = function(path) fake.remove(path) end,
    },
    LrFunctionContext = {
        callWithContext = function(_, fn) return fn({ addCleanupHandler = function() end }) end,
    },
    LrPathUtils = {
        child = function(a, b) return a .. '/' .. b end,
        parent = function(p) return (p:gsub('/[^/]*$', '')) end,
        getStandardFilePath = function(name)
            if name == 'appData' then return fake.appDataRoot end
            return fake.tempRoot
        end,
    },
    LrPrefs = { prefsForPlugin = function() return fake.prefs end },
    LrProgressScope = function() return progress end,
    LrShell = { revealInShell = function(path) fake.revealed = path end },
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


def make_auto_crop_harness(lua, tmp_path):
    """Fake SDK with a real engine whose detector finds subjects by rendition name."""
    fake = lua.execute(FAKE_SDK)
    install_file_system(lua, fake, tmp_path)
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
        def detect_scene(self, image_path):
            bbox = subjects.get(Path(image_path).stem)
            people = [Detection(bbox=bbox, confidence=0.9, label="person")] if bbox else []
            return SceneDetections(people=people, balls=[], image_size=(0, 0))

    def execute(command):
        args, log_path = split_command(command)
        engine_args = args[1:]
        if engine_args == ["--version"]:
            Path(log_path).write_text(version_text() + "\n", encoding="utf-8")
            return 0
        job_path, result_path = engine_args
        with open(log_path, "w", encoding="utf-8") as log, contextlib.redirect_stdout(log):
            return run_job(job_path, result_path, detector=ByNameDetector())

    fake.render = render
    fake.execute = execute
    auto_crop = lua.eval("require('FramePilotAutoCrop')")
    return fake, auto_crop, subjects


def add_photo(lua, fake, **spec):
    photo = fake.makePhoto(lua.table_from(spec))
    fake.photos[len(fake.photos) + 1] = photo
    return photo


def run_auto_crop(lua, auto_crop):
    auto_crop.run(lua.eval("{ addCleanupHandler = function() end }"))


class TestAutoCropFlow:
    """Runs the full plugin flow against the fake SDK and the real engine."""

    @pytest.fixture
    def harness(self, lua, tmp_path):
        return make_auto_crop_harness(lua, tmp_path)

    def add_photo(self, lua, fake, **spec):
        return add_photo(lua, fake, **spec)

    def run(self, lua, auto_crop):
        run_auto_crop(lua, auto_crop)

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

        (run_dir,) = run_folders(tmp_path, "autocrop")
        job = json.loads((run_dir / "job.json").read_text(encoding="utf-8"))
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
            _, log_path = split_command(command)
            Path(log_path).write_text("Traceback: model missing", encoding="utf-8")
            return 1

        fake.execute = failing_execute
        self.add_photo(lua, fake, id=1, name="hero")

        self.run(lua, auto_crop)

        messages = lua_table_to_python(fake.messages)
        assert "exit code 1" in messages[0]["message"]
        assert "model missing" in messages[0]["info"]
        assert len(fake.applied) == 0


class TestRunLogs:
    """Each run's job, results and logs outlive the temp folder."""

    @pytest.fixture
    def harness(self, lua, tmp_path):
        return make_auto_crop_harness(lua, tmp_path)

    def run(self, lua, auto_crop):
        run_auto_crop(lua, auto_crop)

    def test_run_folder_keeps_job_results_and_logs(self, lua, harness, tmp_path):
        fake, auto_crop, subjects = harness
        subjects["hero"] = (0.45, 0.1, 0.55, 0.9)
        add_photo(lua, fake, id=1, name="hero", develop=lua.table_from({"orientation": "BC"}))

        self.run(lua, auto_crop)

        (run_dir,) = run_folders(tmp_path, "autocrop")
        assert {"job.json", "result.tsv", "engine.log", "plugin.log"} <= {p.name for p in run_dir.iterdir()}
        engine_log = (run_dir / "engine.log").read_text(encoding="utf-8")
        assert "photo 1: orientation BC" in engine_log
        plugin_log = (run_dir / "plugin.log").read_text(encoding="utf-8")
        assert "FramePilot plugin 0.2.0" in plugin_log
        assert "Photo 1 hero: orientation BC" in plugin_log
        assert "Cropped 1 photo to 4:5." in plugin_log
        summary = lua_table_to_python(fake.messages)[0]
        assert f"Logs: {run_dir}" in summary["info"]

    def test_engine_failure_names_log_folder(self, lua, harness, tmp_path):
        fake, auto_crop, _ = harness

        def failing_execute(command):
            _, log_path = split_command(command)
            Path(log_path).write_text("Traceback: model missing", encoding="utf-8")
            return 1

        fake.execute = failing_execute
        add_photo(lua, fake, id=1, name="hero")

        self.run(lua, auto_crop)

        (run_dir,) = run_folders(tmp_path, "autocrop")
        message = lua_table_to_python(fake.messages)[0]
        assert message["style"] == "critical"
        assert str(run_dir) in message["info"]
        assert (run_dir / "engine.log").read_text(encoding="utf-8") == "Traceback: model missing"

    def test_keeps_only_recent_runs(self, lua, harness, tmp_path):
        fake, auto_crop, subjects = harness
        root = log_root(tmp_path)
        for day in range(1, 13):
            old = root / f"202601{day:02d}-120000-autocrop"
            old.mkdir(parents=True)
            (old / "engine.log").write_text("old", encoding="utf-8")
        (root / "notes").mkdir()
        subjects["hero"] = (0.45, 0.1, 0.55, 0.9)
        add_photo(lua, fake, id=1, name="hero")

        self.run(lua, auto_crop)

        remaining = sorted(p.name for p in root.iterdir())
        assert "notes" in remaining
        runs = [name for name in remaining if name != "notes"]
        assert len(runs) == 10
        assert runs[0] == "20260104-120000-autocrop"
        assert not runs[-1].startswith("2026010")

    def test_runs_in_the_same_second_get_separate_folders(self, lua, harness, tmp_path):
        fake, auto_crop, subjects = harness
        subjects["hero"] = (0.45, 0.1, 0.55, 0.9)
        add_photo(lua, fake, id=1, name="hero")
        lua.execute("os.date = function() return '20260927-101010' end")

        self.run(lua, auto_crop)
        self.run(lua, auto_crop)

        names = sorted(p.name for p in log_root(tmp_path).iterdir())
        assert names == ["20260927-101010-autocrop", "20260927-101010-autocrop-2"]


class TestCoreRunFolders:
    """Tests for naming and pruning run folders."""

    def test_run_folder_name(self, core):
        assert core.runFolderName("20260927-141503", "autocrop") == "20260927-141503-autocrop"
        assert core.runFolderName("20260927-141503", "check", 3) == "20260927-141503-check-3"

    def test_prunes_oldest_run_folders_only(self, lua, core):
        names = lua.table_from([
            "20260927-100000-check", "notes", "20260925-090000-autocrop",
            "20260926-090000-autocrop", "20260927-100000-autocrop-2",
        ])
        prune = lua_table_to_python(core.runsToPrune(names, 2))
        assert prune == ["20260925-090000-autocrop", "20260926-090000-autocrop"]

    def test_nothing_to_prune(self, lua, core):
        names = lua.table_from(["20260927-100000-check"])
        assert lua_table_to_python(core.runsToPrune(names, 10)) in ([], {})


class TestCheckSetup:
    """Runs Check Setup against the fake SDK, the real engine and the bundled photo."""

    @pytest.fixture
    def harness(self, lua, tmp_path):
        fake = lua.execute(FAKE_SDK)
        install_file_system(lua, fake, tmp_path)
        fake.prefs = lua.table()
        lua.execute(f"_PLUGIN = {{ path = [[{PLUGIN_DIR}]] }}")

        state = {"detected": True, "version_exit": 0, "jobs": []}

        class TestPhotoDetector:
            def detect_scene(self, image_path):
                people = [
                    Detection(bbox=(0.05, 0.3, 0.3, 0.95), confidence=0.9, label="person"),
                ] if state["detected"] else []
                return SceneDetections(people=people, balls=[], image_size=(0, 0))

        def execute(command):
            args, log_path = split_command(command)
            engine_args = args[2:] if args[1].endswith("engine.py") else args[1:]
            state["engine"] = args[:len(args) - len(engine_args)]
            if engine_args == ["--version"]:
                Path(log_path).write_text(version_text() + "\n", encoding="utf-8")
                return state["version_exit"]
            job_path, result_path = engine_args
            state["jobs"].append(json.loads(Path(job_path).read_text(encoding="utf-8")))
            with open(log_path, "w", encoding="utf-8") as log, contextlib.redirect_stdout(log):
                return run_job(job_path, result_path, detector=TestPhotoDetector())

        fake.execute = execute
        check_setup = lua.eval("require('FramePilotCheckSetup')")
        return fake, check_setup, state

    def run(self, lua, check_setup):
        context = lua.eval("{ addCleanupHandler = function() end }")
        ok, lines = check_setup.run(context)
        report = {line[0]: line[1] if len(line) > 1 else None for line in lua_table_to_python(lines)}
        return ok, report

    def test_passes_and_reports_engine(self, lua, harness):
        fake, check_setup, state = harness

        ok, report = self.run(lua, check_setup)

        assert ok
        message = lua_table_to_python(fake.messages)[0]
        assert message["message"] == "FramePilot is set up correctly."
        assert message["style"] == "info"
        assert report["Engine"].endswith("framepilot-engine (next to the plugin)")
        assert report["Engine version"].startswith("FramePilot engine ")
        assert report["Test photo"].startswith("Subject found (single); crop left ")
        assert report["Plugin"] == "0.2.0"
        assert report["Lightroom"].startswith("14.5")
        for label in ["Engine", "Engine version", "Test photo", "Plugin"]:
            assert f"{label}: {report[label]}" in message["info"]

        photo = state["jobs"][0]["photos"][0]
        assert Path(photo["path"]) == PLUGIN_DIR / "check-photo.jpg"
        assert photo["orientation"] == "AB"

    def test_report_and_engine_output_kept_in_log_folder(self, lua, harness, tmp_path):
        fake, check_setup, _ = harness

        ok, report = self.run(lua, check_setup)

        (run_dir,) = run_folders(tmp_path, "check")
        assert report["Logs"] == str(run_dir)
        assert {"check.txt", "version.txt", "job.json", "result.tsv", "engine.log"} <= {
            p.name for p in run_dir.iterdir()
        }
        check = (run_dir / "check.txt").read_text(encoding="utf-8")
        assert check.startswith("FramePilot is set up correctly.")
        assert "photo check: orientation AB" in (run_dir / "engine.log").read_text(encoding="utf-8")

    def test_no_subject_fails(self, lua, harness):
        fake, check_setup, state = harness
        state["detected"] = False

        ok, report = self.run(lua, check_setup)

        assert not ok
        assert "No subject found" in report["Test photo"]
        message = lua_table_to_python(fake.messages)[0]
        assert message["message"] == "FramePilot setup check failed."
        assert message["style"] == "critical"

    def test_missing_engine_fails(self, lua, harness, tmp_path):
        fake, check_setup, state = harness
        fake.engineExists = False
        lua.execute(f"_PLUGIN = {{ path = [[{tmp_path / 'FramePilot' / 'FramePilot.lrplugin'}]] }}")

        ok, report = self.run(lua, check_setup)

        assert not ok
        assert "Could not find the FramePilot engine" in report["Engine"]
        assert state["jobs"] == []

    def test_source_checkout_engine(self, lua, harness):
        fake, check_setup, state = harness
        fake.engineExists = False
        fake.prefs.pythonPath = "/venv/bin/python"

        ok, report = self.run(lua, check_setup)

        assert ok
        engine_py = PLUGIN_DIR.parent.parent / "engine.py"
        assert report["Engine"] == f"{engine_py} (source checkout)"
        assert state["engine"] == ["/venv/bin/python", str(engine_py)]

    def test_engine_that_wont_start_fails(self, lua, harness):
        fake, check_setup, state = harness
        state["version_exit"] = 1

        ok, report = self.run(lua, check_setup)

        assert not ok
        assert "failed to start (exit code 1)" in report["Engine version"]
        assert state["jobs"] == []

    def test_missing_test_photo_fails(self, lua, harness, tmp_path):
        fake, check_setup, state = harness
        lua.execute(f"_PLUGIN = {{ path = [[{tmp_path / 'FramePilot.lrplugin'}]] }}")

        ok, report = self.run(lua, check_setup)

        assert not ok
        assert "missing from the plugin folder" in report["Test photo"]

    def test_custom_engine_path_is_reported(self, lua, harness):
        fake, check_setup, _ = harness
        fake.prefs.enginePath = "/Custom/framepilot-engine"

        ok, report = self.run(lua, check_setup)

        assert ok
        assert report["Engine"] == "/Custom/framepilot-engine (Plug-in Manager setting)"


class TestPluginManifest:
    """Tests for Info.lua."""

    def test_version_matches_core(self, lua, core):
        source = (PLUGIN_DIR / "Info.lua").read_text(encoding="utf-8")
        info = lua.execute(source)
        version = info.VERSION
        assert f"{version.major}.{version.minor}.{version.revision}" == core.PLUGIN_VERSION

    def test_check_setup_in_both_menus(self, lua):
        info = lua.execute((PLUGIN_DIR / "Info.lua").read_text(encoding="utf-8"))
        library = lua_table_to_python(info.LrLibraryMenuItems)
        export = lua_table_to_python(info.LrExportMenuItems)
        assert {"title": "Check Setup...", "file": "CheckSetupMenuItem.lua"} in library
        assert {"title": "FramePilot: Check Setup...", "file": "CheckSetupMenuItem.lua"} in export
        for item in library + export:
            assert (PLUGIN_DIR / item["file"]).exists()
