import os
import logging
import string
import ctypes
from ctypes import windll
import shutil
import pythoncom

from rapidfuzz import process
from rapidfuzz import process as fuzzy_process
import win32com.client

try:
    import win32com.client
    HAVE_WIN32COM = True
except ImportError:
    HAVE_WIN32COM = False

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# ==============================================================================================
#                                         OPEN FOLDERS
# ==============================================================================================

@tool
def open_folder_direct(path: str) -> bool:
    """Strategy 1: path is already exact and valid."""

    logger.debug("Attempting direct open for %s", os.path.basename(path))

    try:
        if os.path.isdir(path):
            os.startfile(path)

            logger.info("Direct open succeeded for %s", os.path.basename(path))
            return True
        
    except Exception:
        logger.exception("Direct open failed for %s", os.path.basename(path))
        # raise 
        return False


def get_common_folder_shortcuts() -> dict:
    """Well-known folders users refer to by short names."""

    logger.debug("Building common folder shortcuts")

    home = os.path.expanduser("~")

    shortcuts = {
        "documents": os.path.join(home, "Documents"),
        "downloads": os.path.join(home, "Downloads"),
        "desktop": os.path.join(home, "Desktop"),
        "pictures": os.path.join(home, "Pictures"),
        "music": os.path.join(home, "Music"),
        "videos": os.path.join(home, "Videos"),
        "appdata": os.path.expandvars(r"%APPDATA%"),
        "programfiles": os.path.expandvars(r"%ProgramFiles%"),
        "temp": os.path.expandvars(r"%TEMP%"),
        "c drive": r"C:\\",
        "this pc": "shell:MyComputerFolder",
    }

    logger.debug("Built %d common folder shortcuts", len(shortcuts))

    return shortcuts


@tool
def open_known_folder(name: str, threshold: int = 70) -> bool:
    """Strategy 2: match against well-known folder aliases (fuzzy)."""

    logger.debug("Attempting known folder open for %s", name)

    shortcuts = get_common_folder_shortcuts()

    match = process.extractOne(name.lower(), shortcuts.keys())

    if match and match[1] >= threshold:
        matched_name = match[0]
        logger.debug(
            "Known folder match found: %s (score: %s)",
            matched_name,
            match[1]
        )

        try:
            os.startfile(shortcuts[matched_name])

            logger.info("Known folder opened successfully for %s", name)
            return True

        except OSError:
            logger.exception("Failed to open known folder %s", matched_name)
            # raise
            return False

    logger.debug(
        "No known folder match found for %s above threshold %s",
        name,
        threshold
    )
    return False


def search_folder_via_index(name: str, limit: int = 5) -> list:
    """Search Windows Search Index for folders matching the given name."""

    logger.debug(
        "Searching Windows index for folder %s with limit %d",
        name,
        limit
    )

    pythoncom.CoInitialize()

    try:
        conn = win32com.client.Dispatch("ADODB.Connection")

        conn.Open(
            "Provider=Search.CollatorDSO;"
            "Extended Properties='Application=Windows';"
        )

        sql = f"""
            SELECT TOP {limit} System.ItemPathDisplay FROM SYSTEMINDEX
            WHERE System.FileName LIKE '%{name}%'
            AND System.Kind = 'folder'
            ORDER BY System.DateModified DESC
        """

        rs = conn.Execute(sql)[0]
        results = []

        while not rs.EOF:
            results.append(
                rs.Fields.Item("System.ItemPathDisplay").Value
            )
            rs.MoveNext()

        conn.Close()

        logger.debug(
            "Windows index folder search completed with %d results",
            len(results)
        )

        return results

    except Exception:
        logger.exception(
            "Windows index folder search failed for %s",
            name
        )
        return []

    finally:
        pythoncom.CoUninitialize()


@tool
def open_folder_via_index(name: str) -> bool:
    """Strategy 3: query Windows Search Index for FOLDERS (not files) matching name."""

    logger.debug("Attempting Windows index folder open for %s", name)

    results = search_folder_via_index(name)

    if not results:
        logger.debug("No matching folders found in Windows index for %s", name)
        return False

    logger.debug("Opening Windows index result: %s", results[0])

    try:
        os.startfile(results[0])

        logger.info("Windows index folder opened successfully for %s", name)
        return True

    except OSError:
        logger.exception(
            "Failed to open Windows index folder %s",
            results[0]
        )
        # raise
        return False


# ==============================================================================================
#                                         CLOSE FOLDERS
# ==============================================================================================

