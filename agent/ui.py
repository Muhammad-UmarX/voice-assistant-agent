"""
Compact "single-exchange" CustomTkinter dialogue UI for the LangGraph
human-in-the-loop agent defined in main.py (build_app / action).

Behaviour
---------
- A small card holds one line of reply text above a single text entry.
  Submitting a message clears the entry immediately, shows "Thinking…",
  then the reply appears in the same spot. Submitting again clears the
  previous reply first.
- If the graph interrupts for approval, the reply area is replaced by
  an inline Approve / Reject control.
- A small arrow (›) on the card opens a separate floating panel with
  the full conversation transcript. The panel slides + fades in next
  to the main window: to the right by default, or to the left if the
  main window is already near the right edge of the screen (and there
  isn't more room on the right than the left). Clicking the arrow
  again (or the panel's × ) slides it back out and closes it. The
  panel follows the main window if it's moved while open.

Run with:  python gui.py
(requires customtkinter: pip install customtkinter)
"""

import queue
import threading
import traceback
from datetime import datetime

import customtkinter as ctk

from main import build_app, action


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

CARD_BG = "#1f1f23"
FIELD_BG = "#28282d"
PANEL_BG = "#19191c"
MUTED = "#9a9aa4"
TEXT = "#f2f2f2"
ACCENT = "#2f6fed"

BUBBLE_COLORS = {
    "user": "#2f6fed",
    "assistant": "#2b2b30",
    "system": "#26262b",
    "error": "#5c2020",
}

MAIN_SIZE = (480, 168)
PANEL_SIZE = (340, 480)
PANEL_GAP = 14          # gap between main window and panel
SLIDE_OFFSET = 44        # how far the panel travels while animating
ANIM_STEPS = 16
ANIM_INTERVAL_MS = 12
DEFAULT_SIDE = "right"   # "right" or "left" -- which side the panel opens on by default


def ease_out_cubic(t):
    return 1 - (1 - t) ** 3


