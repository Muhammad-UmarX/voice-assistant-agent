import pytest
from unittest.mock import patch, MagicMock
from tools import apps_files
import win32con
import psutil

# TEST FILE / FOLDER OPENING

# Go to the tools.apps_files module and replace the os.startfile that that module is using.
@patch("tools.apps_files.os.startfile")
def test_direct_open(mock_startfile):
    result = apps_files.try_direct_open.func("Stremio")

    mock_startfile.assert_called_once_with("Stremio")

    assert result is True

@patch("tools.apps_files.os.startfile")
def test_direct_open_failure(mock_startfile):
    mock_startfile.side_effect = OSError("File not found")

    result = apps_files.try_direct_open.func("Stremio")

    mock_startfile.assert_called_once_with("Stremio")

    assert result is False

# Bottom - Top Order
@patch("tools.apps_files.glob.glob") # 2nd arg
@patch("tools.apps_files.os.path.isdir") # 1st func arg 
def test_build_shortcut_index(mock_isdir, mock_glob):
    mock_isdir.return_value = True
    mock_glob.return_value = [
        r"C:/StartMenu/Stremio.lnk",
        r"C:/StartMenu/Chrome.lnk"
    ]

    result = apps_files.build_shortcut_index()
    expected = {
        "Stremio": r"C:/StartMenu/Stremio.lnk",
        "Chrome": r"C:/StartMenu/Chrome.lnk"
    }

    assert result == expected

@patch("tools.apps_files.build_shortcut_index")
def test_find_app_shortcut(mock_build_index):
    mock_build_index.return_value = {
        "Stremio": r"C:/StartMenu/Stremio.lnk",
    }

    result = apps_files.find_app_shortcut("Stremio")

    assert result == r"C:/StartMenu/Stremio.lnk"

@patch("tools.apps_files.process.extractOne")
@patch("tools.apps_files.build_shortcut_index")
def test_find_app_shortcut_below_threshold(mock_build_index, mock_extract_one):
    mock_build_index.return_value = {
        "Stremio": r"C:/StartMenu/Stremio.lnk",
    }
    mock_extract_one.return_value = ("Stremio", 40)

    result = apps_files.find_app_shortcut("Chrome")

    assert result is None

@patch("tools.apps_files.build_shortcut_index")
def test_find_app_shortcut_empty_index(mock_build_index):
    mock_build_index.return_value = {}

    result = apps_files.find_app_shortcut("Chrome")

    assert result is None

@patch("tools.apps_files.os.startfile")
@patch("tools.apps_files.find_app_shortcut")
def test_try_shortcut_open(mock_match, mock_startfile):
    mock_match.return_value = r"C:/StartMenu/Stremio.lnk"
    result = apps_files.try_shortcut_open.func("Stremio")

    mock_startfile.assert_called_once_with(r"C:/StartMenu/Stremio.lnk")

    assert result is True

@patch("tools.apps_files.os.startfile")
@patch("tools.apps_files.find_app_shortcut")
def test_try_shortcut_open_no_match(mock_match, mock_startfile):
    mock_match.return_value = None

    result = apps_files.try_shortcut_open.func("Unknown")

    mock_startfile.assert_not_called()

    assert result is False

@patch("tools.apps_files.os.startfile")
@patch("tools.apps_files.find_app_shortcut")
def test_try_shortcut_open_failure(mock_match, mock_startfile):
    mock_match.return_value = r"C:/StartMenu/Stremio.lnk"
    mock_startfile.side_effect = OSError("Could not open shortcut")

    result = apps_files.try_shortcut_open.func("Stremio")

    assert result is False

@patch("tools.apps_files.win32com.client.Dispatch")
def test_search_windows_index(mock_dispatch):
    mock_conn = mock_dispatch.return_value

    mock_rs = MagicMock()
    mock_conn.Execute.return_value = [mock_rs]

    mock_rs.EOF = False
    mock_rs.Fields.Item.return_value.Value = r"C:\Stremio\Stremio.exe"
    mock_rs.MoveNext.side_effect = lambda: setattr(mock_rs, "EOF", True)

    result = apps_files.search_windows_index("Stremio")

    assert result == [r"C:\Stremio\Stremio.exe"]

