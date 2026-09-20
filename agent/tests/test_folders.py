import os
from unittest.mock import patch, MagicMock

import pytest

from tools import folders


@pytest.fixture
def temp_folder(tmp_path):
    directory = tmp_path / "test_directory"
    directory.mkdir()

    return directory

# ==============================================================================================
#                                         OPEN FOLDERS
# ==============================================================================================

@patch("tools.folders.os.startfile")
def test_open_folder_direct(mock_startfile, temp_folder):
    result = folders.open_folder_direct.func(temp_folder)

    mock_startfile.assert_called_once_with(temp_folder)

    assert result is True

@patch("tools.folders.os.startfile")
def test_open_folder_direct_exception(mock_startfile, temp_folder):
    mock_startfile.side_effect = OSError("Failed to open file")

    result = folders.open_folder_direct.func(temp_folder)

    assert result is False    
    mock_startfile.assert_called_once_with(temp_folder)

@patch("tools.folders.os.startfile")
@patch("tools.folders.os.path.isdir")
def test_open_folder_direct_not_a_dir(mock_isdir, mock_startfile):
    mock_isdir.return_value = False

    result = folders.open_folder_direct.func(r"C:\not\a\real\path")

    mock_startfile.assert_not_called()

    # No explicit return when the isdir check fails, so the function
    # falls through to an implicit None rather than False.
    assert result is None

@patch("tools.folders.os.path.expandvars")
@patch("tools.folders.os.path.expanduser")
def test_get_common_folder_shortcuts(mock_expanduser, mock_expandvars):
    mock_expanduser.return_value = r"C:\Users\Test"
    mock_expandvars.side_effect = lambda v: {
        r"%APPDATA%": r"C:\Users\Test\AppData\Roaming",
        r"%ProgramFiles%": r"C:\Program Files",
        r"%TEMP%": r"C:\Users\Test\AppData\Local\Temp",
    }[v]

    result = folders.get_common_folder_shortcuts()

    assert result["documents"] == os.path.join(r"C:\Users\Test", "Documents")
    assert result["downloads"] == os.path.join(r"C:\Users\Test", "Downloads")
    assert result["appdata"] == r"C:\Users\Test\AppData\Roaming"
    assert result["this pc"] == "shell:MyComputerFolder"

@patch("tools.folders.os.startfile")
@patch("tools.folders.get_common_folder_shortcuts")
def test_open_known_folder(mock_get_shortcuts, mock_startfile):
    mock_get_shortcuts.return_value = {
        "documents": r"C:\test\Documents",
        "downloads": r"C:\test\Downloads",
        "desktop": r"C:\test\Desktop"
    }

    result = folders.open_known_folder.func("Downloads")

    assert result is True
    mock_get_shortcuts.assert_called_once()
    mock_startfile.assert_called_once_with(r"C:\test\Downloads")

@patch("tools.folders.os.startfile")
@patch("tools.folders.get_common_folder_shortcuts")
def test_open_known_folder_error(mock_get_shortcuts, mock_startfile):
    mock_get_shortcuts.return_value = {
        "documents": r"C:\test\Documents",
        "downloads": r"C:\test\Downloads",
        "desktop": r"C:\test\Desktop"
    }
    mock_startfile.side_effect = OSError("Failed to open file")

    result = folders.open_known_folder.func("Downloads")

    assert result is False
    mock_startfile.assert_called_once_with(r"C:\test\Downloads")

@patch("tools.folders.os.startfile")
@patch("tools.folders.get_common_folder_shortcuts")
def test_open_known_folder_no_match(mock_get_shortcuts, mock_startfile):
    mock_get_shortcuts.return_value = {
        "documents": r"C:\test\Documents",
        "downloads": r"C:\test\Downloads",
    }

    result = folders.open_known_folder.func("xyzzyqqq", threshold=70)

    mock_startfile.assert_not_called()

    assert result is False

# NOTE: the source module only does `import win32com.client` — there is no
# bare `win32` name bound anywhere in tools/folders.py. Patching
# "tools.folders.win32.client.Dispatch" raises AttributeError before the
# test body ever runs. The correct target is "tools.folders.win32com.client.Dispatch",
# same as test_close_folder_by_path below.

