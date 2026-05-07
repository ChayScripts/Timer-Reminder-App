import customtkinter as ctk
from tkinter import filedialog, messagebox
from datetime import datetime, timedelta, date
import calendar
import os, json, sys, uuid, threading
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
import pygame
from windows_toasts import WindowsToaster, Toast
import pystray
from pystray import MenuItem as TrayItem
from PIL import Image, ImageDraw

pygame.mixer.init()
toaster = WindowsToaster("Timer & Reminder")

CONFIG_FILE    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
REMINDERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reminders.json")

RECUR_OPTIONS = [
    "Once", "Hourly", "Daily", "Weekly", "Biweekly",
    "Monthly", "Every 3 Months", "Every 6 Months", "Yearly", "Custom"
]

WEEKDAYS = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]

def resource_path(rel):
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path) as f: return json.load(f)
        except Exception: pass
    return default

def save_json(path, data):
    try:
        with open(path, "w") as f: json.dump(data, f, indent=2)
    except Exception: pass

def fmt_delta(secs):
    h, r = divmod(int(secs), 3600)
    m, s = divmod(r, 60)
    if h:  return f"{h}h {m:02d}m"
    if m:  return f"{m}m {s:02d}s"
    return f"{s}s"

def next_trigger_standard(time_str, recur, after=None):
    """Compute next fire datetime for non-custom recurrence."""
    now = after or datetime.now()
    h, m = map(int, time_str.split(":"))
    base = now.replace(hour=h, minute=m, second=0, microsecond=0)

    if recur == "Once":
        if base <= now: base += timedelta(days=1)
        return base
    if recur == "Hourly":
        candidate = now.replace(second=0, microsecond=0) + timedelta(hours=1)
        return candidate
    if recur == "Daily":
        if base <= now: base += timedelta(days=1)
        return base
    if recur == "Weekly":
        if base <= now: base += timedelta(weeks=1)
        return base
    if recur == "Biweekly":
        if base <= now: base += timedelta(weeks=2)
        return base
    if recur == "Monthly":
        m2 = base.month + 1
        y2 = base.year + (m2 - 1) // 12
        m2 = (m2 - 1) % 12 + 1
        day = min(base.day, calendar.monthrange(y2, m2)[1])
        nxt = base.replace(year=y2, month=m2, day=day)
        if nxt <= now: nxt += timedelta(days=28)
        return nxt
    if recur == "Every 3 Months":
        m2 = base.month + 3
        y2 = base.year + (m2 - 1) // 12
        m2 = (m2 - 1) % 12 + 1
        day = min(base.day, calendar.monthrange(y2, m2)[1])
        return base.replace(year=y2, month=m2, day=day)
    if recur == "Every 6 Months":
        m2 = base.month + 6
        y2 = base.year + (m2 - 1) // 12
        m2 = (m2 - 1) % 12 + 1
        day = min(base.day, calendar.monthrange(y2, m2)[1])
        return base.replace(year=y2, month=m2, day=day)
    if recur == "Yearly":
        try:
            nxt = base.replace(year=base.year + 1)
        except ValueError:
            nxt = base.replace(year=base.year + 1, day=28)
        return nxt
    return base + timedelta(days=1)

def next_trigger_for_schedule(sched, after=None):
    """
    sched = {
      "type": "weekdays",  # or "date"
      "days": [0,2,4],     # weekday indices (Mon=0) — for weekdays type
      "date": "2025-12-25",# ISO date string — for date type
      "time": "09:00"
    }
    Returns next datetime or None if it's a one-shot date already passed.
    """
    now = after or datetime.now()
    h, m = map(int, sched["time"].split(":"))

    if sched["type"] == "date":
        d = datetime.fromisoformat(sched["date"]).replace(hour=h, minute=m, second=0, microsecond=0)
        return d if d > now else None

    if sched["type"] == "weekdays":
        chosen = sched["days"]  # list of 0-6
        for offset in range(8):
            candidate = (now + timedelta(days=offset)).replace(hour=h, minute=m, second=0, microsecond=0)
            if candidate > now and candidate.weekday() in chosen:
                return candidate
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Calendar popup
# ─────────────────────────────────────────────────────────────────────────────

