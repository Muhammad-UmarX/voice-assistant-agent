import glob
import logging
import os
import time
import psutil
from functools import lru_cache

try:
    from rapidfuzz import process
    HAVE_RAPIDFUZZ = True
except ImportError:
    HAVE_RAPIDFUZZ = False

try:
    import win32com.client
    HAVE_WIN32COM = True
except ImportError:
    HAVE_WIN32COM = False

from langchain_core.tools import tool
from rapidfuzz import process as fuzzy_process

import win32gui
import win32process
import win32con

logger = logging.getLogger(__name__)

# ==============================================================================================
#                                      OPEN APPS/FILES
# ==============================================================================================

@tool
def try_direct_open(name: str):
    """Try to open an application or file directly using its provided name or path."""
    logger.debug("Attempting direct open for %s", name)

    try:
        os.startfile(name)

        logger.info("Direct open succeeded for %s", name)
        return True
    
    except OSError:
        logger.exception("Direct open failed for %s", name)

        return False
        # raise

# ---------- Strategy 2: Start Menu shortcut search ----------

SHORTCUT_DIRS = [
    r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs",
    os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
    os.path.join(os.path.expanduser("~"), "Desktop"),
]

@lru_cache(maxsize=1)
def build_shortcut_index() -> dict:
    """Scan Start Menu folders once and cache {display_name: path}."""
    index = {}

    logger.debug("Building shortcut index")
    for base in SHORTCUT_DIRS:
        if not os.path.isdir(base):
            continue
        for path in glob.glob(os.path.join(base, "**", "*.lnk"), recursive=True):

            # os.path.basename(path): path/file.ext = file.txt
            # os.path.splitext(file.txt) = (file, .txt)

            display_name = os.path.splitext(os.path.basename(path))[0]
            index[display_name] = path

    logger.info("Shortcut index built successfully")

    return index

def find_app_shortcut(name: str, threshold: int = 60):
    logger.debug("Searching for shortcut matching %s", name)

    index = build_shortcut_index()
    if not index:
        logger.debug("Shortcut index is empty")
        return None

    if HAVE_RAPIDFUZZ:
        logger.debug("Using RapidFuzz for shortcut matching")
        result = process.extractOne(name, index.keys())

        # result = (key, similarity_score)
        if result and result[1] >= threshold:
            logger.debug(
                "Shortcut match found: %s with score %s",
                result[0],
                result[1]
            )
            return index[result[0]]

        logger.debug("No shortcut match met threshold %s", threshold)
        return None
    
    else:
        logger.debug("RapidFuzz unavailable, using substring matching")

        # Crude fallback without rapidfuzz: substring match
        name_lower = name.lower()

        for display_name, path in index.items():
            if name_lower in display_name.lower():
                logger.debug("Substring shortcut match found: %s", display_name)
                return path
            
        return None

@tool
def try_shortcut_open(name: str):
    """Find an application in the Windows Start Menu shortcuts and open it."""
    logger.debug("Attempting shortcut open for %s", name)

    try:
        match = find_app_shortcut(name)

        if not match:
            logger.debug("No shortcut found for %s", name)
            return False

        logger.debug("Opening shortcut %s", match)

        os.startfile(match)

        logger.info("Shortcut open succeeded for %s", name)
        return True

    except OSError:
        logger.exception("Shortcut open failed for %s", name)
        # raise
        return False


# ---------- Strategy 3: Windows Search Index (files/documents) ----------