class MessageBubble(ctk.CTkFrame):
    """One row in the history panel's transcript."""

    LABELS = {"user": "You", "assistant": "Agent", "system": "System", "error": "Error"}

    def __init__(self, master, text, sender="assistant", **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        anchor_side = "e" if sender == "user" else "w"
        justify = "right" if sender == "user" else "left"
        color = BUBBLE_COLORS.get(sender, BUBBLE_COLORS["assistant"])

        bubble = ctk.CTkFrame(self, fg_color=color, corner_radius=14)
        bubble.pack(anchor=anchor_side, padx=10, pady=3)

        ctk.CTkLabel(
            bubble,
            text=f"{self.LABELS.get(sender, 'Agent')} \u00b7 {datetime.now().strftime('%H:%M')}",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=MUTED,
        ).pack(anchor="w", padx=12, pady=(7, 0))

        ctk.CTkLabel(
            bubble, text=text, font=ctk.CTkFont(size=13), text_color=TEXT,
            justify=justify, wraplength=270,
        ).pack(anchor="w", padx=12, pady=(0, 9))


class HistoryPanel(ctk.CTkToplevel):
    """Frameless floating window showing the full transcript."""

    def __init__(self, master, transcript, on_close, width=PANEL_SIZE[0], height=PANEL_SIZE[1]):
        super().__init__(master)
        self.width, self.height = width, height
        self.overrideredirect(True)
        try:
            self.attributes("-topmost", True)
            self.attributes("-alpha", 0.0)
        except Exception:
            pass
        self.configure(fg_color=PANEL_BG)
        self.geometry(f"{width}x{height}+0+0")

        outer = ctk.CTkFrame(self, fg_color=PANEL_BG, corner_radius=16,
                              border_width=1, border_color="#2c2c31")
        outer.pack(fill="both", expand=True, padx=1, pady=1)

        header = ctk.CTkFrame(outer, fg_color="transparent", height=40)
        header.pack(fill="x", padx=12, pady=(10, 0))
        ctk.CTkLabel(
            header, text="History", font=ctk.CTkFont(size=13, weight="bold"), text_color=TEXT,
        ).pack(side="left")
        ctk.CTkButton(
            header, text="\u2715", width=24, height=24, corner_radius=8,
            fg_color="transparent", hover_color="#2c2c31", text_color=MUTED,
            command=on_close,
        ).pack(side="right")

        self.scroll = ctk.CTkScrollableFrame(outer, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=6, pady=(6, 10))
        self.scroll.grid_columnconfigure(0, weight=1)
        self._row = 0

        for text, sender in transcript:
            self.add_message(text, sender, scroll=False)
        self.after(30, self._scroll_to_bottom)

    def add_message(self, text, sender, scroll=True):
        MessageBubble(self.scroll, text, sender=sender).grid(row=self._row, column=0, sticky="ew", pady=2)
        self._row += 1
        if scroll:
            self.after(10, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        try:
            self.scroll._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass

    def set_position(self, x, y):
        self.geometry(f"{self.width}x{self.height}+{int(x)}+{int(y)}")

    def set_alpha(self, a):
        try:
            self.attributes("-alpha", max(0.0, min(1.0, a)))
        except Exception:
            pass


class DialogueApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Agent")
        self.resizable(False, False)
        self.geometry("{}x{}".format(*MAIN_SIZE))

        self.workflow = None
        self.logger = None
        self.config = {"configurable": {"thread_id": 123}}

        self._event_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._busy = False
        self._think_job = None
        self._think_dots = 0
        self._pending_decision = None

        self.transcript = []           # full log: list[(text, sender)]
        self.history_panel = None
        self._panel_direction = None
        self._panel_anim_job = None

        self._build_layout()
        self.bind("<Configure>", self._on_main_configure)
        self._poll_queue()

        self._set_reply("Starting up\u2026", muted=True)
        threading.Thread(target=self._init_backend, daemon=True).start()

    # ---------------------------------------------------------- layout --

    def _build_layout(self):
        self.grid_columnconfigure(0, weight=1)

        self.card = ctk.CTkFrame(self, corner_radius=16, fg_color=CARD_BG)
        self.card.grid(row=0, column=0, sticky="nsew", padx=14, pady=14)
        self.card.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(self.card, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 6))
        top.grid_columnconfigure(0, weight=1)

        self.reply_label = ctk.CTkLabel(
            top, text="", font=ctk.CTkFont(size=13), text_color=TEXT,
            justify="left", anchor="w", wraplength=330,
        )
        self.reply_label.grid(row=0, column=0, sticky="ew")

        self.arrow_btn = ctk.CTkButton(
            top, text="\u203a", width=28, height=26, corner_radius=8,
            fg_color="transparent", hover_color="#2c2c31", text_color=MUTED,
            font=ctk.CTkFont(size=15, weight="bold"), command=self._toggle_history_panel,
        )
        self.arrow_btn.grid(row=0, column=1, sticky="ne", padx=(8, 0))

        # inline approval control (hidden until needed)
        self.approval_row = ctk.CTkFrame(self.card, fg_color="transparent")
        self.approval_row.grid(row=1, column=0, sticky="ew", padx=14)
        self.approval_row.grid_remove()

        self.approve_btn = ctk.CTkButton(
            self.approval_row, text="Approve", width=100, fg_color="#2f9e44",
            hover_color="#228b3a", command=lambda: self._resolve_approval("YES"),
        )
        self.approve_btn.pack(side="left", padx=(0, 8), pady=(0, 8))

        self.reject_btn = ctk.CTkButton(
            self.approval_row, text="Reject", width=100, fg_color="#c0392b",
            hover_color="#992d22", command=lambda: self._resolve_approval("NO"),
        )
        self.reject_btn.pack(side="left", pady=(0, 8))

        entry_row = ctk.CTkFrame(self.card, fg_color="transparent")
        entry_row.grid(row=2, column=0, sticky="ew", padx=14, pady=(4, 14))
        entry_row.grid_columnconfigure(0, weight=1)

        self.entry = ctk.CTkEntry(
            entry_row, placeholder_text="Ask something\u2026", height=40,
            fg_color=FIELD_BG, border_width=0, corner_radius=12,
            font=ctk.CTkFont(size=13),
        )
        self.entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.entry.bind("<Return>", lambda _e: self._on_send())
        self.entry.configure(state="disabled")

        self.send_btn = ctk.CTkButton(
            entry_row, text="\u27a4", width=40, height=40, corner_radius=12,
            fg_color=ACCENT, hover_color="#255bc4", command=self._on_send,
        )
        self.send_btn.grid(row=0, column=1)
        self.send_btn.configure(state="disabled")

    # ------------------------------------------------------ reply helpers --

    def _set_reply(self, text, muted=False, animate_dots=False):
        self._stop_thinking_animation()
        self.reply_label.configure(text=text, text_color=MUTED if muted else TEXT)
        if animate_dots:
            self._start_thinking_animation(text.rstrip("."))

    def _start_thinking_animation(self, base_text):
        self._think_dots = 0

        def tick():
            self._think_dots = (self._think_dots % 3) + 1
            self.reply_label.configure(text=base_text + "." * self._think_dots)
            self._think_job = self.after(450, tick)

        tick()

    def _stop_thinking_animation(self):
        if self._think_job is not None:
            self.after_cancel(self._think_job)
            self._think_job = None

    # ------------------------------------------------------- transcript --

    def _log(self, text, sender):
        self.transcript.append((text, sender))
        if self.history_panel is not None:
            self.history_panel.add_message(text, sender)

    # -------------------------------------------------- flyout panel --

    def _panel_target_position(self, panel_w, panel_h, preferred_side=None):
        self.update_idletasks()

        # Absolute screen coordinates of the main window.
        mx = self.winfo_rootx()
        my = self.winfo_rooty()
        mw = self.winfo_width()
        mh = self.winfo_height()

        # Virtual desktop bounds.
        # Unlike winfo_screenwidth(), these work much better with
        # multiple monitors.
        vx = self.winfo_vrootx()
        vy = self.winfo_vrooty()
        vw = self.winfo_vrootwidth()
        vh = self.winfo_vrootheight()

        # Space immediately beside the main window.
        right_x = mx + mw + PANEL_GAP
        left_x = mx - panel_w - PANEL_GAP

        right_fits = right_x + panel_w <= vx + vw
        left_fits = left_x >= vx

        # When opening, always prefer the configured default side.
        # Once already open, keep the existing direction.
        direction = preferred_side or self._panel_direction or DEFAULT_SIDE

        if direction == "right":
            if right_fits:
                target_x = right_x
            elif left_fits:
                direction = "left"
                target_x = left_x
            else:
                # Neither side has enough room.
                # Use whichever side has more available space.
                right_space = (vx + vw) - right_x
                left_space = mx - vx

                if right_space >= left_space:
                    direction = "right"
                    target_x = right_x
                else:
                    direction = "left"
                    target_x = left_x

        else:  # preferred direction is left
            if left_fits:
                target_x = left_x
            elif right_fits:
                direction = "right"
                target_x = right_x
            else:
                right_space = (vx + vw) - right_x
                left_space = mx - vx

                if right_space >= left_space:
                    direction = "right"
                    target_x = right_x
                else:
                    direction = "left"
                    target_x = left_x

        # Keep the panel vertically on-screen when possible.
        target_y = my

        if target_y + panel_h > vy + vh:
            target_y = vy + vh - panel_h - 10

        if target_y < vy:
            target_y = vy + 10

        # Absolute safety check:
        # if opening on the left, NEVER allow the panel to cross into
        # the main window's area.
        if direction == "left":
            target_x = min(target_x, mx - panel_w - PANEL_GAP)

        # Likewise, if opening on the right, NEVER allow it to cross
        # into the main window.
        else:
            target_x = max(target_x, mx + mw + PANEL_GAP)

        return direction, target_x, target_y

    def _toggle_history_panel(self):
        if self.history_panel is not None:
            self._close_history_panel()
        else:
            self._open_history_panel()

    def _open_history_panel(self):
        panel_w, panel_h = PANEL_SIZE

        direction, target_x, target_y = self._panel_target_position(
            panel_w,
            panel_h,
            preferred_side=DEFAULT_SIDE,
        )

        self._panel_direction = direction

        panel = HistoryPanel(
            self,
            self.transcript,
            on_close=self._close_history_panel,
            width=panel_w,
            height=panel_h,
        )

        self.history_panel = panel

        self.arrow_btn.configure(
            text="\u2039" if direction == "right" else "\u203a",
            fg_color=ACCENT,
            text_color="#ffffff",
        )

        # Slide outward from the selected side.
        if direction == "right":
            start_x = target_x - SLIDE_OFFSET
        else:
            start_x = target_x + SLIDE_OFFSET

        panel.set_position(start_x, target_y)
        panel.set_alpha(0.0)

        self._animate(
            panel,
            start_x,
            target_x,
            target_y,
            0.0,
            1.0,
            on_done=None,
        )

    def _close_history_panel(self):
        panel = self.history_panel
        if panel is None or not panel.winfo_exists():
            self.history_panel = None
            return
        self.history_panel = None
        self.arrow_btn.configure(text="\u203a", fg_color="transparent", text_color=MUTED)

        x_now, y_now = panel.winfo_x(), panel.winfo_y()
        end_x = x_now - SLIDE_OFFSET if self._panel_direction == "right" else x_now + SLIDE_OFFSET

        def finish():
            panel.destroy()

        self._animate(panel, x_now, end_x, y_now, 1.0, 0.0, on_done=finish)

    def _animate(self, panel, start_x, end_x, y, start_alpha, end_alpha, on_done, step=0):
        if not panel.winfo_exists():
            return
        t = step / ANIM_STEPS
        eased = ease_out_cubic(t)
        x = start_x + (end_x - start_x) * eased
        alpha = start_alpha + (end_alpha - start_alpha) * eased
        panel.set_position(x, y)
        panel.set_alpha(alpha)

        if step < ANIM_STEPS:
            self._panel_anim_job = self.after(
                ANIM_INTERVAL_MS,
                lambda: self._animate(panel, start_x, end_x, y, start_alpha, end_alpha, on_done, step + 1),
            )
        else:
            panel.set_position(end_x, y)
            panel.set_alpha(end_alpha)
            self._panel_anim_job = None
            if on_done:
                on_done()

    def _on_main_configure(self, _event):
        # Keep the flyout attached to the main window if it gets moved.
        if self.history_panel is not None and self._panel_animjob is None:
            panel_w = self.history_panel.width
            panel_h = self.history_panel.height

            direction, x, y = self._panel_target_position(
                panel_w,
                panel_h,
                preferred_side=self._panel_direction,
            )

            self._panel_direction = direction
            self.history_panel.set_position(x, y)

    # ------------------------------------------------------- backend io --

    def _init_backend(self):
        try:
            self.workflow, self.logger = build_app()
        except Exception:
            self._event_queue.put(("error", f"Failed to start agent:\n{traceback.format_exc()}"))
            return
        self._event_queue.put(("ready", None))

    def _gui_input_fn(self, prompt_text):
        """
        Called from the worker thread by main.action() when the graph
        interrupts for approval. Blocks the worker thread until the
        user clicks Approve/Reject, then returns "YES"/"NO".
        """
        decided = threading.Event()
        result = {"value": None}
        self._pending_decision = lambda v: (result.__setitem__("value", v), decided.set())

        self._event_queue.put(("show_approval", prompt_text))
        decided.wait()
        return result["value"]

    def _resolve_approval(self, value):
        if self._pending_decision is None:
            return
        cb, self._pending_decision = self._pending_decision, None
        self._log("Approved" if value == "YES" else "Rejected", "system")
        self.approval_row.grid_remove()
        self._set_reply("Thinking\u2026", muted=True, animate_dots=True)
        cb(value)

    def _on_send(self):
        if self._busy:
            return
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")   # typed text disappears from the box
        self._log(text, "user")
        self._set_reply("Thinking\u2026", muted=True, animate_dots=True)  # previous reply disappears
        self._set_busy(True)
        threading.Thread(target=self._run_turn, args=(text,), daemon=True).start()

    def _run_turn(self, text):
        try:
            result = action(
                self.workflow, self.config, text,
                input_fn=self._gui_input_fn, logger=self.logger,
            )
            reply = result["messages"][-1].content
            self._event_queue.put(("assistant", reply))
        except Exception:
            self._event_queue.put(("error", f"Something went wrong:\n{traceback.format_exc()}"))
        finally:
            self._event_queue.put(("busy_off", None))

    # -------------------------------------------------- main-thread pump --

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self._event_queue.get_nowait()
                if kind == "ready":
                    self._set_reply("Ready. How can I help you?", muted=True)
                    self.entry.configure(state="normal")
                    self.send_btn.configure(state="normal")
                    self.entry.focus()
                elif kind == "assistant":
                    self._set_reply(payload)
                    self._log(payload, "assistant")
                elif kind == "error":
                    self._set_reply("Something went wrong \u2014 see history for details.", muted=True)
                    self._log(payload, "error")
                elif kind == "show_approval":
                    self._set_reply("Needs your approval:", muted=True)
                    self._log(payload, "system")
                    for w in (self.approve_btn, self.reject_btn):
                        w.configure(state="normal")
                    self.approval_row.grid()
                elif kind == "busy_off":
                    self._set_busy(False)
        except queue.Empty:
            pass
        self.after(80, self._poll_queue)

    def _set_busy(self, busy):
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.entry.configure(state=state)
        self.send_btn.configure(state=state)
        if not busy:
            self.entry.focus()


if __name__ == "__main__":
    app = DialogueApp()
    app.mainloop()