@patch("tools.folders.win32com.client.Dispatch")
def test_search_folder_via_index(mock_dispatch):
    mock_conn = mock_dispatch.return_value
    mock_rs = MagicMock()
    mock_conn.Execute.return_value = [mock_rs]
    mock_rs.EOF = False
    mock_rs.Fields.Item.return_value.Value = r"C:\Downloads"
    mock_rs.MoveNext.side_effect = lambda: setattr(mock_rs, "EOF", True)

    result = folders.search_folder_via_index("Downloads")

    assert result == [r"C:\Downloads"]

@patch("tools.folders.win32com.client.Dispatch")
def test_search_folder_via_index_exception(mock_dispatch):
    mock_dispatch.side_effect = Exception("COM Error")

    result = folders.search_folder_via_index("Downloads")

    assert result == []

@patch("tools.folders.os.startfile")
@patch("tools.folders.search_folder_via_index")
def test_open_folder_via_index(mock_search, mock_startfile):
    mock_search.return_value = ["C:\\Downloads"]

    result = folders.open_folder_via_index.func("Downloads")

    assert result is True
    mock_startfile.assert_called_once_with("C:\\Downloads")

@patch("tools.folders.os.startfile")
@patch("tools.folders.search_folder_via_index")
def test_open_folder_via_index_no_results(mock_search, mock_startfile):
    mock_search.return_value = []

    result = folders.open_folder_via_index.func("NonexistentFolder")

    mock_startfile.assert_not_called()

    assert result is False

@patch("tools.folders.os.startfile")
@patch("tools.folders.search_folder_via_index")
def test_open_folder_via_index_failure(mock_search, mock_startfile):
    mock_search.return_value = ["C:\\Downloads"]
    mock_startfile.side_effect = OSError("Could not open folder")

    result = folders.open_folder_via_index.func("Downloads")

    assert result is False

# ==============================================================================================
#                                         CLOSE FOLDERS
# ==============================================================================================

# NOTE: close_folder_by_path is @tool-decorated, so it must be called via
# .func(...) — calling the StructuredTool object directly raises
# TypeError: 'StructuredTool' object is not callable.

@patch("tools.folders.win32com.client.Dispatch")
def test_close_folder_by_path(mock_dispatch):
    mock_shell = mock_dispatch.return_value

    mock_window = MagicMock()
    mock_window.HWND = 1234

    mock_shell.Windows.return_value = [mock_window]

    result = folders.close_folder_by_path.func(1234)

    assert result == 1
    mock_window.Quit.assert_called_once_with()

@patch("tools.folders.win32com.client.Dispatch")
def test_close_folder_by_path_no_match(mock_dispatch):
    mock_shell = mock_dispatch.return_value

    mock_window = MagicMock()
    mock_window.HWND = 9999

    mock_shell.Windows.return_value = [mock_window]

    result = folders.close_folder_by_path.func(1234)

    assert result == 0
    mock_window.Quit.assert_not_called()

@patch("tools.folders.win32com.client.Dispatch")
def test_close_folder_by_path_skips_errored_window(mock_dispatch):
    mock_shell = mock_dispatch.return_value

    class BadWindow:
        @property
        def HWND(self):
            raise Exception("Could not read HWND")

    good_window = MagicMock()
    good_window.HWND = 1234

    mock_shell.Windows.return_value = [BadWindow(), good_window]

    result = folders.close_folder_by_path.func(1234)

    assert result == 1
    good_window.Quit.assert_called_once_with()

# ==============================================================================================
#                                          LIST DRIVES
# ==============================================================================================

@patch("tools.folders.windll")
def test_list_drives(mock_windll):
    # Bit position corresponds to letter position in A-Z, so C: is bit 2, D: is bit 3.
    mock_windll.kernel32.GetLogicalDrives.return_value = 0b1100
    mock_windll.kernel32.GetDriveTypeW.return_value = 3

    def fake_get_volume_info(path, buf, size, *args):
        buf.value = "OS" if path == "C:\\" else "Data"
        return True

    mock_windll.kernel32.GetVolumeInformationW.side_effect = fake_get_volume_info

    result = folders.list_drives.func()

    assert result == [
        {"path": "C:\\", "label": "OS"},
        {"path": "D:\\", "label": "Data"}
    ]

@patch("tools.folders.windll")
def test_list_drives_no_label(mock_windll):
    # Bit 2 -> C: (A is bit 0, B is bit 1, C is bit 2)
    mock_windll.kernel32.GetLogicalDrives.return_value = 0b100
    mock_windll.kernel32.GetDriveTypeW.return_value = 2

    def fake_get_volume_info(path, buf, size, *args):
        buf.value = ""  # unreadable/unassigned volume label
        return False

    mock_windll.kernel32.GetVolumeInformationW.side_effect = fake_get_volume_info

    result = folders.list_drives.func()

    assert result == [{"path": "C:\\", "label": "NONE"}]
    