class CalendarPopup(ctk.CTkToplevel):
    """Lightweight month-grid date picker. Writes YYYY-MM-DD into target_entry."""

    DAYS_HDR = ["Mo","Tu","We","Th","Fr","Sa","Su"]

    def __init__(self, master, target_entry):
        super().__init__(master)
        self.overrideredirect(True)          # borderless
        self.attributes("-topmost", True)
        self._entry = target_entry
        self._entry.update_idletasks()

        # Try to pre-fill from existing entry value
        try:
            d = datetime.strptime(target_entry.get().strip(), "%Y-%m-%d")
            self._year, self._month = d.year, d.month
        except Exception:
            now = datetime.now()
            self._year, self._month = now.year, now.month

        self.configure(fg_color="#ffffff")
        self._build()
        self._position()
        self.grab_set()
        self.bind("<FocusOut>", lambda e: self._maybe_close(e))

    def _position(self):
        e = self._entry
        x = e.winfo_rootx()
        y = e.winfo_rooty() + e.winfo_height() + 4
        self.geometry(f"+{x}+{y}")

    def _maybe_close(self, event):
        try:
            if not str(self.focus_get()).startswith(str(self.winfo_id())):
                self.destroy()
        except Exception:
            self.destroy()

    def _build(self):
        for w in self.winfo_children():
            w.destroy()

        outer = ctk.CTkFrame(self, fg_color="#ffffff",
            corner_radius=10, border_width=1, border_color="#e2e8f0")
        outer.pack(padx=0, pady=0)

        # Header: prev / Month Year / next
        hdr = ctk.CTkFrame(outer, fg_color="#6366f1", corner_radius=8)
        hdr.grid(row=0, column=0, sticky="ew", padx=0, pady=0)
        hdr.columnconfigure(1, weight=1)

        ctk.CTkButton(hdr, text="‹", width=32, height=30,
            fg_color="transparent", hover_color="#4f46e5",
            text_color="white", font=ctk.CTkFont(size=16),
            command=self._prev_month
        ).grid(row=0, column=0)

        ctk.CTkLabel(hdr,
            text=f"{calendar.month_abbr[self._month]} {self._year}",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="white"
        ).grid(row=0, column=1)

        ctk.CTkButton(hdr, text="›", width=32, height=30,
            fg_color="transparent", hover_color="#4f46e5",
            text_color="white", font=ctk.CTkFont(size=16),
            command=self._next_month
        ).grid(row=0, column=2)

        # Jump row: year entry + month dropdown
        jump = ctk.CTkFrame(outer, fg_color="#f8fafc")
        jump.grid(row=1, column=0, sticky="ew", pady=(4,0))
        ctk.CTkLabel(jump, text="Year:", font=ctk.CTkFont(size=10),
            text_color="#64748b").grid(row=0, column=0, padx=(8,4), pady=4)
        self._year_entry = ctk.CTkEntry(jump, width=58, height=24,
            justify="center", font=ctk.CTkFont(size=11))
        self._year_entry.insert(0, str(self._year))
        self._year_entry.grid(row=0, column=1, padx=(0,6))
        ctk.CTkButton(jump, text="Go", width=36, height=24,
            font=ctk.CTkFont(size=10),
            fg_color="#6366f1", hover_color="#4f46e5",
            command=self._jump_year
        ).grid(row=0, column=2, padx=(0,8))

        # Day headers
        grid_frame = ctk.CTkFrame(outer, fg_color="#ffffff")
        grid_frame.grid(row=2, column=0, padx=8, pady=(4,8))

        for c, d in enumerate(self.DAYS_HDR):
            ctk.CTkLabel(grid_frame, text=d, width=30,
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color="#94a3b8"
            ).grid(row=0, column=c)

        # Day buttons
        cal = calendar.monthcalendar(self._year, self._month)
        today = datetime.now().date()
        for r, week in enumerate(cal):
            for c, day in enumerate(week):
                if day == 0:
                    ctk.CTkLabel(grid_frame, text="", width=30
                    ).grid(row=r+1, column=c)
                else:
                    this_date = date(self._year, self._month, day)
                    is_today = this_date == today
                    is_past  = this_date < today
                    fg = "#6366f1" if is_today else ("transparent" if not is_past else "#f1f5f9")
                    tc = "white" if is_today else ("#cbd5e1" if is_past else "#0f172a")
                    ctk.CTkButton(grid_frame,
                        text=str(day), width=30, height=28,
                        corner_radius=14,
                        fg_color=fg, hover_color="#e0e7ff",
                        text_color=tc,
                        font=ctk.CTkFont(size=11),
                        command=lambda d=day: self._pick(d)
                    ).grid(row=r+1, column=c, padx=1, pady=1)

    def _prev_month(self):
        self._month -= 1
        if self._month < 1:
            self._month = 12; self._year -= 1
        self._build()

    def _next_month(self):
        self._month += 1
        if self._month > 12:
            self._month = 1; self._year += 1
        self._build()

    def _jump_year(self):
        try:
            y = int(self._year_entry.get())
            if 1900 < y < 2200:
                self._year = y
                self._build()
        except ValueError:
            pass

    def _pick(self, day):
        val = f"{self._year:04d}-{self._month:02d}-{day:02d}"
        self._entry.delete(0, "end")
        self._entry.insert(0, val)
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# Custom recurrence dialog
# ─────────────────────────────────────────────────────────────────────────────