@tool
def list_open_folders() -> list[dict]:
    """
    List all File Explorer windows that are currently open.

    Use this before close_folder_by_path to find the HWND of the
    window you want to close.

    Returns:
        list[dict]: One entry per open Explorer window:
            {"hwnd": 123456, "path": "C:\\Users\\You\\Documents", "name": "Documents"}
    """

    logger.debug("Listing open File Explorer windows")

    if not HAVE_WIN32COM:
        logger.warning("win32com unavailable, skipping Explorer window search")
        return []

    pythoncom.CoInitialize()

    try:
        shell = win32com.client.Dispatch("Shell.Application")
        results = []

        for window in shell.Windows():
            try:
                # Shell.Windows() can also include Internet Explorer windows
                if os.path.basename(window.FullName).lower() != "explorer.exe":
                    continue

                results.append({
                    "hwnd": window.HWND,
                    "path": window.Document.Folder.Self.Path,
                    "name": window.LocationName,
                })

            except Exception:
                # Some windows raise errors while loading or closing; skip them
                continue

        logger.info("Found %d open File Explorer window(s)", len(results))
        return results
    
    finally:
        pythoncom.CoUninitialize()

@tool
def close_folder_by_path(target_path_handler: int):
    """
    Close one or more open File Explorer windows whose folder HWND matches
    the given target path's HWND or partial path.

    Use this tool to close a specific open folder once you know its real
    path — typically after calling list_open_folders first to confirm
    what's actually open and get the correct path to match against.

    Args:
        target_path_handler (int): The path's handler (HWND) for the unique
            identification of the window/s currently open.

    Returns:
        int: The number of windows that were closed.
    """

    logger.debug(
        "Attempting to close File Explorer window with HWND %s",
        target_path_handler
    )

    if not HAVE_WIN32COM:
        logger.warning("win32com unavailable, skipping Explorer window close")
        return 0

    pythoncom.CoInitialize()

    try:
        shell = win32com.client.Dispatch("Shell.Application")
        windows = shell.Windows()

        closed = 0

        for window in list(windows):
            try:
                path_handler = window.HWND

                if target_path_handler == path_handler:
                    window.Quit()
                    closed += 1

            except Exception:
                continue

        if closed:
            logger.info(
                "Closed %d File Explorer window(s) with HWND %s",
                closed,
                target_path_handler
            )
        else:
            logger.debug(
                "No File Explorer window found with HWND %s",
                target_path_handler
            )

        return closed

    finally:
        pythoncom.CoUninitialize()

# ==============================================================================================
#                                          LIST DRIVES
# ==============================================================================================

@tool
def list_drives() -> list[dict]:
    """
    Get a list of all available drives on the system.

    Scans drive letters A-Z and returns information for each one
    currently mounted, including its path and volume label.

    Returns:
        list[dict]: A list of drives, each represented as:
            {"path": "C:\\", "label": "Windows"}
            A label of "NONE" means the drive has no assigned name
            or its volume information could not be read.
    """

    logger.debug("Scanning system for available drives")

    bitmask = windll.kernel32.GetLogicalDrives()
    drives = []

    for letter in string.ascii_uppercase:
        if bitmask & 1:
            path = f"{letter}:\\"
            dtype = windll.kernel32.GetDriveTypeW(path)

            volume_name = ctypes.create_unicode_buffer(1024)

            windll.kernel32.GetVolumeInformationW(
                path,
                volume_name,
                1024,
                None,
                None,
                None,
                None,
                1024
            )

            label = volume_name.value or "NONE"

            drives.append({
                "path": path,
                "label": label
            })

            logger.debug(
                "Detected drive %s with label %s",
                path,
                label
            )

        bitmask >>= 1

    logger.info("Drive scan completed: found %d drive(s)", len(drives))

    return drives

# ==============================================================================================
#                                     FIND/LIST DIRECTORIES
# ==============================================================================================

def list_subdirs(path: str) -> dict:
    """List immediate subdirectories inside a directory."""

    path = os.path.normpath(path.strip().strip('"'))

    logger.debug("Listing subdirectories in %s", path)

    if not os.path.isdir(path):
        logger.warning("Path does not exist or is not a directory: %s", path)
        return {
            "path": path,
            "subdirs": [],
            "error": "Path does not exist or is not a directory"
        }

    try:
        entries = os.listdir(path)

    except PermissionError:
        logger.warning("Permission denied while listing %s", path)
        return {
            "path": path,
            "subdirs": [],
            "error": "Permission denied"
        }

    subdirs = [
        name for name in entries
        if os.path.isdir(os.path.join(path, name))
    ]

    logger.debug(
        "Found %d subdirectories in %s",
        len(subdirs),
        path
    )

    return {
        "path": path,
        "subdirs": sorted(subdirs)
    }


@tool
def list_subdirs_tool(path: str):
    """
        List immediate subdirectories inside a given directory path.

        Args:
            path: Absolute path to a directory to inspect.

        Returns:
            dict with:
                - "path": the path that was inspected (normalized)
                - "subdirs": list of subdirectory names (not full paths) found
                  directly inside it, one level deep only
                - "error": present only if the path is invalid or inaccessible
    """

    logger.debug("Tool request: list subdirectories in %s", path)

    result = list_subdirs(path)

    logger.info(
        "Listed subdirectories for %s",
        result["path"]
    )

    return result