# ==============================================================================================
#                                     FIND/LIST DIRECTORIES
# ==============================================================================================

@patch("tools.folders.os.listdir")
@patch("tools.folders.os.path.isdir")
def test_list_subdirs(mock_isdir, mock_listdir):
    def fake_isdir(path):
        return not path.endswith("file.txt")

    mock_isdir.side_effect = fake_isdir
    mock_listdir.return_value = ["FolderA", "file.txt", "FolderB"]

    result = folders.list_subdirs(r"C:\Test")

    assert result == {
        "path": r"C:\Test",
        "subdirs": ["FolderA", "FolderB"]
    }

@patch("tools.folders.os.path.isdir")
def test_list_subdirs_invalid_path(mock_isdir):
    mock_isdir.return_value = False

    result = folders.list_subdirs(r"C:\Nonexistent")

    assert result == {
        "path": r"C:\Nonexistent",
        "subdirs": [],
        "error": "Path does not exist or is not a directory"
    }

@patch("tools.folders.os.listdir")
@patch("tools.folders.os.path.isdir")
def test_list_subdirs_permission_error(mock_isdir, mock_listdir):
    mock_isdir.return_value = True
    mock_listdir.side_effect = PermissionError("Access denied")

    result = folders.list_subdirs(r"C:\Restricted")

    assert result == {
        "path": r"C:\Restricted",
        "subdirs": [],
        "error": "Permission denied"
    }

@patch("tools.folders.list_subdirs")
def test_list_subdirs_tool(mock_list_subdirs):
    mock_list_subdirs.return_value = {
        "path": r"C:\Test",
        "subdirs": ["FolderA", "FolderB"]
    }

    result = folders.list_subdirs_tool.func(r"C:\Test")

    mock_list_subdirs.assert_called_once_with(r"C:\Test")

    assert result == {
        "path": r"C:\Test",
        "subdirs": ["FolderA", "FolderB"]
    }

@patch("tools.folders.list_subdirs")
def test_find_directory(mock_list_subdirs):
    mock_list_subdirs.side_effect = [
        {
            "path": r"C:/",
            "subdirs": ["Downloads"]
        },
        # The 2nd result mocks the recursive call inside C:/Downloads
        # Helps exit from recursion when no further subdir is found i.e. "subdir": []
        {
            "path": r"C:/Downloads",
            "subdirs": []
        }
    ]

    result = folders.find_directory.func("Downloads", r"C:/")

    assert result["found"] is True
    assert result["path"] == r"C:/Downloads"
    assert result["candidates"] == []

@patch("tools.folders.list_subdirs")
def test_find_directory_not_found(mock_list_subdirs):
    mock_list_subdirs.return_value = {
        "path": r"C:/",
        "subdirs": ["Music", "Pictures"]
    }

    result = folders.find_directory.func("Invoices", r"C:/", max_depth=0)

    assert result["found"] is False
    assert result["path"] is None
    assert result["candidates"] == []

@patch("tools.folders.list_subdirs")
def test_find_directory_multiple_candidates(mock_list_subdirs):
    mock_list_subdirs.side_effect = [
        {
            "path": r"C:/",
            "subdirs": ["Invoices", "Invoices_old"]
        },
        {
            "path": r"C:/Invoices",
            "subdirs": []
        },
        {
            "path": r"C:/Invoices_old",
            "subdirs": []
        }
    ]

    result = folders.find_directory.func("Invoices", r"C:/")

    assert result["found"] is True
    assert result["path"] == r"C:/Invoices"
    assert result["candidates"] == [r"C:/Invoices_old"]

@patch("tools.folders.list_subdirs")
def test_find_directory_skips_inaccessible_dir(mock_list_subdirs):
    mock_list_subdirs.side_effect = [
        {
            "path": r"C:/",
            "subdirs": ["Restricted"]
        },
        {
            "path": r"C:/Restricted",
            "subdirs": [],
            "error": "Permission denied"
        }
    ]

    result = folders.find_directory.func("Invoices", r"C:/")

    assert result["found"] is False
    assert result["path"] is None