class CustomRecurDialog(ctk.CTkToplevel):
    """
    Modal dialog to build custom schedules.
    Each schedule = weekday selection + time  OR  specific date + time.
    Multiple schedules can be added.
    Result stored in self.result (list of schedule dicts) on confirm.
    """
    def __init__(self, master, existing=None):
        super().__init__(master)
        self.title("Custom Schedule")
        self.geometry("520x560")
        self.resizable(False, False)
        self.grab_set()
        self.result = None
        self._schedules = list(existing or [])

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ── Top: add new schedule form ────────────────────────────────────────
        top = ctk.CTkFrame(self, fg_color=("#f1f5f9","#1a1d2e"), corner_radius=10)
        top.grid(row=0, column=0, sticky="ew", padx=16, pady=(16,8))
        top.columnconfigure(0, weight=1)

        ctk.CTkLabel(top, text="Add Schedule Entry",
            font=ctk.CTkFont(size=13, weight="bold"), anchor="w"
        ).grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=(10,8))

        # Type toggle
        type_row = ctk.CTkFrame(top, fg_color="transparent")
        type_row.grid(row=1, column=0, columnspan=2, sticky="w", padx=12)
        ctk.CTkLabel(type_row, text="Type:", font=ctk.CTkFont(size=11)).grid(row=0,column=0,padx=(0,8))
        self._stype = ctk.StringVar(value="weekdays")
        ctk.CTkRadioButton(type_row, text="Day of week", variable=self._stype,
            value="weekdays", command=self._toggle_type,
            font=ctk.CTkFont(size=11)
        ).grid(row=0, column=1, padx=(0,12))
        ctk.CTkRadioButton(type_row, text="Specific date", variable=self._stype,
            value="date", command=self._toggle_type,
            font=ctk.CTkFont(size=11)
        ).grid(row=0, column=2)

        # Weekday checkboxes
        self._wd_frame = ctk.CTkFrame(top, fg_color="transparent")
        self._wd_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=(8,0))
        self._wd_vars = {}
        for i, day in enumerate(WEEKDAYS):
            var = ctk.BooleanVar(value=False)
            ctk.CTkCheckBox(self._wd_frame, text=day, variable=var,
                width=60, font=ctk.CTkFont(size=11),
                checkbox_width=16, checkbox_height=16
            ).grid(row=0, column=i, padx=2)
            self._wd_vars[i] = var

        # Date input (hidden initially)
        self._date_frame = ctk.CTkFrame(top, fg_color="transparent")
        self._date_frame.grid(row=3, column=0, columnspan=2, sticky="ew", padx=12, pady=(8,0))
        ctk.CTkLabel(self._date_frame, text="Date:",
            font=ctk.CTkFont(size=11)).grid(row=0, column=0, padx=(0,8))
        self._date_entry = ctk.CTkEntry(self._date_frame, width=120,
            placeholder_text="YYYY-MM-DD", justify="center")
        self._date_entry.grid(row=0, column=1)
        ctk.CTkButton(self._date_frame, text="📅", width=34, height=30,
            font=ctk.CTkFont(size=14),
            fg_color=("#e0e7ff","#2e3a6e"),
            hover_color=("#c7d2fe","#3a4a80"),
            text_color=("#3730a3","#a5b4fc"),
            command=self._open_calendar
        ).grid(row=0, column=2, padx=(6,0))
        self._date_frame.grid_remove()

        # Time input
        time_row = ctk.CTkFrame(top, fg_color="transparent")
        time_row.grid(row=4, column=0, columnspan=2, sticky="w", padx=12, pady=(10,0))
        ctk.CTkLabel(time_row, text="Time (HH:MM, 24h):",
            font=ctk.CTkFont(size=11)).grid(row=0, column=0, padx=(0,8))
        self._time_entry = ctk.CTkEntry(time_row, width=90,
            placeholder_text="09:00", justify="center")
        self._time_entry.grid(row=0, column=1)

        ctk.CTkButton(top, text="＋  Add this entry",
            height=34, corner_radius=8,
            fg_color="#6366f1", hover_color="#4f46e5",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._add_entry
        ).grid(row=5, column=0, columnspan=2, sticky="ew", padx=12, pady=(10,12))

        # ── Middle: list of added schedules ───────────────────────────────────
        ctk.CTkLabel(self, text="Scheduled entries",
            font=ctk.CTkFont(size=11), text_color=("#64748b","#94a3b8"), anchor="w"
        ).grid(row=1, column=0, sticky="nw", padx=18, pady=(4,2))

        self._list_frame = ctk.CTkScrollableFrame(self,
            fg_color="transparent", height=160)
        self._list_frame.grid(row=1, column=0, sticky="nsew", padx=16, pady=(20,8))
        self._list_frame.columnconfigure(0, weight=1)

        self._no_entry_lbl = ctk.CTkLabel(self._list_frame,
            text="No entries yet. Add one above.",
            text_color=("#94a3b8","#475569"), font=ctk.CTkFont(size=11))

        self._render_list()

        # ── Bottom: confirm/cancel ─────────────────────────────────────────────
        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.grid(row=2, column=0, pady=(0,16))
        ctk.CTkButton(bot, text="Confirm", width=130, height=36,
            fg_color="#22c55e", hover_color="#16a34a",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._confirm
        ).grid(row=0, column=0, padx=8)
        ctk.CTkButton(bot, text="Cancel", width=100, height=36,
            fg_color=("#e2e8f0","#2e3250"),
            hover_color=("#cbd5e1","#3a3f60"),
            text_color=("#0f172a","#f1f5f9"),
            font=ctk.CTkFont(size=13),
            command=self.destroy
        ).grid(row=0, column=1, padx=8)

    def _open_calendar(self):
        CalendarPopup(self, self._date_entry)

    def _toggle_type(self):
        if self._stype.get() == "weekdays":
            self._wd_frame.grid()
            self._date_frame.grid_remove()
        else:
            self._wd_frame.grid_remove()
            self._date_frame.grid()

    def _add_entry(self):
        t = self._time_entry.get().strip()
        try: datetime.strptime(t, "%H:%M")
        except ValueError:
            messagebox.showerror("Invalid", "Enter time as HH:MM", parent=self); return

        if self._stype.get() == "weekdays":
            chosen = [i for i, v in self._wd_vars.items() if v.get()]
            if not chosen:
                messagebox.showerror("No days", "Select at least one day.", parent=self); return
            self._schedules.append({"type":"weekdays","days":chosen,"time":t})
        else:
            d = self._date_entry.get().strip()
            try: datetime.strptime(d, "%Y-%m-%d")
            except ValueError:
                messagebox.showerror("Invalid", "Enter date as YYYY-MM-DD", parent=self); return
            self._schedules.append({"type":"date","date":d,"time":t})

        self._render_list()
        # reset
        for v in self._wd_vars.values(): v.set(False)
        self._time_entry.delete(0,"end")
        self._date_entry.delete(0,"end")

    def _render_list(self):
        for w in self._list_frame.winfo_children():
            if w != self._no_entry_lbl: w.destroy()
        if not self._schedules:
            self._no_entry_lbl.grid(row=0, column=0, pady=12)
            return
        self._no_entry_lbl.grid_remove()
        for i, s in enumerate(self._schedules):
            row_f = ctk.CTkFrame(self._list_frame,
                fg_color=("#ffffff","#23263a"), corner_radius=6,
                border_width=1, border_color=("#e2e8f0","#2e3250"))
            row_f.grid(row=i, column=0, sticky="ew", pady=2)
            row_f.columnconfigure(0, weight=1)
            if s["type"] == "weekdays":
                day_names = ", ".join(WEEKDAYS[d] for d in sorted(s["days"]))
                desc = f"Every {day_names} at {s['time']}"
            else:
                desc = f"On {s['date']} at {s['time']}"
            ctk.CTkLabel(row_f, text=desc,
                font=ctk.CTkFont(size=11), anchor="w"
            ).grid(row=0, column=0, sticky="ew", padx=10, pady=6)
            idx = i
            ctk.CTkButton(row_f, text="✕", width=24, height=24,
                corner_radius=12, fg_color="transparent",
                hover_color=("#fee2e2","#3f1515"),
                text_color=("#94a3b8","#64748b"),
                font=ctk.CTkFont(size=11),
                command=lambda x=idx: self._remove_entry(x)
            ).grid(row=0, column=1, padx=(0,6))

    def _remove_entry(self, idx):
        del self._schedules[idx]
        self._render_list()

    def _confirm(self):
        if not self._schedules:
            messagebox.showerror("Empty", "Add at least one schedule entry.", parent=self)
            return
        self.result = self._schedules
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# Reminder card
# ─────────────────────────────────────────────────────────────────────────────