@patch("tools.apps_files.win32com.client.Dispatch")
def test_search_windows_index_failure(mock_dispatch):
    mock_dispatch.side_effect = Exception("COM error")

    result = apps_files.search_windows_index("Stremio")

    assert result == []

@patch("tools.apps_files.HAVE_WIN32COM", False)
def test_search_windows_index_no_win32com():
    result = apps_files.search_windows_index("Stremio")

    assert result == []

@patch("tools.apps_files.os.startfile")
@patch("tools.apps_files.search_windows_index")
def test_try_index_open(mock_result, mock_startfile):
    mock_result.return_value = [
        r"C:\Downloads\written.txt",
        r"X:\Documents\written.pdf"
    ]
    result = apps_files.try_index_open.func("written.pdf")

    mock_startfile.assert_called_once_with(r"C:\Downloads\written.txt")

    assert result is True

@patch("tools.apps_files.os.startfile")
@patch("tools.apps_files.search_windows_index")
def test_try_index_open_no_results(mock_result, mock_startfile):
    mock_result.return_value = []

    result = apps_files.try_index_open.func("missing.pdf")

    mock_startfile.assert_not_called()

    assert result is False

@patch("tools.apps_files.os.startfile")
@patch("tools.apps_files.search_windows_index")
def test_try_index_open_failure(mock_result, mock_startfile):
    mock_result.return_value = [r"C:\Downloads\written.txt"]
    mock_startfile.side_effect = OSError("Could not open file")

    result = apps_files.try_index_open.func("written.txt")

    assert result is False

@patch("tools.apps_files.os.startfile")
def test_open_web_search(mock_startfile):
    result = apps_files.open_web_search.func("python testing")

    mock_startfile.assert_called_once_with(
        "https://www.google.com/search?q=python+testing"
    )

    assert result is True

@patch("tools.apps_files.os.startfile")
def test_open_web_search_failure(mock_startfile):
    mock_startfile.side_effect = OSError("Could not open browser")

    result = apps_files.open_web_search.func("python testing")

    assert result is False

@patch("tools.apps_files.win32gui.EnumWindows")
@patch("tools.apps_files.win32process.GetWindowThreadProcessId")
@patch("tools.apps_files.win32gui.IsWindowVisible")
def test_find_windows_for_process(mock_visible, mock_get_pid, mock_enum):
    mock_visible.return_value = True
    mock_get_pid.return_value = (123, 100)

    def fake_enum(callback, _):
        callback(10, None)
        callback(20, None)

    mock_enum.side_effect = fake_enum

    result = apps_files.find_windows_for_process(100)

    assert result == [10, 20]

@patch("tools.apps_files.win32gui.PostMessage")
@patch("tools.apps_files.find_windows_for_process")
def test_graceful_close_process(mock_hwnds, mock_postmsg):
    mock_hwnds.return_value = [1001, 1002]

    result = apps_files.graceful_close_process(100)

    assert result is True
    mock_hwnds.assert_called_once_with(100)

    mock_postmsg.assert_any_call(1001, win32con.WM_CLOSE, 0, 0)
    mock_postmsg.assert_any_call(1002, win32con.WM_CLOSE, 0, 0)
    assert mock_postmsg.call_count == 2

@patch("tools.apps_files.psutil.Process")
def test_force_kill_process(mock_psutil_proc):
    mock_proc = mock_psutil_proc.return_value

    result = apps_files.force_kill_process(10)

    assert result is True
    mock_psutil_proc.assert_called_once_with(10)
    mock_proc.kill.assert_called_once()

@patch("tools.apps_files.psutil.Process")
def test_force_kill_process_no_such_process(mock_psutil_proc):
    mock_psutil_proc.side_effect = psutil.NoSuchProcess(10)

    result = apps_files.force_kill_process(10)

    assert result is False

@patch("tools.apps_files.psutil.Process")
def test_force_kill_process_access_denied(mock_psutil_proc):
    mock_proc = mock_psutil_proc.return_value
    mock_proc.kill.side_effect = psutil.AccessDenied(10)

    result = apps_files.force_kill_process(10)

    assert result is False