# ==============================================================================================
#                                     CREATE/REMOVE DIRECTORIES
# ==============================================================================================

@patch("tools.folders.os.mkdir")
@patch("tools.folders.os.path.isdir")
def test_create_directory(mock_isdir, mock_mkdir):
    mock_isdir.return_value = True

    result = folders.create_directory.func(r"C:\Test", "NewFolder")

    expected_path = os.path.join(r"C:\Test", "NewFolder")
    mock_mkdir.assert_called_once_with(expected_path)

    assert result == {
        "success": True,
        "path": expected_path
    }

@patch("tools.folders.os.path.isdir")
def test_create_directory_parent_missing(mock_isdir):
    mock_isdir.return_value = False

    result = folders.create_directory.func(r"C:\Nonexistent", "NewFolder")

    assert result == {
        "success": False,
        "error": "Parent directory does not exist",
        "path": r"C:\Nonexistent"
    }

@patch("tools.folders.os.mkdir")
@patch("tools.folders.os.path.isdir")
def test_create_directory_permission_error(mock_isdir, mock_mkdir):
    mock_isdir.return_value = True
    mock_mkdir.side_effect = PermissionError("Access denied")

    result = folders.create_directory.func(r"C:\Test", "NewFolder")

    expected_path = os.path.join(r"C:\Test", "NewFolder")

    assert result == {
        "success": False,
        "error": "Access denied",
        "path": expected_path
    }

@patch("tools.folders.os.mkdir")
@patch("tools.folders.os.path.isdir")
def test_create_directory_already_exists(mock_isdir, mock_mkdir):
    mock_isdir.return_value = True
    mock_mkdir.side_effect = FileExistsError("Directory exists")

    result = folders.create_directory.func(r"C:\Test", "NewFolder")

    expected_path = os.path.join(r"C:\Test", "NewFolder")

    assert result == {
        "success": False,
        "error": "Directory exists",
        "path": expected_path
    }

@patch("tools.folders.os.rmdir")
@patch("tools.folders.os.listdir")
@patch("tools.folders.os.path.isdir")
def test_remove_dir_empty(mock_isdir, mock_listdir, mock_rmdir):
    mock_isdir.return_value = True
    mock_listdir.return_value = []

    result = folders.remove_dir.func(r"C:\EmptyFolder")

    mock_rmdir.assert_called_once_with(r"C:\EmptyFolder")

    assert result == {
        "success": True,
        "path": r"C:\EmptyFolder"
    }

@patch("tools.folders.shutil.rmtree")
@patch("tools.folders.os.listdir")
@patch("tools.folders.os.path.isdir")
def test_remove_dir_non_empty(mock_isdir, mock_listdir, mock_rmtree):
    mock_isdir.return_value = True
    mock_listdir.return_value = ["file.txt"]

    result = folders.remove_dir.func(r"C:\FullFolder")

    mock_rmtree.assert_called_once_with(r"C:\FullFolder")

    assert result == {
        "success": True,
        "path": r"C:\FullFolder"
    }

@patch("tools.folders.os.path.isdir")
def test_remove_dir_not_found(mock_isdir):
    mock_isdir.return_value = False

    result = folders.remove_dir.func(r"C:\Nonexistent")

    assert result == {
        "success": False,
        "error": "Directory does not exist",
        "path": r"C:\Nonexistent"
    }

@patch("tools.folders.os.rmdir")
@patch("tools.folders.os.listdir")
@patch("tools.folders.os.path.isdir")
def test_remove_dir_permission_error(mock_isdir, mock_listdir, mock_rmdir):
    mock_isdir.return_value = True
    mock_listdir.return_value = []
    mock_rmdir.side_effect = PermissionError("Access denied")

    result = folders.remove_dir.func(r"C:\Locked")

    assert result == {
        "success": False,
        "error": "Access denied",
        "path": r"C:\Locked"
    }

@patch("tools.folders.os.rmdir")
@patch("tools.folders.os.listdir")
@patch("tools.folders.os.path.isdir")
def test_remove_dir_file_not_found_error(mock_isdir, mock_listdir, mock_rmdir):
    mock_isdir.return_value = True
    mock_listdir.return_value = []
    mock_rmdir.side_effect = FileNotFoundError("Directory not found")

    result = folders.remove_dir.func(r"C:\Vanished")

    assert result == {
        "success": False,
        "error": "Directory not found",
        "path": r"C:\Vanished"
    }