class ReminderCard(ctk.CTkFrame):
    def __init__(self, master, rem, on_delete, **kw):
        super().__init__(master,
            fg_color=("#ffffff","#23263a"),
            corner_radius=8,
            border_width=1,
            border_color=("#e2e8f0","#2e3250"),
            **kw)
        self.columnconfigure(3, weight=1)

        ctk.CTkFrame(self, width=3, height=20, fg_color="#6366f1", corner_radius=2
        ).grid(row=0, column=0, padx=(8,0), pady=10)

        recur = rem.get("recur","Once")
        badge = f"  [{recur}]" if recur != "Once" else ""

        # For custom, show number of schedule entries
        if recur == "Custom":
            n = len(rem.get("schedules", []))
            badge = f"  [Custom · {n} entr{'y' if n==1 else 'ies'}]"

        ctk.CTkLabel(self,
            text=rem["label"] or "Reminder",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=("#0f172a","#f1f5f9"), anchor="w"
        ).grid(row=0, column=1, sticky="w", padx=(8,6), pady=10)

        time_text = rem.get("time","") + badge
        ctk.CTkLabel(self,
            text=time_text,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=("#64748b","#94a3b8"), anchor="w"
        ).grid(row=0, column=2, sticky="w", padx=(0,4), pady=10)

        self.cd_lbl = ctk.CTkLabel(self,
            text="", font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color="#22c55e", anchor="e")
        self.cd_lbl.grid(row=0, column=3, sticky="e", padx=(4,4), pady=10)

        ctk.CTkButton(self,
            text="✕", width=26, height=26, corner_radius=13,
            fg_color="transparent", hover_color=("#fee2e2","#3f1515"),
            text_color=("#94a3b8","#64748b"), font=ctk.CTkFont(size=12),
            command=lambda: on_delete(rem["id"])
        ).grid(row=0, column=4, padx=(2,8), pady=10)

    def update_countdown(self, secs):
        if secs <= 0:
            self.cd_lbl.configure(text="firing…", text_color="#f59e0b")
        else:
            self.cd_lbl.configure(text=f"in {fmt_delta(secs)}", text_color="#22c55e")


# ─────────────────────────────────────────────────────────────────────────────
# Sound row widget
# ─────────────────────────────────────────────────────────────────────────────