@patch("tools.apps_files.fuzzy_process.extract")
@patch("tools.apps_files.psutil.process_iter")
def test_find_matching_processes(mock_process_iter, mock_extract):
    mock_process_iter.return_value = [
        MagicMock(info={"pid": 100, "name": "chrome.exe", "exe": r"C:\chrome.exe"}),
        MagicMock(info={"pid": 200, "name": "notepad.exe", "exe": r"C:\notepad.exe"}),
    ]
    mock_extract.return_value = [("chrome.exe", 90, 0)]

    result = apps_files.find_matching_processes("chrome")

    mock_process_iter.assert_called_once_with(["pid", "name", "exe"])

    assert result == [{"pid": 100, "name": "chrome.exe", "exe": r"C:\chrome.exe"}]

@patch("tools.apps_files.win32gui.IsWindowVisible")
@patch("tools.apps_files.win32gui.EnumWindows")
@patch("tools.apps_files.psutil.Process")
@patch("tools.apps_files.win32process.GetWindowThreadProcessId")
@patch("tools.apps_files.win32gui.GetWindowText")
def test_get_running_apps(mock_window_text, mock_get_pid, mock_psutil_proc,
    mock_enum, mock_visible):
    mock_visible.return_value = True
    mock_window_text.return_value = "Google Chrome"
    mock_get_pid.return_value = (123, 100)

    mock_proc = mock_psutil_proc.return_value
    mock_proc.name.return_value = "chrome.exe"

    def fake_enum(callback, _):
        callback(10, None)

    mock_enum.side_effect = fake_enum

    result = apps_files.get_running_apps()

    mock_visible.assert_called_once_with(10)
    mock_window_text.assert_called_once_with(10)
    mock_get_pid.assert_called_once_with(10)
    mock_psutil_proc.assert_called_once_with(100)
    mock_proc.name.assert_called_once_with()

    assert result == [{
        "title": "Google Chrome",
        "process_name": "chrome.exe",
        "pid": 100,
        "hwnd": 10
    }]

@patch("tools.apps_files.get_running_apps")
def test_get_running_apps_tool(mock_get_apps):
    mock_get_apps.return_value = [{
        "title": "Google Chrome",
        "process_name": "chrome.exe",
        "pid": 100,
        "hwnd": 10
    }]

    result = apps_files.get_running_apps_tool()

    mock_get_apps.assert_called_once_with()

    assert result == [{
        "title": "Google Chrome",
        "process_name": "chrome.exe",
        "pid": 100,
        "hwnd": 10
    }]

@patch("tools.apps_files.fuzzy_process.extract")
@patch("tools.apps_files.get_running_apps")
def test_find_matching_apps(mock_get_apps, mock_extract):
    mock_get_apps.return_value = [
        {"title": "Google Chrome", "process_name": "chrome.exe", "pid": 100, "hwnd": 10}
    ]
    mock_extract.return_value = [("Google Chrome chrome.exe", 95, 0)]

    result = apps_files.find_matching_apps("chrome")

    assert result == [
        {"title": "Google Chrome", "process_name": "chrome.exe", "pid": 100, "hwnd": 10}
    ]

@patch("tools.apps_files.psutil.pid_exists")
@patch("tools.apps_files.graceful_close_process")
@patch("tools.apps_files.find_matching_apps")
def test_close_app(mock_matching_apps, mock_graceful, mock_pid_exists):
    mock_matching_apps.return_value = [
        {"title": "Google Chrome", "process_name": "chrome.exe", "pid": 100, "hwnd": 10}
    ]
    mock_graceful.return_value = True
    mock_pid_exists.return_value = False

    result = apps_files.close_app.func("chrome", wait_seconds=0)

    mock_matching_apps.assert_called_once_with("chrome")
    mock_graceful.assert_called_once_with(100)

    assert result == "Google Chrome (PID 100, window): closed gracefully"

@patch("tools.apps_files.psutil.pid_exists")
@patch("tools.apps_files.graceful_close_process")
@patch("tools.apps_files.find_matching_apps")
def test_close_app_still_running(mock_matching_apps, mock_graceful, mock_pid_exists):
    mock_matching_apps.return_value = [
        {"title": "Google Chrome", "process_name": "chrome.exe", "pid": 100, "hwnd": 10}
    ]
    mock_graceful.return_value = True
    mock_pid_exists.return_value = True

    result = apps_files.close_app.func("chrome", wait_seconds=0)

    assert result == (
        "Google Chrome (PID 100, window): close requested, still running "
        "(may be waiting on a dialog — not force-killed automatically)"
    )