@tool
def find_directory(target_name: str, start_path: str, max_depth: int = 5, threshold: int = 70) -> dict:
    """
    Search for a directory by (fuzzy) name, starting from start_path and
    descending into subdirectories up to max_depth levels.

    Args:
        target_name: The folder name to search for, e.g. "Invoices" or "project_x".
        start_path: Where to begin searching, e.g. r"C:\\Users\\You".
        max_depth: How many levels deep to search before giving up (keeps
                   this from wandering into huge, irrelevant trees).
        threshold: Fuzzy match score (0-100) required to count as a match.

    Returns:
        dict with:
            - "found": bool
            - "path": full path to the best match, if found
            - "candidates": other close matches found along the way, if any
    """

    logger.debug(
        "Searching for directory %s from %s "
        "(max_depth=%d, threshold=%d)",
        target_name,
        start_path,
        max_depth,
        threshold
    )

    best_match = None
    best_score = 0
    other_candidates = []

    def _search(current_path: str, depth: int):
        nonlocal best_match, best_score

        if depth > max_depth:
            return

        result = list_subdirs(current_path)

        if "error" in result:
            logger.debug(
                "Skipping inaccessible directory %s: %s",
                current_path,
                result["error"]
            )
            return

        for name in result["subdirs"]:
            score = fuzzy_process.extractOne(
                target_name,
                [name]
            )[1]

            full_path = os.path.join(current_path, name)

            if score >= threshold:
                logger.debug(
                    "Directory candidate found: %s (score=%s)",
                    full_path,
                    score
                )

                if score > best_score:
                    if best_match:
                        other_candidates.append(best_match)

                    best_match = full_path
                    best_score = score

                    logger.debug(
                        "New best directory match: %s (score=%s)",
                        best_match,
                        best_score
                    )

                else:
                    other_candidates.append(full_path)

            # Keep descending regardless, in case a better match is deeper.
            _search(full_path, depth + 1)

    _search(start_path, depth=0)

    result = {
        "found": best_match is not None,
        "path": best_match,
        "candidates": other_candidates
    }

    if best_match:
        logger.info(
            "Directory search succeeded for %s: %s (score=%s)",
            target_name,
            best_match,
            best_score
        )
    else:
        logger.info(
            "No directory match found for %s starting from %s",
            target_name,
            start_path
        )

    return result

# ==============================================================================================
#                                     CREATE/REMOVE DIRECTORIES
# ==============================================================================================

@tool
def create_directory(path: str, name: str) -> dict:
    """Create a directory {name} at a path.
    The path may be provided by the user or returned and passed by another function."""

    logger.debug(
        "Attempting to create directory %s in %s",
        name,
        path
    )

    if not os.path.isdir(path):
        logger.warning(
            "Cannot create directory %s: parent directory does not exist: %s",
            name,
            path
        )

        return {
            "success": False,
            "error": "Parent directory does not exist",
            "path": path
        }

    new_path = os.path.join(path, name)

    try:
        os.mkdir(new_path)

        logger.info("Directory created successfully: %s", new_path)

        return {
            "success": True,
            "path": new_path
        }

    except PermissionError as pe:
        logger.warning(
            "Permission denied creating directory %s: %s",
            new_path,
            pe
        )

        return {
            "success": False,
            "error": str(pe),
            "path": new_path
        }

    except FileExistsError as fe:
        logger.warning(
            "Directory already exists: %s",
            new_path
        )

        return {
            "success": False,
            "error": str(fe),
            "path": new_path
        }


@tool
def remove_dir(path: str) -> dict:
    """Remove the directory at {path}.

    Arguments:
        path: valid path to the directory that needs to be deleted
    """

    logger.debug("Attempting to remove directory: %s", path)

    if not os.path.isdir(path):
        logger.warning(
            "Cannot remove directory because it does not exist: %s",
            path
        )

        return {
            "success": False,
            "error": "Directory does not exist",
            "path": path
        }

    try:
        if not os.listdir(path):
            logger.debug("Directory is empty, using os.rmdir: %s", path)
            os.rmdir(path)

        else:
            logger.debug("Directory is not empty, using shutil.rmtree: %s", path)
            shutil.rmtree(path)

        logger.info("Directory removed successfully: %s", path)

        return {
            "success": True,
            "path": path
        }

    except PermissionError as pe:
        logger.warning(
            "Permission denied removing directory %s: %s",
            path,
            pe
        )

        return {
            "success": False,
            "error": str(pe),
            "path": path
        }

    except FileNotFoundError as fe:
        logger.warning(
            "Directory was not found while removing %s: %s",
            path,
            fe
        )

        return {
            "success": False,
            "error": str(fe),
            "path": path
        }