class SoundRow(ctk.CTkFrame):
    def __init__(self, master, heading, initial="", on_change=None, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.path = initial
        self.on_change = on_change
        self.columnconfigure(1, weight=1)

        ctk.CTkLabel(self, text=heading,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=("#0f172a","#f1f5f9"), anchor="w", width=130
        ).grid(row=0, column=0, sticky="w")

        self.lbl = ctk.CTkLabel(self,
            text=os.path.basename(initial) if initial else "No file selected",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=("#64748b","#94a3b8"), anchor="w")
        self.lbl.grid(row=0, column=1, sticky="ew", padx=8)

        ctk.CTkButton(self, text="Browse", width=72, height=30,
            font=ctk.CTkFont(size=11),
            fg_color=("#e2e8f0","#2e3250"), hover_color=("#cbd5e1","#3e4470"),
            text_color=("#0f172a","#f1f5f9"), command=self._browse
        ).grid(row=0, column=2, padx=(0,6))

        ctk.CTkButton(self, text="▶", width=34, height=30,
            font=ctk.CTkFont(size=12),
            fg_color=("#e2e8f0","#2e3250"), hover_color=("#cbd5e1","#3e4470"),
            text_color=("#0f172a","#f1f5f9"), command=self._test
        ).grid(row=0, column=3)

    def _browse(self):
        p = filedialog.askopenfilename(title="Select MP3", filetypes=[("MP3","*.mp3")])
        if p:
            self.path = p
            self.lbl.configure(text=os.path.basename(p))
            if self.on_change: self.on_change(p)

    def _test(self):
        if self.path and os.path.exists(self.path):
            threading.Thread(target=lambda:(
                pygame.mixer.music.load(self.path),
                pygame.mixer.music.play()
            ), daemon=True).start()

    def get(self): return self.path


# ─────────────────────────────────────────────────────────────────────────────
# Main App
# ─────────────────────────────────────────────────────────────────────────────

class App(ctk.CTk):
    NAV = [
        ("reminders","🔔","Reminders"),
        ("timer",    "⏱","Timer"),
        ("sounds",   "🔊","Sounds"),
    ]

    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("Light")
        ctk.set_default_color_theme("blue")

        self.title("Timer & Reminder")
        self.geometry("680x660")
        self.minsize(620, 580)
        self.resizable(True, True)

        try: self.iconbitmap(resource_path("app_icon.ico"))
        except Exception: pass

        cfg = load_json(CONFIG_FILE, {})
        self._rsound = cfg.get("reminder_sound","")
        self._tsound = cfg.get("timer_sound","")

        self.reminders: list[dict] = []
        for r in load_json(REMINDERS_FILE, []):
            try:
                r["next_dt"] = datetime.fromisoformat(r["next_dt_str"])
                self.reminders.append(r)
            except Exception: pass

        self.timer_secs    = 0
        self.timer_running = False
        self._cards: dict[str, ReminderCard] = {}
        self._pages = {}
        self._pending_custom = []   # schedules from dialog before reminder saved

        self._build_shell()
        self._show_page("reminders")
        self._refresh_cards()
        self._setup_tray()
        self.protocol("WM_DELETE_WINDOW", self._hide_to_tray)
        self.after(1000, self._tick)

    # ── Tray ──────────────────────────────────────────────────────────────────

    def _make_tray_img(self):
        ico = resource_path("app_icon.ico")
        if os.path.exists(ico):
            try: return Image.open(ico).resize((64,64))
            except Exception: pass
        img = Image.new("RGBA",(64,64),(0,0,0,0))
        d = ImageDraw.Draw(img)
        d.ellipse((2,2,62,62), fill="#6366f1")
        d.ellipse((18,18,46,46), fill="white")
        return img

    def _setup_tray(self):
        menu = pystray.Menu(
            TrayItem("Open", self._tray_open, default=True),
            pystray.Menu.SEPARATOR,
            TrayItem("Quit", self._tray_quit),
        )
        self._tray = pystray.Icon("TR", self._make_tray_img(), "Timer & Reminder", menu)
        threading.Thread(target=self._tray.run, daemon=True).start()

    def _hide_to_tray(self):    self.withdraw()
    def _tray_open(self, *_):   self.after(0, self.deiconify)
    def _tray_quit(self, *_):
        self._tray.stop(); self.after(0, self.destroy)

    # ── Shell ──────────────────────────────────────────────────────────────────

    def _build_shell(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self, width=185,
            fg_color=("#1e1b4b","#12102e"), corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.columnconfigure(0, weight=1)

        ctk.CTkLabel(sidebar, text="⏰", font=ctk.CTkFont(size=32),
            text_color="white").grid(row=0, column=0, pady=(30,4))
        ctk.CTkLabel(sidebar, text="Timer &\nReminder",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color="#c7d2fe", justify="center"
        ).grid(row=1, column=0, pady=(0,30))

        self._nav_btns = {}
        for idx, (key, icon, label) in enumerate(self.NAV):
            btn = ctk.CTkButton(sidebar,
                text=f"  {icon}  {label}", anchor="w", height=42,
                corner_radius=8, font=ctk.CTkFont(family="Segoe UI", size=13),
                fg_color="transparent", hover_color=("#2e2a6e","#1e1b4b"),
                text_color="#a5b4fc",
                command=lambda k=key: self._show_page(k))
            btn.grid(row=2+idx, column=0, sticky="ew", padx=12, pady=3)
            self._nav_btns[key] = btn

        sidebar.grid_rowconfigure(10, weight=1)
        ctk.CTkLabel(sidebar, text="v6.0", font=ctk.CTkFont(size=10),
            text_color="#4338ca").grid(row=11, column=0, pady=(0,16))

        self._content = ctk.CTkFrame(self,
            fg_color=("#f8fafc","#0f1120"), corner_radius=0)
        self._content.grid(row=0, column=1, sticky="nsew")
        self._content.grid_columnconfigure(0, weight=1)
        self._content.grid_rowconfigure(0, weight=1)

        self._build_reminders_page()
        self._build_timer_page()
        self._build_sounds_page()

    def _show_page(self, key):
        for k, btn in self._nav_btns.items():
            btn.configure(
                fg_color=("#3730a3","#2d2a6e") if k==key else "transparent",
                text_color="white" if k==key else "#a5b4fc"
            )
        for k, f in self._pages.items():
            f.grid() if k==key else f.grid_remove()

    # ── Reminders page ────────────────────────────────────────────────────────

    def _build_reminders_page(self):
        page = ctk.CTkFrame(self._content, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew", padx=24, pady=20)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        page.grid_remove()
        self._pages["reminders"] = page

        ctk.CTkLabel(page, text="Reminders",
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color=("#0f172a","#f8fafc"), anchor="w"
        ).grid(row=0, column=0, sticky="ew", pady=(0,16))

        # ── Form ──────────────────────────────────────────────────────────────
        form = ctk.CTkFrame(page,
            fg_color=("#ffffff","#1a1d2e"), corner_radius=12,
            border_width=1, border_color=("#e2e8f0","#2e3250"))
        form.grid(row=1, column=0, sticky="ew", pady=(0,16))
        form.columnconfigure((0,1,2), weight=1)

        for col, txt in enumerate(["LABEL","TIME  (HH:MM)","REPEAT"]):
            ctk.CTkLabel(form, text=txt,
                font=ctk.CTkFont(family="Segoe UI", size=10),
                text_color=("#64748b","#94a3b8"), anchor="w"
            ).grid(row=0, column=col, sticky="w",
                padx=(14 if col==0 else 6, 6 if col<2 else 14), pady=(14,3))

        self.rem_label = ctk.CTkEntry(form,
            placeholder_text="e.g. Take medicine", height=36, corner_radius=8,
            border_color=("#cbd5e1","#2e3250"))
        self.rem_label.grid(row=1, column=0, sticky="ew", padx=(14,6), pady=(0,10))

        self.rem_time = ctk.CTkEntry(form,
            placeholder_text="14:30", justify="center", height=36, corner_radius=8,
            border_color=("#cbd5e1","#2e3250"))
        self.rem_time.grid(row=1, column=1, sticky="ew", padx=6, pady=(0,10))

        self.rem_recur = ctk.CTkOptionMenu(form,
            values=RECUR_OPTIONS, height=36, corner_radius=8,
            fg_color=("#f1f5f9","#1e2130"),
            button_color=("#e2e8f0","#2e3250"),
            button_hover_color=("#cbd5e1","#3a3f60"),
            text_color=("#0f172a","#f1f5f9"),
            dropdown_fg_color=("#ffffff","#1a1d2e"),
            command=self._on_recur_change)
        self.rem_recur.set("Once")
        self.rem_recur.grid(row=1, column=2, sticky="ew", padx=(6,14), pady=(0,10))

        # Custom schedule button (shown only when Custom selected)
        self._custom_btn = ctk.CTkButton(form,
            text="⚙  Configure Custom Schedule",
            height=32, corner_radius=8,
            fg_color=("#e0e7ff","#2e3a6e"),
            hover_color=("#c7d2fe","#3a4a80"),
            text_color=("#3730a3","#a5b4fc"),
            font=ctk.CTkFont(size=12),
            command=self._open_custom_dialog)
        self._custom_btn.grid(row=2, column=0, columnspan=3, sticky="ew", padx=14, pady=(0,8))
        self._custom_btn.grid_remove()

        # Custom schedule summary label
        self._custom_summary = ctk.CTkLabel(form,
            text="", font=ctk.CTkFont(size=10),
            text_color=("#6366f1","#818cf8"), anchor="w")
        self._custom_summary.grid(row=3, column=0, columnspan=3, sticky="ew", padx=14, pady=(0,4))
        self._custom_summary.grid_remove()

        ctk.CTkButton(form,
            text="Add Reminder",
            height=38, corner_radius=8,
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color="#6366f1", hover_color="#4f46e5",
            command=self._add_reminder
        ).grid(row=4, column=0, columnspan=3, sticky="ew", padx=14, pady=(0,14))

        # ── Active list ───────────────────────────────────────────────────────
        lf = ctk.CTkFrame(page, fg_color="transparent")
        lf.grid(row=2, column=0, sticky="nsew")
        lf.columnconfigure(0, weight=1)
        lf.rowconfigure(1, weight=1)

        ctk.CTkLabel(lf, text="Active",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=("#64748b","#94a3b8"), anchor="w"
        ).grid(row=0, column=0, sticky="w", pady=(0,6))

        self.rem_scroll = ctk.CTkScrollableFrame(lf,
            fg_color="transparent",
            scrollbar_button_color=("#cbd5e1","#2e3250"),
            scrollbar_button_hover_color=("#94a3b8","#4a5080"))
        self.rem_scroll.grid(row=1, column=0, sticky="nsew")
        self.rem_scroll.columnconfigure(0, weight=1)

        self.no_rem_lbl = ctk.CTkLabel(self.rem_scroll,
            text="No reminders yet.",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=("#94a3b8","#475569"))

    def _on_recur_change(self, val):
        if val == "Custom":
            self._custom_btn.grid()
            self._pending_custom = []
            self._custom_summary.configure(text="No schedule configured yet.")
            self._custom_summary.grid()
        else:
            self._custom_btn.grid_remove()
            self._custom_summary.grid_remove()
            self._pending_custom = []

    def _open_custom_dialog(self):
        dlg = CustomRecurDialog(self, existing=self._pending_custom)
        self.wait_window(dlg)
        if dlg.result is not None:
            self._pending_custom = dlg.result
            n = len(self._pending_custom)
            self._custom_summary.configure(
                text=f"✓ {n} schedule entr{'y' if n==1 else 'ies'} configured")

    # ── Timer page ────────────────────────────────────────────────────────────

    def _build_timer_page(self):
        page = ctk.CTkFrame(self._content, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew", padx=24, pady=20)
        page.columnconfigure(0, weight=1)
        page.grid_remove()
        self._pages["timer"] = page

        ctk.CTkLabel(page, text="Timer",
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color=("#0f172a","#f8fafc"), anchor="w"
        ).grid(row=0, column=0, sticky="ew", pady=(0,20))

        clock = ctk.CTkFrame(page,
            fg_color=("#ffffff","#1a1d2e"), corner_radius=16,
            border_width=1, border_color=("#e2e8f0","#2e3250"))
        clock.grid(row=1, column=0, sticky="ew")
        clock.columnconfigure(0, weight=1)

        self.timer_display = ctk.CTkLabel(clock,
            text="00:00",
            font=ctk.CTkFont(family="Segoe UI", size=72, weight="bold"),
            text_color="#6366f1")
        self.timer_display.grid(row=0, column=0, pady=(32,8))

        self.timer_sub = ctk.CTkLabel(clock,
            text="Enter a duration and press Start",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=("#64748b","#94a3b8"))
        self.timer_sub.grid(row=1, column=0, pady=(0,28))

        ctk.CTkLabel(page, text="DURATION  (minutes)",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=("#64748b","#94a3b8"), anchor="w"
        ).grid(row=2, column=0, sticky="w", pady=(24,4))

        self.timer_entry = ctk.CTkEntry(page,
            placeholder_text="25", justify="center", height=42, corner_radius=10,
            font=ctk.CTkFont(family="Segoe UI", size=18),
            border_color=("#cbd5e1","#2e3250"))
        self.timer_entry.grid(row=3, column=0, sticky="ew", pady=(0,16))

        btns = ctk.CTkFrame(page, fg_color="transparent")
        btns.grid(row=4, column=0)

        ctk.CTkButton(btns, text="▶   Start",
            width=160, height=44, corner_radius=10,
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            fg_color="#22c55e", hover_color="#16a34a",
            command=self._start_timer
        ).grid(row=0, column=0, padx=(0,10))

        ctk.CTkButton(btns, text="■   Cancel",
            width=130, height=44, corner_radius=10,
            font=ctk.CTkFont(family="Segoe UI", size=14),
            fg_color=("#e2e8f0","#2e3250"), hover_color=("#cbd5e1","#3a3f60"),
            text_color=("#0f172a","#f1f5f9"),
            command=self._cancel_timer
        ).grid(row=0, column=1)

    # ── Sounds page ───────────────────────────────────────────────────────────

    def _build_sounds_page(self):
        page = ctk.CTkFrame(self._content, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew", padx=24, pady=20)
        page.columnconfigure(0, weight=1)
        page.grid_remove()
        self._pages["sounds"] = page

        ctk.CTkLabel(page, text="Sounds",
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color=("#0f172a","#f8fafc"), anchor="w"
        ).grid(row=0, column=0, sticky="ew", pady=(0,8))

        ctk.CTkLabel(page, text="Separate MP3 files for reminders and timer.",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=("#64748b","#94a3b8"), anchor="w"
        ).grid(row=1, column=0, sticky="ew", pady=(0,20))

        card = ctk.CTkFrame(page,
            fg_color=("#ffffff","#1a1d2e"), corner_radius=12,
            border_width=1, border_color=("#e2e8f0","#2e3250"))
        card.grid(row=2, column=0, sticky="ew")
        card.columnconfigure(0, weight=1)

        def section(row, icon, title):
            f = ctk.CTkFrame(card, fg_color="transparent")
            f.grid(row=row, column=0, sticky="ew", padx=16, pady=(16,12))
            f.columnconfigure(0, weight=1)
            ctk.CTkLabel(f, text=f"{icon}  {title}",
                font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
                text_color=("#0f172a","#f1f5f9"), anchor="w"
            ).grid(row=0, column=0, sticky="w", pady=(0,10))
            return f

        s1 = section(0, "🔔", "Reminder Sound")
        self.rsound_row = SoundRow(s1, "MP3 file",
            initial=self._rsound,
            on_change=lambda p: self._autosave_sound("r", p))
        self.rsound_row.grid(row=1, column=0, sticky="ew")

        ctk.CTkFrame(card, height=1, fg_color=("#e2e8f0","#2e3250")
        ).grid(row=1, column=0, sticky="ew", padx=16)

        s2 = section(2, "⏱", "Timer Sound")
        self.tsound_row = SoundRow(s2, "MP3 file",
            initial=self._tsound,
            on_change=lambda p: self._autosave_sound("t", p))
        self.tsound_row.grid(row=1, column=0, sticky="ew")

        ctk.CTkButton(card, text="Save", height=38, corner_radius=8,
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color="#6366f1", hover_color="#4f46e5",
            command=self._save_sounds
        ).grid(row=3, column=0, sticky="ew", padx=16, pady=(8,16))

    # ── Sound logic ───────────────────────────────────────────────────────────

    def _autosave_sound(self, kind, path):
        if kind == "r": self._rsound = path
        else:           self._tsound = path
        save_json(CONFIG_FILE, {"reminder_sound": self._rsound, "timer_sound": self._tsound})

    def _save_sounds(self):
        self._rsound = self.rsound_row.get()
        self._tsound = self.tsound_row.get()
        save_json(CONFIG_FILE, {"reminder_sound": self._rsound, "timer_sound": self._tsound})
        messagebox.showinfo("Saved", "Sound settings saved.")

    def _play(self, path):
        if path and os.path.exists(path):
            threading.Thread(target=lambda:(
                pygame.mixer.music.load(path), pygame.mixer.music.play()
            ), daemon=True).start()

    def _notify(self, title, msg, path):
        self._play(path)
        self.after(0, lambda: self._toast(title, msg))

    def _toast(self, title, msg):
        t = Toast(); t.text_fields = [title, msg]; toaster.show_toast(t)

    def _need_sound(self, kind):
        p = self._rsound if kind=="r" else self._tsound
        if not p:
            messagebox.showwarning("No Sound",
                f"Go to Sounds and set a file for {'Reminder' if kind=='r' else 'Timer'}.")
            return False
        return True

    # ── Reminder logic ────────────────────────────────────────────────────────

    def _add_reminder(self):
        if not self._need_sound("r"): return
        label = self.rem_label.get().strip()
        recur = self.rem_recur.get()

        if recur == "Custom":
            if not self._pending_custom:
                messagebox.showerror("No Schedule",
                    "Click 'Configure Custom Schedule' and add at least one entry.")
                return
            nd = self._next_custom_dt(self._pending_custom)
            if nd is None:
                messagebox.showerror("No Future Date",
                    "All custom schedule dates are in the past.")
                return
            rem = {
                "id": str(uuid.uuid4()),
                "label": label or "Reminder",
                "time": "",
                "recur": "Custom",
                "schedules": self._pending_custom,
                "next_dt": nd,
                "next_dt_str": nd.isoformat()
            }
        else:
            t = self.rem_time.get().strip()
            if not t:
                messagebox.showerror("Missing","Enter a time."); return
            try: datetime.strptime(t, "%H:%M")
            except ValueError:
                messagebox.showerror("Invalid","Use HH:MM 24-hour format."); return
            nd = next_trigger_standard(t, recur)
            rem = {
                "id": str(uuid.uuid4()),
                "label": label or "Reminder",
                "time": t,
                "recur": recur,
                "next_dt": nd,
                "next_dt_str": nd.isoformat()
            }

        self.reminders.append(rem)
        self._save_reminders()
        self._refresh_cards()
        self.rem_label.delete(0,"end")
        self.rem_time.delete(0,"end")
        self.rem_recur.set("Once")
        self._custom_btn.grid_remove()
        self._custom_summary.grid_remove()
        self._pending_custom = []

    def _next_custom_dt(self, schedules, after=None):
        candidates = []
        for s in schedules:
            dt = next_trigger_for_schedule(s, after=after)
            if dt: candidates.append(dt)
        return min(candidates) if candidates else None

    def _delete_reminder(self, rid):
        self.reminders = [r for r in self.reminders if r["id"] != rid]
        self._save_reminders(); self._refresh_cards()

    def _refresh_cards(self):
        for w in self._cards.values(): w.destroy()
        self._cards.clear()
        if not self.reminders:
            self.no_rem_lbl.grid(row=0, column=0, pady=24)
        else:
            self.no_rem_lbl.grid_remove()
            for i, rem in enumerate(self.reminders):
                c = ReminderCard(self.rem_scroll, rem, on_delete=self._delete_reminder)
                c.grid(row=i, column=0, sticky="ew", pady=2)
                self._cards[rem["id"]] = c

    def _save_reminders(self):
        save_json(REMINDERS_FILE,
            [{k:v for k,v in r.items() if k!="next_dt"} for r in self.reminders])

    # ── Timer logic ───────────────────────────────────────────────────────────

    def _start_timer(self):
        if not self._need_sound("t"): return
        if self.timer_running: return
        try: mins = float(self.timer_entry.get())
        except ValueError:
            messagebox.showerror("Invalid","Enter minutes as a number."); return
        secs = int(mins * 60)
        if secs <= 0: return
        self.timer_secs = secs
        self.timer_running = True
        self.timer_sub.configure(text="Running…")

    def _cancel_timer(self):
        self.timer_running = False; self.timer_secs = 0
        self.timer_display.configure(text="00:00")
        self.timer_sub.configure(text="Cancelled.")

    # ── Tick ──────────────────────────────────────────────────────────────────

    def _tick(self):
        now = datetime.now()
        fired = False

        for rem in self.reminders:
            delta = (rem["next_dt"] - now).total_seconds()

            if delta <= 0 and not fired:
                fired = True
                self._notify("Reminder", rem["label"], self._rsound)
                recur = rem.get("recur","Once")

                if recur == "Once":
                    self.reminders = [r for r in self.reminders if r["id"] != rem["id"]]
                    self._save_reminders(); self._refresh_cards()
                elif recur == "Custom":
                    nd = self._next_custom_dt(rem.get("schedules",[]), after=now)
                    if nd:
                        rem["next_dt"] = nd
                        rem["next_dt_str"] = nd.isoformat()
                        self._save_reminders()
                        c = self._cards.get(rem["id"])
                        if c: c.update_countdown((nd - now).total_seconds())
                    else:
                        # all custom dates exhausted
                        self.reminders = [r for r in self.reminders if r["id"] != rem["id"]]
                        self._save_reminders(); self._refresh_cards()
                else:
                    nd = next_trigger_standard(rem["time"], recur, after=now)
                    rem["next_dt"] = nd
                    rem["next_dt_str"] = nd.isoformat()
                    self._save_reminders()
                    c = self._cards.get(rem["id"])
                    if c: c.update_countdown((nd - now).total_seconds())
            else:
                c = self._cards.get(rem["id"])
                if c: c.update_countdown(delta)

        if self.timer_running:
            if self.timer_secs > 0:
                m, s = divmod(self.timer_secs, 60)
                self.timer_display.configure(text=f"{m:02d}:{s:02d}")
                self.timer_secs -= 1
            else:
                self.timer_display.configure(text="00:00")
                self.timer_sub.configure(text="Done! ✓")
                self._notify("Timer","Timer finished!", self._tsound)
                self.timer_running = False

        self.after(1000, self._tick)


if __name__ == "__main__":
    app = App()
    app.mainloop()