@patch("tools.apps_files.force_kill_process")
@patch("tools.apps_files.graceful_close_process")
@patch("tools.apps_files.find_matching_apps")
def test_close_app_no_window_found(mock_matching_apps, mock_graceful, mock_force_kill):
    mock_matching_apps.return_value = [
        {"title": "Google Chrome", "process_name": "chrome.exe", "pid": 100, "hwnd": 10}
    ]
    mock_graceful.return_value = False
    mock_force_kill.return_value = True

    result = apps_files.close_app.func("chrome")

    mock_force_kill.assert_called_once_with(100)

    assert result == "Google Chrome (PID 100, window): force-killed (no window found)"

@patch("tools.apps_files.force_kill_process")
@patch("tools.apps_files.find_matching_apps")
def test_close_app_force(mock_matching_apps, mock_force_kill):
    mock_matching_apps.return_value = [
        {"title": "Google Chrome", "process_name": "chrome.exe", "pid": 100, "hwnd": 10}
    ]
    mock_force_kill.return_value = True

    result = apps_files.close_app.func("chrome", force=True)

    mock_force_kill.assert_called_once_with(100)

    assert result == "Google Chrome (PID 100, window): force-killed"

@patch("tools.apps_files.find_matching_processes")
@patch("tools.apps_files.find_matching_apps")
def test_close_app_not_found(mock_matching_apps, mock_matching_processes):
    mock_matching_apps.return_value = []

    result = apps_files.close_app.func("nonexistent")

    mock_matching_processes.assert_not_called()

    assert result == "No running app or process found matching: nonexistent"

@patch("tools.apps_files.force_kill_process")
@patch("tools.apps_files.find_matching_processes")
@patch("tools.apps_files.find_matching_apps")
def test_close_app_background_fallback(mock_matching_apps, mock_matching_processes, mock_force_kill):
    mock_matching_apps.return_value = []
    mock_matching_processes.return_value = [
        {"pid": 200, "name": "helper.exe", "exe": r"C:\helper.exe"}
    ]
    mock_force_kill.return_value = True

    result = apps_files.close_app.func(
        "helper", force=True, include_background=True
    )

    mock_matching_processes.assert_called_once_with("helper")
    mock_force_kill.assert_called_once_with(200)

    assert result == "helper.exe (PID 200, process): force-killed"

@pytest.fixture
def temp_file(tmp_path):
    file = tmp_path / "test_file.txt"
    file.write_text("This is a text file")

    return file

@patch("tools.apps_files.os.remove")
def test_remove_file(mock_remove, temp_file):  
    result = apps_files.remove_file.func(temp_file)

    assert result == {
        "success": True,
        "path": temp_file
        }

    mock_remove.assert_called_once_with(temp_file)

@patch("tools.apps_files.os.path.isfile")
@patch("tools.apps_files.os.remove")
def test_file_not_found_error(mock_remove, mock_isfile, temp_file):
    mock_isfile.return_value = True
    mock_remove.side_effect = FileNotFoundError("File does not exist")

    result = apps_files.remove_file.func(temp_file)

    assert result == {
            "success": False,
            "path": temp_file,
            "error": "File does not exist"
            }

    mock_isfile.assert_called_once_with(temp_file)
    mock_remove.assert_called_once_with(temp_file)

@patch("tools.apps_files.os.path.isfile")
def test_remove_file_does_not_exist(mock_isfile, temp_file):
    mock_isfile.return_value = False

    result = apps_files.remove_file.func(temp_file)

    assert result == {
        "success": False,
        "path": temp_file,
        "error": "File does not exist"
        }

    mock_isfile.assert_called_once_with(temp_file)

@patch("tools.apps_files.os.path.isfile")
@patch("tools.apps_files.os.remove")
def test_remove_file_permission_error(mock_remove, mock_isfile, temp_file):
    mock_isfile.return_value = True
    mock_remove.side_effect = PermissionError("Permission denied")

    result = apps_files.remove_file.func(temp_file)

    assert result == {
            "success": False,
            "path": temp_file,
            "error": "Permission denied"
            }

    mock_isfile.assert_called_once_with(temp_file)
    mock_remove.assert_called_once_with(temp_file)