def search_windows_index(query: str, limit: int = 5):
    """Search the Windows Search index for matching files."""
    logger.debug(
        "Searching Windows index for %s with limit %d",
        query,
        limit
    )

    if not HAVE_WIN32COM:
        logger.warning("win32com unavailable, skipping Windows index search")
        return []

    try:
        conn = win32com.client.Dispatch("ADODB.Connection")
        conn.Open(
            "Provider=Search.CollatorDSO;"
            "Extended Properties='Application=Windows';"
        )

        sql = f"""
            SELECT TOP {limit} System.ItemPathDisplay FROM SYSTEMINDEX
            WHERE System.FileName LIKE '%{query}%'
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
            "Windows index search completed with %d results",
            len(results)
        )

        return results

    except Exception:
        logger.exception("Windows index search failed for %s", query)
        return []

@tool
def try_index_open(name: str):
    """Search the Windows Search index for a matching file or application and open the first result."""
    logger.debug("Attempting Windows index open for %s", name)

    try:
        results = search_windows_index(name)

        if not results:
            logger.debug("No Windows index results found for %s", name)
            return False

        logger.debug("Opening Windows index result %s", results[0])

        os.startfile(results[0])

        logger.info("Windows index open succeeded for %s", name)
        return True

    except OSError:
        logger.exception("Windows index open failed for %s", name)
        return False
        # raise


# ---------- Strategy 4: Fallback to web search ----------
@tool
def open_web_search(query: str):
    """Open a Google search for the given query in the default web browser."""
    logger.debug("Opening web search for %s", query)

    try:
        os.startfile(
            f"https://www.google.com/search?q={query.replace(' ', '+')}"
        )

        logger.info("Web search opened successfully for %s", query)
        return True

    except OSError:
        logger.exception("Failed to open web search for %s", query)
        # raise
        return False


# ==============================================================================================
#                                      CLOSE APPS/FILES
# ==============================================================================================

# ---------- Strategy 1: Graceful close via window message (preferred) ----------

def find_windows_for_process(pid: int) -> list:
    """Find all top-level window handles belonging to a given process ID."""
    logger.debug("Finding windows for process %s", pid)

    hwnds = []

    def enum_handler(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            _, found_pid = win32process.GetWindowThreadProcessId(hwnd)

            if found_pid == pid:
                hwnds.append(hwnd)

    win32gui.EnumWindows(enum_handler, None)

    logger.debug(
        "Found %d visible windows for process %s",
        len(hwnds),
        pid
    )

    return hwnds


def graceful_close_process(pid: int) -> bool:
    """Send WM_CLOSE to all windows of a process — same as clicking the ✕ button.
    Gives the app a chance to prompt 'Save changes?' etc."""
    logger.debug("Attempting graceful close for process %s", pid)

    hwnds = find_windows_for_process(pid)

    if not hwnds:
        logger.debug("No windows found for process %s", pid)
        return False

    for hwnd in hwnds:
        # Asks the process to close itself, will prompt for saving unsaved changes.
        # Process has control.
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)

    logger.info(
        "Graceful close message sent to process %s (%d windows)",
        pid,
        len(hwnds)
    )

    return True


# ---------- Strategy 2: Force kill (last resort) ----------

def force_kill_process(pid: int) -> bool:
    """Forcefully terminate a process. Use only if graceful close fails
    or the app is unresponsive — this discards unsaved work."""
    logger.debug("Attempting force kill for process %s", pid)

    try:
        proc = psutil.Process(pid)
        proc.kill()

        logger.info("Process %s terminated forcefully", pid)
        return True

    except psutil.NoSuchProcess:
        logger.warning("Process %s no longer exists", pid)
        return False

    except psutil.AccessDenied:
        logger.warning("Access denied when terminating process %s", pid)
        return False


# ---------- Process discovery ----------
def find_matching_processes(name: str, threshold: int = 65) -> list:
    """Find running processes whose name fuzzy-matches the given name.
    Returns list of dicts: {pid, name, exe}."""
    logger.debug(
        "Searching for processes matching %s with threshold %d",
        name,
        threshold
    )

    candidates = []

    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            candidates.append(proc.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not candidates:
        logger.debug("No running processes found")
        return []

    names = [c["name"] for c in candidates if c["name"]]

    matches = fuzzy_process.extract(
        name,
        names,
        limit=10,
        score_cutoff=threshold
    )

    matched_names = {m[0] for m in matches}
    results = [c for c in candidates if c["name"] in matched_names]

    logger.debug(
        "Found %d matching processes for %s",
        len(results),
        name
    )

    return results

# ---------- Discovery: visible app windows (narrow, user-facing) ----------

def get_running_apps() -> list:
    """Returns one entry per visible top-level window — mirrors Alt+Tab/Taskbar."""
    logger.debug("Finding running applications")

    apps = []

    def enum_handler(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return

        title = win32gui.GetWindowText(hwnd)
        if not title.strip():
            return

        _, pid = win32process.GetWindowThreadProcessId(hwnd)

        try:
            proc = psutil.Process(pid)
            proc_name = proc.name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return

        apps.append({
            "title": title,
            "process_name": proc_name,
            "pid": pid,
            "hwnd": hwnd
        })

    win32gui.EnumWindows(enum_handler, None)

    logger.debug("Found %d running applications", len(apps))

    return apps

def get_running_apps_tool():
    """Return currently visible running applications to the agent."""
    logger.debug("Retrieving running applications")

    apps = get_running_apps()

    logger.info("Retrieved %d running applications", len(apps))

    return apps

def find_matching_apps(name: str, threshold: int = 65) -> list:
    """Find currently visible app windows whose title OR process name
    fuzzy-matches the given name."""

    logger.debug(
        "Searching running applications for %s with threshold %d",
        name,
        threshold
    )

    apps = get_running_apps()

    if not apps:
        logger.debug("No running applications available for matching")
        return []

    search_pool = {
        f"{a['title']} {a['process_name']}": a
        for a in apps
    }

    matches = fuzzy_process.extract(
        name,
        search_pool.keys(),
        limit=10,
        score_cutoff=threshold
    )

    results = [search_pool[m[0]] for m in matches]

    logger.debug(
        "Found %d matching applications for %s",
        len(results),
        name
    )

    return results


# ---------- Unified entry point ----------

@tool
def close_app(name: str, force: bool = False, wait_seconds: float = 2.0,
              include_background: bool = False) -> str:
    """
    Close a running application by (fuzzy) name.

    Args:
        name: App name to search for, e.g. "chrome", "notepad", "word".
              The name given might not match the process name exactly —
              e.g. "Word" runs as WINWORD.EXE, "Chrome" as chrome.exe.
              Fuzzy matching against both window title and process name
              handles most of this, but use your own reasoning for
              well-known app-name-to-process mismatches.
        force: If True, force-kill immediately instead of trying a graceful
               close first. Only set True if the user explicitly asks to
               force-close, or a prior graceful attempt left it still running.
        wait_seconds: How long to wait after a graceful close attempt before
                      checking if it actually exited.
        include_background: If True and no visible app window matches, also
              search background/helper processes with no window (e.g. a
              stuck or tray-only process). Only set True if the user's
              request implies this — e.g. "kill any leftover chrome
              processes" or "it's frozen, force close everything related
              to X." Leave False for normal requests like "close Chrome,"
              so only what the user can actually see gets touched.

    Returns:
        Human-readable status string, one line per matched process.
    """
    logger.debug(
        "Attempting to close app %s (force=%s, include_background=%s)",
        name,
        force,
        include_background
    )

    matches = find_matching_apps(name)
    source = "window"

    if not matches and include_background:
        logger.debug(
            "No visible app matches found for %s, searching background processes",
            name
        )
        matches = find_matching_processes(name)
        source = "process"

    if not matches:
        logger.info("No running app or process found matching %s", name)
        return f"No running app or process found matching: {name}"

    logger.debug(
        "Found %d matching %s process(es) for %s",
        len(matches),
        source,
        name
    )

    results = []

    for m in matches:
        pid = m["pid"]
        label = m.get("title") or m.get("name") or m.get("process_name")

        if force:
            logger.debug("Force-killing %s (PID %s)", label, pid)

            success = force_kill_process(pid)

            results.append(
                f"{label} (PID {pid}, {source}): "
                f"{'force-killed' if success else 'failed'}"
            )
            continue

        logger.debug("Attempting graceful close for %s (PID %s)", label, pid)

        closed_gracefully = graceful_close_process(pid)

        if not closed_gracefully:
            logger.debug(
                "Graceful close unavailable for %s (PID %s), force-killing",
                label,
                pid
            )

            success = force_kill_process(pid)

            results.append(
                f"{label} (PID {pid}, {source}): "
                f"{'force-killed (no window found)' if success else 'failed'}"
            )
            continue

        logger.debug(
            "Graceful close requested for %s (PID %s), waiting %.1f seconds",
            label,
            pid,
            wait_seconds
        )

        time.sleep(wait_seconds)

        if psutil.pid_exists(pid):
            logger.info(
                "%s (PID %s) is still running after graceful close request",
                label,
                pid
            )

            results.append(
                f"{label} (PID {pid}, {source}): close requested, still running "
                f"(may be waiting on a dialog — not force-killed automatically)"
            )
        else:
            logger.info(
                "%s (PID %s) closed gracefully",
                label,
                pid
            )

            results.append(
                f"{label} (PID {pid}, {source}): closed gracefully"
            )

    logger.debug("Application close operation completed for %s", name)

    return "\n".join(results)


# ==============================================================================================
#                                       CREATE/REMOVE FILES
# ==============================================================================================

@tool
def remove_file(path: str) -> dict:
    """
    Remove the file at a valid path.

    Args:
        path: A valid file path in the form of a string.
    """
    logger.debug("Attempting to remove file %s", path)

    if not os.path.isfile(path):
        logger.warning("File does not exist: %s", path)

        return {
            "success": False,
            "path": path,
            "error": "File does not exist"
        }

    try:
        os.remove(path)

        logger.info("File removed successfully: %s", path)

        return {
            "success": True,
            "path": path
        }

    except FileNotFoundError as e:
        logger.warning("File not found while removing %s: %s", path, e)

        return {
            "success": False,
            "path": path,
            "error": str(e)
        }

    except PermissionError as e:
        logger.warning("Permission denied while removing %s: %s", path, e)

        return {
            "success": False,
            "path": path,
            "error": str(e)
        }