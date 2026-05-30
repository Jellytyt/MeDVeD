from __future__ import annotations

import base64
import binascii
import ctypes
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from collections import deque
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, Y, BooleanVar, Canvas, Menu, StringVar, filedialog, ttk
from tkinter.scrolledtext import ScrolledText

import customtkinter as ctk
from typing import Any, Dict, List, Optional

import pystray
from PIL import Image, ImageDraw

try:
    from plyer import notification as plyer_notification
except ImportError:
    plyer_notification = None

from config import build_sing_box_config
from models import VlessProfile
from parser import parse_link, profile_to_vless_link
from storage import get_user_data_root, load_profiles, load_settings, save_profiles, save_settings


__version__ = "0.9.4"
GITHUB_REPO = "Jellytyt/MeDVeD"


_TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "ru": {
        "connect": "Подключиться",
        "connected": "Подключено",
        "active_server": "Активный сервер:",
        "server": "Сервер:",
        "profiles_page": "Профили и подписки",
        "log_page": "Журнал",
        "settings_page": "Настройки",
        "back": "← Назад",
        "quit": "✕  Выход",
        "save": "Сохранить",
        "delete": "Удалить",
        "import": "Импорт",
        "export": "Экспорт",
        "speedtest": "Speedtest",
        "check_pings": "Проверить пинги",
        "copy_link": "Скопировать ссылку",
        "no_profiles_title": "Нет профилей",
        "no_profiles_body": "Откройте «Профили и подписки» в меню и добавьте сервер или подписку.",
        "auto_label_switch": "Авто (быстрейший из всех)",
        "auto_label_fixed": "Авто (лучший на старте)",
        "auto_label_fixed_to": "Авто (фикс: {name})",
        "update_check": "Проверить обновления",
        "update_available": "🔄  Обновить до {version}",
        "checking_updates": "Проверяю обновления…",
        "up_to_date": "У тебя последняя версия (v{version})",
        "lang_change_restart": "Перезапустите MeDVeD чтобы сменить язык интерфейса.",
    },
    "en": {
        "connect": "Connect",
        "connected": "Connected",
        "active_server": "Active server:",
        "server": "Server:",
        "profiles_page": "Profiles & subscriptions",
        "log_page": "Log",
        "settings_page": "Settings",
        "back": "← Back",
        "quit": "✕  Quit",
        "save": "Save",
        "delete": "Delete",
        "import": "Import",
        "export": "Export",
        "speedtest": "Speedtest",
        "check_pings": "Test pings",
        "copy_link": "Copy link",
        "no_profiles_title": "No profiles",
        "no_profiles_body": "Open “Profiles & subscriptions” in the menu and add a server or subscription.",
        "auto_label_switch": "Auto (fastest server)",
        "auto_label_fixed": "Auto (best on start)",
        "auto_label_fixed_to": "Auto (locked: {name})",
        "update_check": "Check for updates",
        "update_available": "🔄  Update to {version}",
        "checking_updates": "Checking updates…",
        "up_to_date": "You have the latest version (v{version})",
        "lang_change_restart": "Restart MeDVeD to apply the new language.",
    },
}


def _t_for(lang: str, key: str, **kwargs: Any) -> str:
    table = _TRANSLATIONS.get(lang) or _TRANSLATIONS["ru"]
    text = table.get(key) or _TRANSLATIONS["ru"].get(key, key)
    return text.format(**kwargs) if kwargs else text


def _parse_version(value: str) -> tuple:
    """Parse 'v1.2.3', '1.2.3', '1.2' into a comparable tuple."""
    parts = []
    for chunk in value.lstrip("vV ").split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _format_bytes(bytes_count: float) -> str:
    """Format bytes to human-readable string."""
    if bytes_count < 1024:
        return f"{bytes_count:.0f} B"
    elif bytes_count < 1024 ** 2:
        return f"{bytes_count / 1024:.1f} KB"
    elif bytes_count < 1024 ** 3:
        return f"{bytes_count / 1024 ** 2:.1f} MB"
    else:
        return f"{bytes_count / 1024 ** 3:.2f} GB"


def _format_speed(bytes_per_sec: float) -> str:
    """Format speed to human-readable string."""
    return _format_bytes(bytes_per_sec) + "/s"


_KEYCODE_PASTE = 86  # V
_KEYCODE_COPY = 67   # C
_KEYCODE_CUT = 88    # X
_KEYCODE_SELECT_ALL = 65  # A


def _bind_clipboard_shortcuts(widget) -> None:
    """Make Ctrl+V/C/X/A work regardless of keyboard layout (Tkinter binds to
    English chars, so Cyrillic м/с/ч/ф on the same keys don't fire <Control-v>).
    For CTkEntry, we must bind to the inner tk.Entry (`_entry`) because keyboard
    events arrive there, not on the CTk wrapper frame."""
    target = getattr(widget, "_entry", None) or widget

    def handler(event):
        if not (event.state & 0x4):
            return None
        if event.keycode == _KEYCODE_PASTE:
            target.event_generate("<<Paste>>")
            return "break"
        if event.keycode == _KEYCODE_COPY:
            target.event_generate("<<Copy>>")
            return "break"
        if event.keycode == _KEYCODE_CUT:
            target.event_generate("<<Cut>>")
            return "break"
        if event.keycode == _KEYCODE_SELECT_ALL:
            try:
                target.select_range(0, "end")
                target.icursor("end")
            except Exception:
                pass
            return "break"
        return None
    target.bind("<KeyPress>", handler, add="+")


_KILL_SWITCH_RULE_NAME = "MeDVeD-KillSwitch"


def _kill_switch_engage() -> Optional[str]:
    """Block all outbound traffic except loopback (127.0.0.0/8) and link-local.
    Called when sing-box dies unexpectedly while kill_switch is on. The user
    has to disconnect/reconnect (or quit app) to lift the block."""
    if os.name != "nt":
        return "kill switch supported only on Windows"
    try:
        subprocess.run(
            ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={_KILL_SWITCH_RULE_NAME}"],
            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        result = subprocess.run(
            [
                "netsh", "advfirewall", "firewall", "add", "rule",
                f"name={_KILL_SWITCH_RULE_NAME}",
                "dir=out", "action=block", "enable=yes", "profile=any",
                "remoteip=0.0.0.0-126.255.255.255,128.0.0.0-169.253.255.255,169.255.0.0-255.255.255.255",
            ],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            return result.stderr.strip() or result.stdout.strip() or "netsh failed"
        return None
    except Exception as error:
        return f"{type(error).__name__}: {error}"


def _kill_switch_release() -> None:
    if os.name != "nt":
        return
    try:
        subprocess.run(
            ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={_KILL_SWITCH_RULE_NAME}"],
            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        pass


def _get_hwid() -> str:
    """Read Windows MachineGuid (used by many providers as device fingerprint
    via X-Hwid header — e.g. Karing/Happ-style subscriptions)."""
    if os.name != "nt":
        return ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
        return str(value).strip()
    except Exception:
        return ""


def _tcp_ping(host: str, port: int, timeout: float = 3.0) -> Optional[float]:
    """Measure TCP-handshake time in ms via time.perf_counter (nanosecond
    resolution, unlike time.time on Windows which jumps in ~15.6ms steps and
    rounds fast connects to 0)."""
    if not host or port <= 0:
        return None
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return (time.perf_counter() - start) * 1000.0
    except (OSError, socket.timeout):
        return None


_SINGLE_INSTANCE_MUTEX_NAME = "MeDVeD-VPN-SingleInstance"
_single_instance_handle = None


def _acquire_single_instance_lock() -> bool:
    """Return True if this process became the first instance. Returns False
    if another MeDVeD is already running — caller should activate that one
    and exit. Windows-only; on other OS just returns True."""
    global _single_instance_handle
    if os.name != "nt":
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        ERROR_ALREADY_EXISTS = 183
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        handle = kernel32.CreateMutexW(None, False, _SINGLE_INSTANCE_MUTEX_NAME)
        if not handle:
            return True
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        _single_instance_handle = handle
        return True
    except Exception:
        return True


def _activate_existing_window(title: str) -> bool:
    if os.name != "nt":
        return False
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, title)
        if not hwnd:
            return False
        SW_RESTORE = 9
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


_LOG_FILE_NAME = "app.log"
_LOG_MAX_BYTES = 1024 * 1024  # 1 MB before rotation


def _get_log_file_path() -> Path:
    """Persistent log lives next to the user's profiles/settings, NOT inside
    the exe folder — that one might be Program Files (read-only) and would also
    be wiped by our own auto-update Move-Item."""
    if os.name == "nt":
        base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or str(Path.home())
        return Path(base) / "vless_manager" / _LOG_FILE_NAME
    return Path.home() / ".vless_manager" / _LOG_FILE_NAME


def _write_log_line(line: str) -> None:
    """Append a single line to the persistent log, with size-based rotation.
    Silent on failure — logging itself must never crash the app."""
    try:
        path = _get_log_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > _LOG_MAX_BYTES:
            backup = path.with_suffix(path.suffix + ".1")
            try:
                if backup.exists():
                    backup.unlink()
                path.rename(backup)
            except Exception:
                pass
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
            if not line.endswith("\n"):
                f.write("\n")
    except Exception:
        pass


def _cleanup_stale_tun_adapters() -> None:
    """sing-box can leave behind 'singtunN' adapters if it was force-killed.
    On next start that can cause 'Cannot create a file when that file already
    exists'. We try to delete every adapter whose name starts with 'singtun'.
    Runs once at startup, silent on failure (best-effort cleanup)."""
    if os.name != "nt":
        return
    try:
        creationflags = subprocess.CREATE_NO_WINDOW
        result = subprocess.run(
            ["netsh", "interface", "show", "interface"],
            capture_output=True, text=True, timeout=5,
            encoding="cp866", errors="replace",
            creationflags=creationflags,
        )
        if result.returncode != 0:
            return
        for line in result.stdout.splitlines():
            tokens = line.strip().split()
            if not tokens:
                continue
            name = tokens[-1]
            if name.lower().startswith("singtun"):
                subprocess.run(
                    ["netsh", "interface", "set", "interface", f"name={name}", "admin=disable"],
                    capture_output=True, timeout=3,
                    creationflags=creationflags,
                )
    except Exception:
        pass


def _install_global_excepthooks() -> None:
    """Route every uncaught exception (main thread + worker threads) into the
    persistent log. Without this, a frozen GUI exe just silently disappears."""
    import traceback

    def _hook(exc_type, exc_value, exc_tb):
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        _write_log_line(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] UNCAUGHT:\n{msg}")

    sys.excepthook = lambda et, ev, tb: _hook(et, ev, tb)
    # threading.excepthook landed in 3.8 — guard just in case.
    if hasattr(threading, "excepthook"):
        threading.excepthook = lambda args: _hook(args.exc_type, args.exc_value, args.exc_traceback)


_AUTOSTART_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_AUTOSTART_VALUE_NAME = "MeDVeD"


def _set_autostart(enabled: bool, start_minimized: bool) -> Optional[str]:
    """Toggle 'launch on Windows boot' via HKCU\\...\\Run. Returns error or None."""
    if os.name != "nt":
        return "Только Windows"
    if not getattr(sys, "frozen", False):
        # In dev mode there's no exe to autostart — skip silently.
        return None
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _AUTOSTART_REG_KEY, 0, winreg.KEY_SET_VALUE,
        ) as key:
            if enabled:
                exe = str(Path(sys.executable).resolve())
                cmd = f'"{exe}" --minimized' if start_minimized else f'"{exe}"'
                winreg.SetValueEx(key, _AUTOSTART_VALUE_NAME, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, _AUTOSTART_VALUE_NAME)
                except FileNotFoundError:
                    pass
        return None
    except Exception as error:
        return f"{type(error).__name__}: {error}"


def _asset_path(name: str) -> Path:
    """Resolve a file in the assets/ folder, both in dev and frozen builds."""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / "assets" / name
        return Path(sys.executable).resolve().parent / "assets" / name
    return Path(__file__).resolve().parent / "assets" / name


def _is_admin() -> bool:
    if os.name != "nt":
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def _relaunch_as_admin() -> bool:
    if os.name != "nt":
        return False
    try:
        script = os.path.abspath(sys.argv[0])
        params = " ".join(f'"{a}"' for a in sys.argv[1:])
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, f'"{script}" {params}', None, 1)
        return int(ret) > 32
    except Exception:
        return False


class RoundButton:
    """Truly circular button (CTkButton only does rounded rectangles).
    Uses a Canvas with create_oval + create_text. Public API:
    `pack(...)`, `set_state(active=True/False, text=...)`."""

    def __init__(
        self,
        parent,
        size: int,
        text: str,
        command,
        fg_color: str,
        hover_color: str,
        active_color: str,
        active_hover: str,
        text_color: str = "#ffffff",
        bg_color: str = "#242424",
        font_size: int = 18,
    ) -> None:
        self.size = size
        self.command = command
        self._fg = fg_color
        self._hover = hover_color
        self._active_fg = active_color
        self._active_hover = active_hover
        self._is_active = False
        self._is_hover = False
        self.canvas = Canvas(parent, width=size, height=size, bg=bg_color, highlightthickness=0)
        self._circle = self.canvas.create_oval(2, 2, size - 2, size - 2, fill=fg_color, outline="")
        self._text_id = self.canvas.create_text(
            size // 2, size // 2, text=text, fill=text_color,
            font=("Segoe UI", font_size, "bold"),
        )
        self.canvas.bind("<Enter>", self._on_enter)
        self.canvas.bind("<Leave>", self._on_leave)
        self.canvas.bind("<Button-1>", self._on_click)

    def _current_color(self) -> str:
        if self._is_active:
            return self._active_hover if self._is_hover else self._active_fg
        return self._hover if self._is_hover else self._fg

    def _on_enter(self, _event) -> None:
        self._is_hover = True
        self.canvas.configure(cursor="hand2")
        self.canvas.itemconfig(self._circle, fill=self._current_color())

    def _on_leave(self, _event) -> None:
        self._is_hover = False
        self.canvas.configure(cursor="")
        self.canvas.itemconfig(self._circle, fill=self._current_color())

    def _on_click(self, _event) -> None:
        if self.command is None:
            return
        try:
            self.command()
        except Exception:
            pass

    def pack(self, **kwargs) -> None:
        self.canvas.pack(**kwargs)

    def set_state(self, active: bool, text: Optional[str] = None) -> None:
        self._is_active = active
        if text is not None:
            self.canvas.itemconfig(self._text_id, text=text)
        self.canvas.itemconfig(self._circle, fill=self._current_color())

    def update_background(self, bg_color: str, text_color: Optional[str] = None) -> None:
        """Repaint the canvas background to match a changed app theme so the
        button doesn't sit on a grey square. Optionally re-color the label too."""
        try:
            self.canvas.configure(bg=bg_color)
            if text_color is not None:
                self.canvas.itemconfig(self._text_id, fill=text_color)
        except Exception:
            pass


class VlessApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("MeDVeD")
        self.geometry("1040x820")
        self.minsize(920, 720)
        try:
            self.iconbitmap(default=str(_asset_path("medved.ico")))
        except Exception:
            pass

        self.settings = load_settings()
        self._apply_ttk_style()
        self.profiles: List[VlessProfile] = load_profiles(self.settings)
        self.process: Optional[subprocess.Popen[str]] = None
        self._process_lock = threading.Lock()
        self._api_port: Optional[int] = None
        self._monitor_generation = 0
        self._monitor_thread: Optional[threading.Thread] = None
        self._tray_icon: Optional[Any] = None
        self._quitting = False
        self._profile_pings: Dict[str, Optional[float]] = {}
        self._refresh_after_id: Optional[str] = None
        self._dl_history: deque = deque(maxlen=60)
        self._ul_history: deque = deque(maxlen=60)
        self._pending_profiles: List[VlessProfile] = []
        self._is_urltest = False
        self._self_heal_attempted = False
        self._settings_ui_ready = False
        self._update_available = False
        self._update_version = ""
        self._update_url = ""
        self._update_badge: Optional[Any] = None
        self._log_buffer: deque = deque(maxlen=500)
        self.log_widget: Optional[Any] = None
        self.profile_list: Optional[Any] = None
        self.active_server_var = StringVar(value="—")
        self.server_choice_var = StringVar(value=self._AUTO_KEY)

        # Stats tracking
        self._prev_rx: float = 0.0
        self._prev_tx: float = 0.0
        self._prev_time: float = 0.0
        self._total_rx: float = 0.0
        self._total_tx: float = 0.0
        self._last_ping_ms: float = 0.0

        self.selected_uuid: Optional[str] = None
        self.selected_group_url: Optional[str] = None
        self.selected_indices: List[int] = []
        self.link_var = StringVar()
        self.name_var = StringVar()
        self.subscription_var = StringVar()
        self.status_var = StringVar(value="Готово")
        self.settings_path_var = StringVar(value=self.settings.sing_box_path)
        self.active_var = BooleanVar(value=False)
        self.auto_connect_var = BooleanVar(value=self.settings.auto_connect_enabled)
        self.subscription_refresh_var = StringVar(value=str(self.settings.subscription_refresh_hours))
        self.notifications_var = BooleanVar(value=self.settings.notifications_enabled)
        self.bypass_ru_var = BooleanVar(value=self.settings.bypass_ru)
        self.kill_switch_var = BooleanVar(value=self.settings.kill_switch)
        self.urltest_auto_switch_var = BooleanVar(value=self.settings.urltest_auto_switch)
        self.autostart_var = BooleanVar(value=self.settings.auto_start_with_windows)
        self.start_minimized_var = BooleanVar(value=self.settings.start_minimized)
        self.appearance_var = StringVar(value=self.settings.appearance_mode)
        self.language_var = StringVar(value=self.settings.language)

        # Stats display variables
        self.dl_speed_var = StringVar(value="—")
        self.ul_speed_var = StringVar(value="—")
        self.total_dl_var = StringVar(value="—")
        self.total_ul_var = StringVar(value="—")
        self.ping_var = StringVar(value="—")

        self._build_ui()
        self.refresh_profiles()
        self._autodetect_sing_box_path()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._init_tray()
        if self.settings.auto_connect_enabled and self.settings.auto_connect_key:
            self.after(500, self._safe_auto_connect_startup)
        self._schedule_subscription_refresh()
        if getattr(sys, "frozen", False) and not GITHUB_REPO.startswith("USERNAME/"):
            self.after(5000, lambda: threading.Thread(target=self._check_for_update, daemon=True).start())

    def _resolved_bg_color(self) -> str:
        """Pick a hex bg matching the current CTk theme, for tk.Canvas children
        (which can't be transparent and need a solid color to blend in)."""
        try:
            return self._apply_appearance_mode(ctk.ThemeManager.theme["CTk"]["fg_color"])
        except Exception:
            return "#242424" if self._resolve_appearance_mode() == "dark" else "#fafafa"

    def _refresh_main_button_background(self) -> None:
        btn = getattr(self, "main_button", None)
        if btn is None:
            return
        btn.update_background(self._resolved_bg_color())

    def _resolve_appearance_mode(self) -> str:
        """Return concrete 'dark' or 'light' even when settings say 'system'."""
        mode = self.settings.appearance_mode
        if mode in ("dark", "light"):
            return mode
        try:
            return ctk.get_appearance_mode().lower()
        except Exception:
            return "dark"

    def _apply_ttk_style(self) -> None:
        """Style ttk widgets (Treeview, Spinbox) to match the current CTk theme.
        Called on startup and every time the theme is switched in settings."""
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        mode = self._resolve_appearance_mode()
        if mode == "light":
            bg = "#fafafa"
            bg_alt = "#e8e8e8"
            fg = "#1a1a1a"
            accent = "#1f6aa5"
            heading_hover_bg = "#d4d4d4"
        else:
            bg = "#212121"
            bg_alt = "#2b2b2b"
            fg = "#e0e0e0"
            accent = "#1f6aa5"
            heading_hover_bg = "#3a3a3a"
        style.configure(
            "Dark.Treeview",
            background=bg, foreground=fg, fieldbackground=bg,
            borderwidth=0, rowheight=24,
        )
        style.configure(
            "Dark.Treeview.Heading",
            background=bg_alt, foreground=fg, borderwidth=0,
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "Dark.Treeview",
            background=[("selected", accent)],
            foreground=[("selected", "#ffffff")],
        )
        style.map(
            "Dark.Treeview.Heading",
            background=[("active", heading_hover_bg)],
            foreground=[("active", fg)],
        )
        style.layout("Dark.Treeview", style.layout("Treeview"))
        style.configure(
            "Dark.TSpinbox",
            fieldbackground=bg_alt, foreground=fg, background=bg_alt,
            arrowcolor=fg, bordercolor=bg_alt, lightcolor=bg_alt, darkcolor=bg_alt,
        )

    def _section(self, parent, title: str) -> "ctk.CTkFrame":
        frame = ctk.CTkFrame(parent, corner_radius=8)
        if title:
            ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(size=12, weight="bold")).pack(
                anchor="w", padx=12, pady=(8, 2)
            )
        return frame

    def _build_ui(self) -> None:
        self.geometry("960x760")
        self.minsize(880, 720)

        self._burger_visible = False
        self._burger_dropdown: Optional[Any] = None

        self.view_container = ctk.CTkFrame(self, fg_color="transparent")
        self.view_container.pack(fill=BOTH, expand=True)

        self.bind("<Button-1>", self._global_click_for_menus, add="+")

        self._views: Dict[str, Any] = {}
        self._build_main_view()
        self._build_settings_view()
        self._build_profiles_view()
        self._build_log_view()

        self.current_view = "main"
        self._show_view("main")

    def _show_view(self, name: str) -> None:
        # Close any open dropdowns before switching screens — they're placed on
        # the root window so wouldn't disappear with the view.
        self._hide_burger()
        self._hide_server_menu()
        for v in self._views.values():
            v.pack_forget()
        view = self._views.get(name)
        if view is None:
            return
        view.pack(fill=BOTH, expand=True)
        self.current_view = name
        if name == "log" and self.log_widget is not None:
            try:
                self.log_widget.see(END)
            except Exception:
                pass
        self._render_update_badge()

    def _view_header(self, parent, title: str, back: bool = False) -> "ctk.CTkFrame":
        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.pack(fill=X, padx=16, pady=(16, 8))
        if back:
            ctk.CTkButton(
                header, text="← Назад", width=88, height=32,
                fg_color="#2b2b2b", hover_color="#3a3a3a",
                command=lambda: self._show_view("main"),
            ).pack(side=LEFT)
            ctk.CTkLabel(header, text=title, font=ctk.CTkFont(size=18, weight="bold")).pack(side=LEFT, padx=(12, 0))
        else:
            self.burger_button = ctk.CTkButton(
                header, text="☰", width=36, height=36, font=ctk.CTkFont(size=18),
                fg_color="#2b2b2b", hover_color="#3a3a3a",
                command=self._show_burger_menu,
            )
            self.burger_button.pack(side=LEFT)
            ctk.CTkLabel(header, text=title, font=ctk.CTkFont(size=20, weight="bold")).pack(side=LEFT, padx=(10, 0))
        return header

    def _build_main_view(self) -> None:
        view = ctk.CTkFrame(self.view_container, fg_color="transparent")
        self._view_header(view, "MeDVeD", back=False)

        body = ctk.CTkFrame(view, fg_color="transparent")
        body.pack(fill=BOTH, expand=True, padx=16, pady=(0, 16))

        button_box = ctk.CTkFrame(body, fg_color="transparent")
        button_box.pack(fill=BOTH, expand=True)

        ctk.CTkLabel(button_box, text=self._t("server"), font=ctk.CTkFont(size=11), text_color="#888888").pack(pady=(8, 0))
        self.server_button = ctk.CTkButton(
            button_box, text=f"{self._format_choice(self.server_choice_var.get())}  ▼",
            width=320, height=32,
            fg_color="#3a3a3a", hover_color="#4a4a4a",
            text_color="#e0e0e0",
            command=self._toggle_server_menu,
        )
        self.server_button.pack(pady=(2, 0))
        self._server_menu_visible = False
        self._server_dropdown: Optional[Any] = None

        self.main_button = RoundButton(
            button_box, size=220, text=self._t("connect"),
            fg_color="#3a3a3a", hover_color="#4a4a4a",
            active_color="#2e7d32", active_hover="#388e3c",
            text_color="#ffffff", bg_color=self._resolved_bg_color(), font_size=18,
            command=self._toggle_connection,
        )
        self.main_button.pack(pady=(24, 10))

        ctk.CTkLabel(
            button_box, text=self._t("active_server"), font=ctk.CTkFont(size=10), text_color="#888888",
        ).pack(pady=(8, 0))
        ctk.CTkLabel(
            button_box, textvariable=self.active_server_var, font=ctk.CTkFont(size=13, weight="bold"),
        ).pack()
        self.sub_info_label = ctk.CTkLabel(
            button_box, text="", font=ctk.CTkFont(size=10), text_color="#888888",
        )
        self.sub_info_label.pack(pady=(4, 0))
        self.after(100, self._refresh_subscription_info_label)

        stats_card = ctk.CTkFrame(body, corner_radius=10)
        stats_card.pack(fill=X, pady=(16, 0))
        stats_grid = ctk.CTkFrame(stats_card, fg_color="transparent")
        stats_grid.pack(fill=X, padx=14, pady=12)

        ctk.CTkLabel(stats_grid, text="⬇", font=ctk.CTkFont(size=14)).grid(row=0, column=0, sticky="w", padx=(0, 6))
        ctk.CTkLabel(stats_grid, textvariable=self.dl_speed_var, text_color="#4caf50", font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=1, sticky="w", padx=(0, 20))
        ctk.CTkLabel(stats_grid, text="⬆", font=ctk.CTkFont(size=14)).grid(row=0, column=2, sticky="w", padx=(0, 6))
        ctk.CTkLabel(stats_grid, textvariable=self.ul_speed_var, text_color="#ef5350", font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=3, sticky="w", padx=(0, 20))
        ctk.CTkLabel(stats_grid, text="📶", font=ctk.CTkFont(size=14)).grid(row=0, column=4, sticky="w", padx=(0, 6))
        ctk.CTkLabel(stats_grid, textvariable=self.ping_var, font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=5, sticky="w")

        ctk.CTkLabel(stats_grid, text="📥 Всего:", font=ctk.CTkFont(size=10), text_color="#888888").grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ctk.CTkLabel(stats_grid, textvariable=self.total_dl_var, font=ctk.CTkFont(size=11)).grid(row=1, column=2, columnspan=2, sticky="w", pady=(8, 0))
        ctk.CTkLabel(stats_grid, text="📤 Всего:", font=ctk.CTkFont(size=10), text_color="#888888").grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 0))
        ctk.CTkLabel(stats_grid, textvariable=self.total_ul_var, font=ctk.CTkFont(size=11)).grid(row=2, column=2, columnspan=2, sticky="w", pady=(2, 0))

        self.sparkline = Canvas(stats_grid, height=50, bg="#1a1a1a", highlightthickness=0)
        self.sparkline.grid(row=3, column=0, columnspan=6, sticky="we", pady=(10, 0))
        stats_grid.columnconfigure(5, weight=1)

        self._views["main"] = view

    # ========== SING-BOX BINARY ==========

    def _ensure_sing_box_binary(self) -> Path:
        explicit = self.settings.sing_box_path.strip()
        candidates: list[Path] = []

        if explicit:
            explicit_path = Path(explicit)
            candidates.append(explicit_path)
            if not explicit_path.suffix:
                candidates.append(explicit_path.with_suffix(".exe"))

        if getattr(sys, "frozen", False):
            bundle_dir = Path(sys.executable).resolve().parent
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                candidates.append(Path(meipass) / "sing-box.exe")
        else:
            bundle_dir = Path(__file__).resolve().parent

        candidates.extend(
            [
                bundle_dir / "sing-box.exe",
                bundle_dir / "sing-box",
                get_user_data_root() / "bin" / "sing-box.exe",
            ]
        )

        for candidate in candidates:
            if candidate.is_file():
                resolved = candidate.resolve()
                return resolved

        found_in_path = shutil.which(explicit) if explicit else None
        if not found_in_path:
            found_in_path = shutil.which("sing-box")
        if found_in_path:
            resolved = Path(found_in_path).resolve()
            return resolved

        self.log("sing-box не найден. Скачиваю автоматически...")
        downloaded = self._download_sing_box_binary()
        self.log(f"sing-box установлен: {downloaded}")
        return downloaded

    def _download_sing_box_binary(self) -> Path:
        machine = platform.machine().lower()
        arch = "arm64" if "arm" in machine else "amd64"
        api_url = "https://api.github.com/repos/SagerNet/sing-box/releases/latest"
        request = urllib.request.Request(
            api_url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "MeDVeD/1.0",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                release_data = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as error:
            raise FileNotFoundError(
                "Не удалось скачать sing-box автоматически. "
                "Подключите интернет или укажите путь к sing-box.exe вручную."
            ) from error

        asset = None
        for item in release_data.get("assets", []):
            name = str(item.get("name", "")).lower()
            if name.endswith(".zip") and f"windows-{arch}" in name:
                asset = item
                break

        if not asset:
            raise FileNotFoundError(
                f"В релизе sing-box не найден архив для Windows {arch}. "
                "Скачайте sing-box.exe вручную и укажите путь в настройках."
            )

        download_url = str(asset.get("browser_download_url", ""))
        if not download_url:
            raise FileNotFoundError("Не найден URL для скачивания sing-box.")

        target_dir = get_user_data_root() / "bin"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / "sing-box.exe"

        with urllib.request.urlopen(
            urllib.request.Request(download_url, headers={"User-Agent": "MeDVeD/1.0"}),
            timeout=60,
        ) as response:
            archive_bytes = response.read()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as temp_file:
            temp_file.write(archive_bytes)
            temp_zip_path = Path(temp_file.name)

        try:
            with zipfile.ZipFile(temp_zip_path, "r") as archive:
                exe_member = next(
                    (name for name in archive.namelist() if name.lower().endswith("sing-box.exe")),
                    None,
                )
                if not exe_member:
                    raise FileNotFoundError(
                        "В архиве sing-box не найден sing-box.exe. "
                        "Скачайте бинарник вручную и укажите путь в настройках."
                    )
                with archive.open(exe_member, "r") as source, target_path.open("wb") as target:
                    target.write(source.read())
        finally:
            temp_zip_path.unlink(missing_ok=True)

        return target_path.resolve()

    # ========== PROFILE LIST ==========

    def refresh_profiles(self) -> None:
        self._refresh_server_menu()
        if self.profile_list is None:
            return
        for item in self.profile_list.get_children():
            self.profile_list.delete(item)

        groups: Dict[str, List[int]] = {}
        for index, profile in enumerate(self.profiles):
            groups.setdefault(profile.source_url or "", []).append(index)

        for source_url, indices in sorted(groups.items(), key=lambda kv: (kv[0] == "", kv[0])):
            if source_url:
                label = source_url
                if source_url.startswith("karing://"):
                    label = f"Karing: {source_url[len('karing://'):]}"
                elif source_url.startswith("http"):
                    label = f"Подписка: {source_url}"
                group_iid = f"g:{source_url}"
            else:
                label = "Импортированные вручную"
                group_iid = "g:_manual"
            self.profile_list.insert("", END, iid=group_iid, text=f"{label}  ({len(indices)})", open=True)
            for index in indices:
                profile = self.profiles[index]
                transport = f"{profile.protocol}/{profile.type or 'tcp'}"
                ping = self._format_profile_ping(self._profile_ping_key(profile))
                self.profile_list.insert(
                    group_iid, END, iid=str(index),
                    text=profile.name,
                    values=(profile.server, transport, ping),
                )

        if self.selected_uuid is not None:
            for index, profile in enumerate(self.profiles):
                if profile.uuid == self.selected_uuid:
                    self.profile_list.selection_set(str(index))
                    self.profile_list.see(str(index))
                    break

    @staticmethod
    def _profile_ping_key(profile: VlessProfile) -> str:
        return f"{profile.uuid or profile.password}|{profile.server}|{profile.port}"

    def _selected_single_profile(self) -> Optional[VlessProfile]:
        if len(self.selected_indices) == 1:
            return self.profiles[self.selected_indices[0]]
        if self.selected_uuid:
            return next((p for p in self.profiles if p.uuid == self.selected_uuid), None)
        return None

    def _format_profile_ping(self, key: str) -> str:
        if key not in self._profile_pings:
            return "—"
        value = self._profile_pings[key]
        if value is None:
            return "timeout"
        if value < 1.0:
            return "<1 мс"
        return f"{int(round(value))} мс"

    def log(self, message: str) -> None:
        self._log_buffer.append(message)
        _write_log_line(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}")
        if self.log_widget is not None:
            try:
                self.log_widget.configure(state="normal")
                self.log_widget.insert(END, message + "\n")
                self.log_widget.see(END)
                self.log_widget.configure(state="disabled")
            except Exception:
                self.log_widget = None
        short = message if len(message) <= 70 else message[:67] + "..."
        self.status_var.set(short)

    def _log_show_menu(self, event) -> None:
        try:
            self.log_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.log_menu.grab_release()

    def _log_copy_selection(self) -> None:
        try:
            text = self.log_widget.get("sel.first", "sel.last")
        except Exception:
            return
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)

    def _log_copy_all(self) -> None:
        text = self.log_widget.get("1.0", "end-1c")
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)

    def _log_select_all(self) -> None:
        self.log_widget.tag_add("sel", "1.0", "end-1c")

    def _log_clear(self) -> None:
        self.log_widget.configure(state="normal")
        self.log_widget.delete("1.0", END)
        self.log_widget.configure(state="disabled")

    def _log_copy_selection_event(self, _event) -> str:
        self._log_copy_selection()
        return "break"

    def _log_select_all_event(self, _event) -> str:
        self._log_select_all()
        return "break"

    def on_profile_select(self, _event: object) -> None:
        selection = self.profile_list.selection()
        self.selected_uuid = None
        self.selected_group_url = None
        self.selected_indices = []

        if not selection:
            return

        groups = [iid for iid in selection if iid.startswith("g:")]
        profile_iids = [iid for iid in selection if not iid.startswith("g:")]

        for iid in profile_iids:
            try:
                index = int(iid)
            except ValueError:
                continue
            if 0 <= index < len(self.profiles):
                self.selected_indices.append(index)

        if self.selected_indices:
            if len(self.selected_indices) == 1:
                profile = self.profiles[self.selected_indices[0]]
                self.selected_uuid = profile.uuid
                self.name_var.set(profile.name)
            return

        if groups:
            self.selected_group_url = groups[0][len("g:"):]

    def _has_uuid(self, uuid: str) -> bool:
        return any(p.uuid == uuid for p in self.profiles)

    # ========== IMPORT / EXPORT ==========

    def import_profile(self) -> None:
        link = self.link_var.get().strip()
        if not link:
            self._show_toast("MeDVeD", "Вставьте ссылку (vless / vmess / trojan / ss / hysteria2).", "warn")
            return

        try:
            profile = parse_link(link, self.name_var.get().strip() or "Imported")
        except ValueError as error:
            self._show_toast("Ошибка импорта", str(error), "error")
            return

        dedup_key = (profile.protocol, profile.uuid or profile.password, profile.server, profile.port)
        if any((p.protocol, p.uuid or p.password, p.server, p.port) == dedup_key for p in self.profiles):
            self._show_toast("MeDVeD", "Такой профиль уже существует.", "warn")
            return

        self._append_profile(profile)
        self.link_var.set("")
        self.name_var.set("")
        self.log(f"Импортирован профиль: {profile.name} ({profile.protocol})")

    def import_subscription(self) -> None:
        url = self.subscription_var.get().strip()
        if not url:
            self._show_toast("MeDVeD", "Вставьте URL подписки.", "warn")
            return

        def worker() -> None:
            try:
                profiles = self._fetch_subscription_profiles(url)
                if not profiles:
                    self.after(0, lambda: self._show_toast("MeDVeD", "В подписке не найдено профилей.", "info"))
                    return

                if url not in self.settings.subscriptions:
                    self.settings.subscriptions.append(url)
                    save_settings(self.settings)

                self.after(0, self._append_profiles, profiles)
                self.after(0, self.log, f"Импортировано профилей из подписки: {len(profiles)}")
            except Exception as error:
                self.after(0, lambda e=error: self._show_toast("MeDVeD", str(e), "error"))

        threading.Thread(target=worker, daemon=True).start()

    def refresh_subscriptions(self) -> None:
        subscriptions = list(self.settings.subscriptions)
        if not subscriptions:
            self._show_toast("MeDVeD", "Подписок пока нет.", "info")
            return

        subscription_urls = set(subscriptions)

        def worker() -> None:
            try:
                all_new_profiles: List[VlessProfile] = []
                for url in subscriptions:
                    profiles = self._fetch_subscription_profiles(url)
                    all_new_profiles.extend(profiles)

                def update() -> None:
                    self.profiles = [p for p in self.profiles if p.source_url not in subscription_urls]
                    existing_keys = {
                        (p.uuid or p.password, p.server, p.port) for p in self.profiles
                    }
                    added = 0
                    for profile in all_new_profiles:
                        key = (profile.uuid or profile.password, profile.server, profile.port)
                        if key in existing_keys:
                            continue
                        self.profiles.append(profile)
                        existing_keys.add(key)
                        added += 1
                    save_profiles(self.profiles, self.settings)
                    self.refresh_profiles()
                    self.log(f"Подписки обновлены, добавлено новых профилей: {added}")
                    if added > 0:
                        self._show_snackbar(f"Подписки обновлены: +{added} профилей", "ok")
                    else:
                        self._show_snackbar("Подписки обновлены: новых профилей нет", "info")

                self.after(0, update)
            except Exception as error:
                self.after(0, lambda e=error: self._show_toast("MeDVeD", str(e), "error"))

        threading.Thread(target=worker, daemon=True).start()

    _SUBSCRIPTION_USER_AGENTS = (
        "v2rayN/7.0",
        "clash-verge/2.0",
        "sing-box/1.13.12",
        "Hiddify-Next/2.5.6",
        "karing/1.1.6",
        "Mozilla/5.0",
    )

    def _fetch_subscription_profiles(self, url: str) -> List[VlessProfile]:
        last_payload = ""
        last_error: Optional[str] = None
        got_fake = False
        hwid = _get_hwid()
        for user_agent in self._SUBSCRIPTION_USER_AGENTS:
            try:
                headers = {"User-Agent": user_agent}
                if hwid:
                    headers["X-Hwid"] = hwid
                    headers["X-DEVICE-ID"] = hwid
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = response.read().decode("utf-8", errors="ignore")
                    sub_info_header = response.headers.get("subscription-userinfo") or response.headers.get("Subscription-Userinfo")
                    if sub_info_header:
                        self.after(0, self.log, f"Подписка прислала лимиты: {sub_info_header}")
                        self._save_subscription_info(url, sub_info_header)
                    else:
                        self.after(0, self.log, "Подписка не сообщила лимиты (нет заголовка subscription-userinfo)")
            except Exception as error:
                last_error = f"{type(error).__name__}: {error}"
                continue

            decoded = self._decode_subscription_payload(payload)
            if not any(s in decoded for s in ("vless://", "vmess://", "trojan://", "ss://", "hysteria2://", "hy2://", "tuic://")):
                # Maybe it's Clash YAML
                clash_profiles = self._try_parse_clash_yaml(decoded, url)
                if clash_profiles:
                    return clash_profiles
                last_payload = decoded[:200]
                continue

            links = [line.strip() for line in decoded.splitlines() if line.strip()]
            profiles: List[VlessProfile] = []
            for index, link in enumerate(links, start=1):
                try:
                    profile = parse_link(link, f"Subscription {index}", source_url=url)
                except ValueError:
                    continue
                if self._is_fake_profile(profile):
                    got_fake = True
                    continue
                profiles.append(profile)
            if profiles:
                return profiles

        if got_fake:
            raise RuntimeError(
                "Сервер подписки отдаёт только заглушку «Приложение не поддерживается» "
                "(сервер 127.0.0.1:1) — этот провайдер блокирует все клиенты кроме своего "
                "официального (например, Happ). Сменить провайдера или импортировать "
                "VLESS-ссылки вручную."
            )
        if last_error:
            raise RuntimeError(f"Не удалось загрузить подписку: {last_error}")
        raise RuntimeError(
            f"Подписка не содержит VLESS-ссылок. Ответ сервера: {last_payload!r}"
        )

    def _save_subscription_info(self, url: str, header_value: str) -> None:
        """Parse 'upload=N; download=N; total=N; expire=UNIX_TS' and store per-url."""
        info: Dict[str, int] = {}
        for part in header_value.split(";"):
            piece = part.strip()
            if "=" not in piece:
                continue
            k, v = piece.split("=", 1)
            try:
                info[k.strip().lower()] = int(v.strip())
            except (TypeError, ValueError):
                continue
        if not info:
            return
        self.settings.subscription_info[url] = info
        try:
            save_settings(self.settings)
        except Exception:
            pass
        self.after(0, self._refresh_subscription_info_label)

    def _refresh_subscription_info_label(self) -> None:
        label = getattr(self, "sub_info_label", None)
        if label is None:
            return
        # Aggregate across all subscriptions
        used = 0
        total = 0
        earliest_expire = None
        for url in self.settings.subscriptions:
            info = self.settings.subscription_info.get(url) or {}
            used += int(info.get("upload", 0)) + int(info.get("download", 0))
            total += int(info.get("total", 0))
            ex = int(info.get("expire", 0))
            if ex > 0 and (earliest_expire is None or ex < earliest_expire):
                earliest_expire = ex
        if total <= 0 and earliest_expire is None:
            # Show a placeholder so the user knows the feature exists and that
            # their provider just isn't sharing the limits header.
            if self.settings.subscriptions:
                label.configure(text="(подписка не сообщает лимиты)")
            else:
                label.configure(text="")
            return
        parts = []
        if total > 0:
            remaining = max(0, total - used)
            parts.append(f"Осталось: {_format_bytes(remaining)} / {_format_bytes(total)}")
        if earliest_expire:
            days_left = max(0, (earliest_expire - int(time.time())) // 86400)
            parts.append(f"истекает через {days_left} дн.")
        label.configure(text="   ".join(parts))

    @staticmethod
    def _is_fake_profile(profile: VlessProfile) -> bool:
        if profile.server in {"127.0.0.1", "0.0.0.0", "localhost", "::1"}:
            return True
        name_lower = profile.name.lower()
        for marker in ("не поддерживается", "unsupported", "приложение не", "not supported"):
            if marker in name_lower:
                return True
        return False

    def _try_parse_clash_yaml(self, text: str, source_url: str) -> List[VlessProfile]:
        """Clash/Clash Meta YAML subscriptions have 'proxies:' top-level key.
        We extract the list and map each proxy dict to a VlessProfile."""
        if "proxies:" not in text and "proxy-providers:" not in text:
            return []
        try:
            import yaml  # type: ignore
        except ImportError:
            return []
        try:
            data = yaml.safe_load(text)
        except Exception:
            return []
        if not isinstance(data, dict):
            return []
        proxies = data.get("proxies") or []
        if not isinstance(proxies, list):
            return []
        result: List[VlessProfile] = []
        for entry in proxies:
            if not isinstance(entry, dict):
                continue
            profile = self._clash_entry_to_profile(entry, source_url)
            if profile is not None and not self._is_fake_profile(profile):
                result.append(profile)
        return result

    @staticmethod
    def _clash_entry_to_profile(entry: Dict[str, Any], source_url: str) -> Optional[VlessProfile]:
        proto = str(entry.get("type", "")).lower()
        name = str(entry.get("name", "Clash"))
        server = str(entry.get("server", ""))
        port = int(entry.get("port", 443) or 443)
        if not server:
            return None
        common = dict(name=name, server=server, port=port, enabled=True, source_url=source_url, remark=name)
        if proto == "vless":
            ws_opts = entry.get("ws-opts") or {}
            reality_opts = entry.get("reality-opts") or {}
            return VlessProfile(
                **common, uuid=str(entry.get("uuid", "")), protocol="vless",
                security="reality" if reality_opts else ("tls" if entry.get("tls") else "none"),
                flow=str(entry.get("flow", "")), sni=str(entry.get("servername", "") or entry.get("sni", "")),
                fp=str(entry.get("client-fingerprint", "chrome")),
                type=str(entry.get("network", "tcp")),
                path=str(ws_opts.get("path", "")), host=str((ws_opts.get("headers") or {}).get("Host", "")),
                public_key=str(reality_opts.get("public-key", "")),
                short_id=str(reality_opts.get("short-id", "")),
            )
        if proto == "vmess":
            ws_opts = entry.get("ws-opts") or {}
            return VlessProfile(
                **common, uuid=str(entry.get("uuid", "")), protocol="vmess",
                security="tls" if entry.get("tls") else "none",
                sni=str(entry.get("servername", "")),
                type=str(entry.get("network", "tcp")),
                path=str(ws_opts.get("path", "")), host=str((ws_opts.get("headers") or {}).get("Host", "")),
                alter_id=int(entry.get("alterId", 0) or 0),
            )
        if proto == "trojan":
            return VlessProfile(
                **common, uuid="", protocol="trojan", security="tls",
                password=str(entry.get("password", "")),
                sni=str(entry.get("sni", "")),
                insecure=bool(entry.get("skip-cert-verify", False)),
            )
        if proto in ("ss", "shadowsocks"):
            return VlessProfile(
                **common, uuid="", protocol="shadowsocks", security="none",
                password=str(entry.get("password", "")),
                method=str(entry.get("cipher", "")),
            )
        if proto in ("hysteria2", "hy2"):
            return VlessProfile(
                **common, uuid="", protocol="hysteria2", security="tls",
                password=str(entry.get("password", "")),
                sni=str(entry.get("sni", "")),
                insecure=bool(entry.get("skip-cert-verify", False)),
                obfs=str(entry.get("obfs", "")),
                obfs_password=str(entry.get("obfs-password", "")),
            )
        if proto == "tuic":
            return VlessProfile(
                **common, uuid=str(entry.get("uuid", "")), protocol="tuic", security="tls",
                password=str(entry.get("password", "")),
                sni=str(entry.get("sni", "")),
                congestion_control=str(entry.get("congestion-controller", "bbr")),
                udp_relay_mode=str(entry.get("udp-relay-mode", "native")),
                insecure=bool(entry.get("skip-cert-verify", False)),
            )
        return None

    def _decode_subscription_payload(self, payload: str) -> str:
        candidate = payload.strip()
        if "vless://" in candidate:
            return candidate

        try:
            compact = "".join(candidate.split())
            padding = (4 - len(compact) % 4) % 4
            if padding:
                compact += "=" * padding
            decoded = base64.b64decode(compact, validate=False)
            text = decoded.decode("utf-8", errors="ignore").strip()
            if text:
                return text
        except (binascii.Error, UnicodeDecodeError, ValueError):
            pass

        return candidate

    def _append_profile(self, profile: VlessProfile) -> None:
        self.profiles.append(profile)
        save_profiles(self.profiles, self.settings)
        self.refresh_profiles()

    def _append_profiles(self, profiles: List[VlessProfile]) -> None:
        if not profiles:
            return

        existing_keys = {(p.uuid or p.password, p.server, p.port) for p in self.profiles}
        new_profiles = [
            p for p in profiles
            if (p.uuid or p.password, p.server, p.port) not in existing_keys
        ]
        if not new_profiles:
            return

        self.profiles.extend(new_profiles)
        save_profiles(self.profiles, self.settings)
        self.refresh_profiles()

    def delete_profile(self) -> None:
        targets: List[VlessProfile] = []
        if self.selected_indices:
            targets = [self.profiles[i] for i in self.selected_indices]
        elif self.selected_group_url is not None:
            group_url = self.selected_group_url
            if group_url == "_manual":
                targets = [p for p in self.profiles if not p.source_url]
            else:
                targets = [p for p in self.profiles if p.source_url == group_url]

        if not targets:
            self._show_toast("MeDVeD", "Выберите профиль (или группу).", "info")
            return

        if len(targets) == 1:
            confirm = self._show_confirm("Удалить профиль", f"Удалить профиль «{targets[0].name}»?", danger=True)
        elif self.selected_group_url is not None and not self.selected_indices:
            group_label = "категорию «Импортированные вручную»" if self.selected_group_url == "_manual" else f"категорию «{self.selected_group_url}»"
            confirm = self._show_confirm("Удалить категорию", f"Удалить {group_label} ({len(targets)} профилей)?", danger=True)
        else:
            confirm = self._show_confirm("Удалить профили", f"Удалить {len(targets)} выбранных профилей?", danger=True)
        if not confirm:
            return

        keys_to_remove = {id(p) for p in targets}
        self.profiles = [p for p in self.profiles if id(p) not in keys_to_remove]
        save_profiles(self.profiles, self.settings)
        self.selected_uuid = None
        self.selected_group_url = None
        self.selected_indices = []
        self.refresh_profiles()
        self.log(f"Удалено профилей: {len(targets)}")

    # ========== CONNECT / DISCONNECT ==========

    def connect_selected(self) -> None:
        if not _is_admin():
            answer = self._show_confirm(
                "Нужны права администратора",
                "Для создания TUN-интерфейса sing-box требует прав администратора.\n\n"
                "Перезапустить приложение от имени администратора?",
            )
            if answer:
                if _relaunch_as_admin():
                    self._real_quit()
                else:
                    self._show_toast("MeDVeD", "Не удалось перезапустить с правами администратора.", "error")
            return

        active_name = "—"
        if self.selected_indices:
            if len(self.selected_indices) == 1:
                profile = self.profiles[self.selected_indices[0]]
                connect_target: Any = profile
                self.log(f"Подготовка к подключению: {profile.name}")
                active_name = profile.name
            else:
                connect_target = [self.profiles[i] for i in self.selected_indices]
                self.log(f"Подготовка URLTest: {len(connect_target)} выбранных профилей")
                active_name = f"Авто (URLTest, {len(connect_target)} серверов)"
        elif self.selected_group_url is not None:
            group_url = self.selected_group_url
            if group_url == "_manual":
                group_profiles = [p for p in self.profiles if not p.source_url]
            else:
                group_profiles = [p for p in self.profiles if p.source_url == group_url]
            if not group_profiles:
                self._show_toast("MeDVeD", "В группе нет профилей.", "info")
                return
            self.log(f"Подготовка URLTest: {len(group_profiles)} профилей из группы")
            connect_target = group_profiles
            active_name = f"Авто (URLTest, {len(group_profiles)} серверов)"
        elif self.selected_uuid is not None:
            profile = next((p for p in self.profiles if p.uuid == self.selected_uuid), None)
            if profile is None:
                self._show_toast("MeDVeD", "Выберите профиль для подключения.", "info")
                return
            self.log(f"Подготовка к подключению: {profile.name}")
            connect_target = profile
            active_name = profile.name
        else:
            self._show_toast("MeDVeD", "Выберите профиль (или группу/несколько для URLTest).", "info")
            return

        if isinstance(connect_target, list) and len(connect_target) > 1 and not self.settings.urltest_auto_switch:
            def ping_sort_key(profile: VlessProfile) -> float:
                value = self._profile_pings.get(self._profile_ping_key(profile))
                return value if isinstance(value, (int, float)) else float("inf")
            connect_target = sorted(connect_target, key=ping_sort_key)

        try:
            config_data = build_sing_box_config(
                connect_target,
                bypass_ru=self.settings.bypass_ru,
                process_rules=self.settings.process_rules,
                routing_rules=self.settings.routing_rules,
                use_urltest=self.settings.urltest_auto_switch,
            )
        except Exception as error:
            self._show_toast("Ошибка конфига", str(error), "error")
            return

        try:
            controller = config_data["experimental"]["clash_api"]["external_controller"]
            self._api_port = int(controller.rsplit(":", 1)[-1])
        except (KeyError, ValueError, IndexError):
            self._api_port = None

        if isinstance(connect_target, list):
            self._pending_profiles = list(connect_target)
            self._is_urltest = len(connect_target) > 1 and self.settings.urltest_auto_switch
            if len(connect_target) > 1 and not self.settings.urltest_auto_switch:
                active_name = f"Авто (фикс: {connect_target[0].name})"
        else:
            self._pending_profiles = [connect_target]
            self._is_urltest = False
        self._pending_active_name = active_name
        self.log(f"Конфиг готов, API порт: {self._api_port}")
        self._self_heal_attempted = False
        self._start_sing_box(config_data)

    def _sing_box_preflight(self, sing_box_executable: Path, config_path: Path) -> Optional[str]:
        """Run `sing-box check` and return None on success, or a short error
        string describing the validation failure. Catches malformed configs
        before they show up as a confusing 'код 1' crash post-run."""
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            result = subprocess.run(
                [str(sing_box_executable), "check", "-c", str(config_path)],
                capture_output=True, text=True, timeout=10,
                encoding="utf-8", errors="replace",
                creationflags=creationflags,
            )
        except subprocess.TimeoutExpired:
            return "sing-box check завис (>10с)"
        except Exception as error:
            return f"{type(error).__name__}: {error}"
        if result.returncode == 0:
            return None
        msg = (result.stderr or result.stdout or "").strip()
        if not msg:
            msg = f"check вернул код {result.returncode}"
        # sing-box prints the file path noise; trim it.
        return msg.split("\n")[-1][:300]

    def _start_sing_box(self, config_data: dict) -> None:
        self.disconnect()
        self._reset_stats()

        config_dir = Path(tempfile.gettempdir()) / "vless_manager"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "sing-box.json"

        with config_path.open("w", encoding="utf-8") as file:
            json.dump(config_data, file, ensure_ascii=False, indent=2)
        self.log(f"Конфиг записан: {config_path}")

        def worker() -> None:
            try:
                self.after(0, self.log, "Поиск sing-box...")
                sing_box_executable = self._ensure_sing_box_binary()
                self.after(0, self.log, f"sing-box: {sing_box_executable}")

                # Preflight: run `sing-box check` first so a malformed config
                # surfaces an actionable error instead of "VPN упал код 1".
                check_result = self._sing_box_preflight(sing_box_executable, config_path)
                if check_result is not None:
                    self.after(0, self.log, f"❌ Конфиг невалиден: {check_result}")
                    self.after(0, lambda msg=check_result: self._show_toast(
                        "Ошибка конфига sing-box", msg, "error"
                    ))
                    return

                command = [str(sing_box_executable), "run", "-c", str(config_path)]
                creationflags = 0
                if os.name == "nt":
                    creationflags = subprocess.CREATE_NO_WINDOW
                self.after(0, self.log, "Запускаю процесс sing-box...")
                new_process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=creationflags,
                )
                setattr(new_process, "_mvd_user_disconnect", False)
                with self._process_lock:
                    self.process = new_process
                start_time = time.monotonic()
                self.after(0, self._update_active_state, True)
                self.after(0, self.log, f"Процесс запущен, PID={new_process.pid}")
                if self._api_port is not None:
                    self.after(0, self._start_stats_monitor)
                assert new_process.stdout is not None
                for line in new_process.stdout:
                    self.after(0, self.log, line.rstrip())
                new_process.wait()
                self.after(0, self.log, f"sing-box завершён, код={new_process.returncode}")
                crashed = (
                    new_process.returncode != 0
                    and not self._quitting
                    and not getattr(new_process, "_mvd_user_disconnect", False)
                )
                if crashed:
                    self.after(0, self._notify, "MeDVeD", f"VPN упал (код {new_process.returncode})")
                    # Self-heal: if the crash happened after a healthy uptime,
                    # try ONE auto-reconnect to the same config. Don't loop on
                    # rapid crashes (would just thrash on a permanent error).
                    uptime = time.monotonic() - start_time
                    if uptime >= 10 and not self._self_heal_attempted:
                        self._self_heal_attempted = True
                        self.after(0, self.log, f"Сам-восстановление: переподключаюсь через 3 сек (uptime={int(uptime)}с)")
                        self.after(3000, lambda: self._start_sing_box(config_data))
                    elif self.settings.kill_switch:
                        err = _kill_switch_engage()
                        if err:
                            self.after(0, self.log, f"Kill switch: не удалось включить — {err}")
                        else:
                            self.after(0, self.log, "Kill switch активирован — интернет заблокирован до переподключения")
                            self.after(0, self._notify, "MeDVeD", "Kill switch активирован")
                else:
                    # Clean exit (user disconnect or own quit) — reset self-heal counter.
                    self._self_heal_attempted = False
            except FileNotFoundError as error:
                self.after(0, lambda e=error: self._show_toast("MeDVeD", str(e), "error"))
                self.after(0, self.log, f"FileNotFoundError: {error}")
            except Exception as error:
                self.after(0, lambda e=error: self._show_toast("MeDVeD", f"{type(e).__name__}: {e}", "error"))
                self.after(0, self.log, f"Exception {type(error).__name__}: {error}")
            finally:
                with self._process_lock:
                    if self.process is not None and self.process.poll() is not None:
                        self.process = None
                # Don't call _stop_stats_monitor here — disconnect() already did
                # it, and calling it here can race with a newly started monitor
                # (worker1 finally fires after worker2 has spawned its monitor).
                # The monitor self-exits when it sees process=None below.
                self.after(0, self._update_active_state, False)

        threading.Thread(target=worker, daemon=True).start()

    def disconnect(self) -> None:
        self._stop_stats_monitor()
        with self._process_lock:
            proc = self.process
            self.process = None

        if proc and proc.poll() is None:
            setattr(proc, "_mvd_user_disconnect", True)
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
            except Exception:
                pass
            self.log("Соединение остановлено")
        _kill_switch_release()
        self._update_active_state(False)

    def _on_close(self) -> None:
        if self.settings.minimize_to_tray and self._tray_icon is not None and not self._quitting:
            self.withdraw()
            return
        self._real_quit()

    def _real_quit(self) -> None:
        self._quitting = True
        try:
            self.disconnect()
            _kill_switch_release()
        finally:
            if self._tray_icon is not None:
                try:
                    self._tray_icon.stop()
                except Exception:
                    pass
                self._tray_icon = None
            self.destroy()

    def _update_active_state(self, active: bool) -> None:
        self.active_var.set(active)
        self.status_var.set(self._t("connected") if active else "Готово")
        if active:
            pending = getattr(self, "_pending_active_name", "")
            if pending:
                self.active_server_var.set(pending)
        else:
            self._reset_stats()
            self.active_server_var.set("—")
        self._refresh_tray_icon(active)
        if getattr(self, "main_button", None) is not None:
            self.main_button.set_state(active, text=(self._t("connected") if active else self._t("connect")))

    def _reset_stats(self) -> None:
        self._prev_rx = 0.0
        self._prev_tx = 0.0
        self._prev_time = 0.0
        self._total_rx = 0.0
        self._total_tx = 0.0
        self._last_ping_ms = 0.0
        self.dl_speed_var.set("—")
        self.ul_speed_var.set("—")
        self.total_dl_var.set("—")
        self.total_ul_var.set("—")
        self.ping_var.set("—")
        self._dl_history.clear()
        self._ul_history.clear()
        if hasattr(self, "sparkline"):
            self.sparkline.delete("all")

    def _redraw_sparkline(self) -> None:
        canvas = getattr(self, "sparkline", None)
        if canvas is None:
            return
        canvas.delete("all")
        width = max(1, canvas.winfo_width())
        height = max(1, canvas.winfo_height())
        dl = list(self._dl_history)
        ul = list(self._ul_history)
        if not dl and not ul:
            return
        peak = max((max(dl) if dl else 0.0), (max(ul) if ul else 0.0), 1.0)
        capacity = self._dl_history.maxlen or len(dl) or 1
        for series, color in ((dl, "#4caf50"), (ul, "#ef5350")):
            if len(series) < 2:
                continue
            points: List[float] = []
            for i, value in enumerate(series):
                x = (i / (capacity - 1)) * width if capacity > 1 else width / 2
                y = height - (value / peak) * (height - 2) - 1
                points.extend([x, y])
            canvas.create_line(*points, fill=color, width=2, smooth=False)

    # ========== STATS MONITOR ==========

    def _start_stats_monitor(self) -> int:
        self._monitor_generation += 1
        generation = self._monitor_generation
        self._monitor_thread = threading.Thread(
            target=self._stats_monitor_loop, args=(generation,), daemon=True
        )
        self._monitor_thread.start()
        return generation

    def _stop_stats_monitor(self, generation: Optional[int] = None) -> None:
        # If a generation is given, only stop if the active monitor still matches —
        # this prevents a late-finishing worker from killing a freshly started one.
        if generation is not None and generation != self._monitor_generation:
            return
        self._monitor_generation += 1
        self._monitor_thread = None

    def _api_url(self, path: str) -> str:
        return f"http://127.0.0.1:{self._api_port}{path}"

    def _api_request(self, path: str) -> Optional[Any]:
        if self._api_port is None:
            return None
        url = self._api_url(path)
        req = urllib.request.Request(url, headers={"Authorization": "Bearer medved"})
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError, OSError):
            return None

    def _stats_monitor_loop(self, generation: int) -> None:
        ping_interval = 0
        last_now_tag: Optional[str] = None

        while self._monitor_generation == generation:
            with self._process_lock:
                proc = self.process
            if proc is None or proc.poll() is not None:
                return
            if self._is_urltest:
                info = self._api_request("/proxies/proxy")
                if isinstance(info, dict):
                    now_tag = info.get("now")
                    if isinstance(now_tag, str) and now_tag != last_now_tag:
                        is_first = last_now_tag is None
                        last_now_tag = now_tag
                        try:
                            idx = int(now_tag.split("-", 1)[1])
                        except (IndexError, ValueError):
                            idx = -1
                        if 0 <= idx < len(self._pending_profiles):
                            name = self._pending_profiles[idx].name

                            def update_name(n=name, notify=not is_first) -> None:
                                self.active_server_var.set(n)
                                if notify:
                                    self._show_snackbar(f"Переключён на {n}", "info", duration_ms=2500)

                            self.after(0, update_name)
            snapshot = self._api_request("/connections")
            if snapshot is not None:
                try:
                    download_total = float(snapshot.get("downloadTotal", 0))
                    upload_total = float(snapshot.get("uploadTotal", 0))
                    current_time = time.time()

                    if self._prev_time > 0:
                        elapsed = current_time - self._prev_time
                        if elapsed > 0:
                            dl_speed = max(0.0, (download_total - self._prev_rx) / elapsed)
                            ul_speed = max(0.0, (upload_total - self._prev_tx) / elapsed)

                            def update_speed(dl=dl_speed, ul=ul_speed, total_dl=download_total, total_ul=upload_total):
                                self.dl_speed_var.set(_format_speed(dl))
                                self.ul_speed_var.set(_format_speed(ul))
                                self.total_dl_var.set(_format_bytes(total_dl))
                                self.total_ul_var.set(_format_bytes(total_ul))
                                self._dl_history.append(dl)
                                self._ul_history.append(ul)
                                self._redraw_sparkline()

                            self.after(0, update_speed)

                    self._prev_rx = download_total
                    self._prev_tx = upload_total
                    self._prev_time = current_time
                    self._total_rx = download_total
                    self._total_tx = upload_total
                except (TypeError, ValueError):
                    pass

            ping_interval += 1
            if ping_interval >= 5:
                ping_interval = 0
                delay = self._api_request(
                    "/proxies/proxy/delay?timeout=2000&url=http%3A%2F%2Fwww.gstatic.com%2Fgenerate_204"
                )
                if isinstance(delay, dict) and "delay" in delay:
                    try:
                        elapsed_ms = float(delay["delay"])
                        self._last_ping_ms = elapsed_ms
                        self.after(0, lambda ms=elapsed_ms: self.ping_var.set(f"{ms:.0f} мс"))
                    except (TypeError, ValueError):
                        self.after(0, lambda: self.ping_var.set("—"))
                else:
                    self.after(0, lambda: self.ping_var.set("timeout"))

            time.sleep(1)

    def _apply_settings_now(self, *_args: Any) -> None:
        """Apply every settings UI value to self.settings and persist immediately.
        Called automatically on every toggle/dropdown/field change — there is no
        manual Save button. The *_args tail lets it be used as a trace_add callback."""
        if not getattr(self, "_settings_ui_ready", False):
            return
        path = self.settings_path_var.get().strip()

        resolved = self._find_sing_box_path(path)
        if resolved is not None:
            self.settings.sing_box_path = str(resolved)
            if str(resolved) != self.settings_path_var.get():
                # Avoid trace recursion: only update var if path actually changed.
                self.settings_path_var.set(str(resolved))

        prev_auto_connect = self.settings.auto_connect_enabled
        self.settings.auto_connect_enabled = bool(self.auto_connect_var.get())
        if self.settings.auto_connect_enabled and not prev_auto_connect:
            selected = self._selected_single_profile()
            if selected is not None:
                self.settings.auto_connect_key = self._profile_ping_key(selected)
            elif not self.settings.auto_connect_key:
                self.log("⚠ Автоподключение включено, но профиль не выбран — выберите профиль и снова включите")

        self.settings.notifications_enabled = bool(self.notifications_var.get())
        self.settings.bypass_ru = bool(self.bypass_ru_var.get())
        self.settings.urltest_auto_switch = bool(self.urltest_auto_switch_var.get())
        new_appearance = str(self.appearance_var.get())
        if new_appearance in ("dark", "light", "system") and new_appearance != self.settings.appearance_mode:
            self.settings.appearance_mode = new_appearance
            try:
                ctk.set_appearance_mode(new_appearance)
            except Exception:
                pass
            self._apply_ttk_style()
            self._refresh_main_button_background()
        new_language = str(self.language_var.get())
        if new_language in ("ru", "en") and new_language != self.settings.language:
            self.settings.language = new_language
            self._show_snackbar(_t_for(new_language, "lang_change_restart"), "info", duration_ms=5000)
        prev_autostart = self.settings.auto_start_with_windows
        prev_min = self.settings.start_minimized
        self.settings.auto_start_with_windows = bool(self.autostart_var.get())
        self.settings.start_minimized = bool(self.start_minimized_var.get())
        if (self.settings.auto_start_with_windows != prev_autostart) or (self.settings.start_minimized != prev_min):
            autostart_error = _set_autostart(
                self.settings.auto_start_with_windows, self.settings.start_minimized,
            )
            if autostart_error:
                self._show_snackbar(f"Автозапуск: {autostart_error}", "warn", duration_ms=4000)
        was_kill_switch = self.settings.kill_switch
        self.settings.kill_switch = bool(self.kill_switch_var.get())
        if was_kill_switch and not self.settings.kill_switch:
            _kill_switch_release()
        try:
            self.settings.subscription_refresh_hours = max(0, int(self.subscription_refresh_var.get() or 0))
        except ValueError:
            pass

        try:
            save_settings(self.settings)
        except Exception as error:
            self.log(f"⚠ Не удалось сохранить настройки: {error}")
            return
        self._schedule_subscription_refresh()
        self._refresh_server_menu()

    def _find_sing_box_path(self, hint: str = "") -> Optional[Path]:
        candidates: list[Path] = []
        if hint:
            h = Path(hint)
            candidates.append(h)
            if not h.suffix:
                candidates.append(h.with_suffix(".exe"))
        bundle_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "sing-box.exe")
        candidates.extend([
            bundle_dir / "sing-box.exe",
            bundle_dir / "sing-box",
            get_user_data_root() / "bin" / "sing-box.exe",
        ])
        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve()
        found = shutil.which(hint) if hint else None
        if not found:
            found = shutil.which("sing-box")
        return Path(found).resolve() if found else None

    def _autodetect_sing_box_path(self) -> None:
        current = self.settings.sing_box_path.strip()
        if current and Path(current).is_file():
            self.settings_path_var.set(current)
            return
        resolved = self._find_sing_box_path(current)
        if resolved is not None:
            self.settings.sing_box_path = str(resolved)
            self.settings_path_var.set(str(resolved))
            save_settings(self.settings)

    # ========== MAIN BUTTON / PROFILES WINDOW / LOG WINDOW ==========

    _AUTO_KEY = "__auto__"

    def _t(self, key: str, **kwargs: Any) -> str:
        return _t_for(self.settings.language, key, **kwargs)

    def _auto_label(self) -> str:
        return self._t("auto_label_switch") if self.settings.urltest_auto_switch else self._t("auto_label_fixed")

    def _format_choice(self, value: str) -> str:
        return self._auto_label() if value == self._AUTO_KEY else value

    def _refresh_server_menu(self) -> None:
        button = getattr(self, "server_button", None)
        if button is None:
            return
        valid_keys = [self._AUTO_KEY] + [p.name for p in self.profiles]
        if self.server_choice_var.get() not in valid_keys:
            self.server_choice_var.set(self._AUTO_KEY)
        button.configure(text=f"{self._format_choice(self.server_choice_var.get())}  ▼")

    def _toggle_server_menu(self) -> None:
        if self._server_menu_visible:
            self._hide_server_menu()
            return
        self._open_server_menu()

    def _open_server_menu(self) -> None:
        self._hide_burger()
        items = [(self._AUTO_KEY, self._auto_label())] + [(p.name, p.name) for p in self.profiles]

        button = self.server_button
        bx = button.winfo_rootx() - self.winfo_rootx()
        by = button.winfo_rooty() - self.winfo_rooty() + button.winfo_height() + 4
        bw = button.winfo_width()

        dropdown = ctk.CTkFrame(
            self, fg_color="#2b2b2b", corner_radius=8, border_width=1,
            border_color="#3a3a3a", width=bw,
        )
        dropdown.place(x=bx, y=by)
        dropdown.lift()

        def pick(key: str) -> None:
            prev_key = self.server_choice_var.get()
            self.server_choice_var.set(key)
            self.server_button.configure(text=f"{self._format_choice(key)}  ▼")
            self._hide_server_menu()
            if self.active_var.get() and key != prev_key:
                self._connect_with_current_choice()

        # Limit visible items, allow scroll only if many
        max_visible = 7
        if len(items) <= max_visible:
            container = dropdown
        else:
            container = ctk.CTkScrollableFrame(
                dropdown, fg_color="transparent", width=bw - 20, height=36 * max_visible,
            )
            container.pack(fill=BOTH, expand=True, padx=2, pady=2)

        for key, label in items:
            ctk.CTkButton(
                container, text=label, command=lambda k=key: pick(k),
                fg_color="transparent", hover_color="#1f6aa5", text_color="#e0e0e0",
                anchor="w", height=32, corner_radius=4,
            ).pack(fill=X, padx=2, pady=1)

        self._server_dropdown = dropdown
        self._server_menu_visible = True

    def _hide_server_menu(self) -> None:
        if self._server_dropdown is not None:
            try:
                self._server_dropdown.place_forget()
                self._server_dropdown.destroy()
            except Exception:
                pass
            self._server_dropdown = None
        self._server_menu_visible = False
        try:
            self.update_idletasks()
        except Exception:
            pass

    def _toggle_connection(self) -> None:
        if self.active_var.get():
            self.disconnect()
            return
        self._connect_with_current_choice()

    def _connect_with_current_choice(self) -> None:
        if not self.profiles:
            self._show_toast(
                "Нет профилей",
                "Откройте «Профили и подписки» в меню и добавьте сервер или подписку.",
                "info",
            )
            return
        choice = self.server_choice_var.get()
        if choice == self._AUTO_KEY:
            if len(self.profiles) == 1:
                self.selected_indices = [0]
            else:
                self.selected_indices = list(range(len(self.profiles)))
        else:
            match_idx = next((i for i, p in enumerate(self.profiles) if p.name == choice), None)
            if match_idx is None:
                self._show_toast("MeDVeD", f"Сервер «{choice}» не найден среди профилей.", "warn")
                return
            self.selected_indices = [match_idx]
        self.selected_uuid = None
        self.selected_group_url = None
        self.connect_selected()

    def _build_profiles_view(self) -> None:
        view = ctk.CTkFrame(self.view_container, fg_color="transparent")
        self._view_header(view, "Профили и подписки", back=True)

        wrapper = ctk.CTkFrame(view, fg_color="transparent")
        wrapper.pack(fill=BOTH, expand=True, padx=16, pady=(0, 16))

        left = ctk.CTkFrame(wrapper, fg_color="transparent")
        left.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 10))

        right = ctk.CTkFrame(wrapper, width=300, fg_color="transparent")
        right.pack(side=RIGHT, fill=Y)
        right.pack_propagate(False)

        list_section = self._section(left, "Профили")
        list_section.pack(fill=BOTH, expand=True)

        tree_holder = ctk.CTkFrame(list_section, fg_color="transparent")
        tree_holder.pack(fill=BOTH, expand=True, padx=10, pady=(2, 8))
        self.profile_list = ttk.Treeview(
            tree_holder, columns=("server", "type", "ping"), show="tree headings",
            selectmode="extended", style="Dark.Treeview",
        )
        self.profile_list.heading("#0", text="Имя")
        self.profile_list.heading("server", text="Сервер")
        self.profile_list.heading("type", text="Транспорт")
        self.profile_list.heading("ping", text="Пинг")
        self.profile_list.column("#0", width=240, anchor="w")
        self.profile_list.column("server", width=180, anchor="w")
        self.profile_list.column("type", width=100, anchor="center")
        self.profile_list.column("ping", width=80, anchor="center")
        self.profile_list.pack(fill=BOTH, expand=True)
        self.profile_list.bind("<<TreeviewSelect>>", self.on_profile_select)
        self.refresh_profiles()

        actions = ctk.CTkFrame(left, fg_color="transparent")
        actions.pack(fill=X, pady=(8, 0))
        for text, cmd in [
            ("Удалить", self.delete_profile),
            ("Скопировать ссылку", self._copy_selected_link),
            ("Проверить пинги", self.test_all_pings),
            ("Speedtest", self.test_all_speeds),
            ("Экспорт", self.export_profiles),
            ("Импорт", self.import_profiles_from_file),
        ]:
            ctk.CTkButton(actions, text=text, command=cmd, width=125, height=30).pack(side=LEFT, padx=(0, 4))

        details = self._section(right, "Импорт ссылки")
        details.pack(fill=X)
        ctk.CTkLabel(details, text="vless / vmess / trojan / ss / hysteria2", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=12, pady=(0, 2))
        self.link_entry = ctk.CTkEntry(details, textvariable=self.link_var)
        self.link_entry.pack(fill=X, padx=12, pady=4)
        _bind_clipboard_shortcuts(self.link_entry)
        ctk.CTkButton(details, text="Добавить профиль", command=self.import_profile, height=32).pack(fill=X, padx=12, pady=(8, 10))

        sub_box = self._section(right, "Подписка")
        sub_box.pack(fill=X, pady=(10, 0))
        ctk.CTkLabel(sub_box, text="URL подписки", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=12, pady=(0, 2))
        self.subscription_entry = ctk.CTkEntry(sub_box, textvariable=self.subscription_var)
        self.subscription_entry.pack(fill=X, padx=12, pady=4)
        _bind_clipboard_shortcuts(self.subscription_entry)
        ctk.CTkButton(sub_box, text="Импортировать подписку", command=self.import_subscription, height=30).pack(fill=X, padx=12, pady=(6, 4))
        ctk.CTkButton(sub_box, text="Обновить все подписки", command=self.refresh_subscriptions, height=30).pack(fill=X, padx=12, pady=(0, 10))

        self._views["profiles"] = view

    def _build_log_view(self) -> None:
        view = ctk.CTkFrame(self.view_container, fg_color="transparent")
        self._view_header(view, "Журнал", back=True)

        wrapper = ctk.CTkFrame(view, fg_color="transparent")
        wrapper.pack(fill=BOTH, expand=True, padx=16, pady=(0, 16))

        widget = ScrolledText(
            wrapper, wrap="word",
            bg="#1a1a1a", fg="#e0e0e0", insertbackground="#ffffff",
            borderwidth=0, relief="flat", font=("Consolas", 9),
        )
        widget.pack(fill=BOTH, expand=True)
        widget.configure(state="normal")
        widget.insert(END, "\n".join(self._log_buffer))
        if self._log_buffer:
            widget.insert(END, "\n")
        widget.see(END)
        widget.configure(state="disabled")
        self.log_widget = widget

        self.log_menu = Menu(widget, tearoff=0, bg="#2b2b2b", fg="#e0e0e0", activebackground="#1f6aa5", activeforeground="#ffffff")
        self.log_menu.add_command(label="Скопировать выделенное", command=self._log_copy_selection)
        self.log_menu.add_command(label="Скопировать весь лог", command=self._log_copy_all)
        self.log_menu.add_separator()
        self.log_menu.add_command(label="Очистить лог", command=self._log_clear)
        widget.bind("<Button-3>", self._log_show_menu)
        widget.bind("<Control-c>", self._log_copy_selection_event)
        widget.bind("<Control-a>", self._log_select_all_event)

        self._views["log"] = view

    # ========== BURGER MENU / SETTINGS WINDOW ==========

    _BURGER_ITEMS = [
        ("📋  Профили и подписки", "profiles_view"),
        ("📊  Журнал", "log_view"),
        ("---", None),
        ("⚙  Настройки", "settings_view"),
        ("---", None),
        ("✕  Выход", "quit"),
    ]

    def _show_burger_menu(self) -> None:
        if self._burger_visible:
            self._hide_burger()
            return
        self._open_burger()

    def _open_burger(self) -> None:
        dropdown = ctk.CTkFrame(self, fg_color="#2b2b2b", corner_radius=8, border_width=1, border_color="#3a3a3a")
        btn = getattr(self, "burger_button", None)
        if btn is not None:
            bx = btn.winfo_rootx() - self.winfo_rootx()
            by = btn.winfo_rooty() - self.winfo_rooty() + btn.winfo_height() + 4
        else:
            bx, by = 16, 64
        dropdown.place(x=bx, y=by)
        dropdown.lift()

        action_map = {
            "profiles_view": lambda: self._show_view("profiles"),
            "log_view":      lambda: self._show_view("log"),
            "settings_view": lambda: self._show_view("settings"),
            "quit":          self._real_quit,
            "update":        self._start_update_flow,
        }

        items = list(self._BURGER_ITEMS)
        if self._update_available:
            items = [
                (f"🔄  Обновить до {self._update_version}", "update"),
                ("---", None),
            ] + items

        for label, action in items:
            if label == "---":
                ctk.CTkFrame(dropdown, height=1, fg_color="#3a3a3a").pack(fill=X, padx=8, pady=4)
                continue
            cb = action_map.get(action)
            def make_handler(callback):
                def handler() -> None:
                    self._hide_burger()
                    if callback is not None:
                        try:
                            callback()
                        except Exception:
                            pass
                return handler
            text_color = "#ff7a7a" if action == "update" else "#e0e0e0"
            hover_color = "#a83232" if action == "update" else "#1f6aa5"
            ctk.CTkButton(
                dropdown, text=label, command=make_handler(cb),
                fg_color="transparent", hover_color=hover_color, text_color=text_color,
                anchor="w", height=32, corner_radius=4,
            ).pack(fill=X, padx=4, pady=1)

        self._burger_dropdown = dropdown
        self._burger_visible = True

    def _hide_burger(self) -> None:
        if self._burger_dropdown is not None:
            try:
                self._burger_dropdown.place_forget()
                self._burger_dropdown.destroy()
            except Exception:
                pass
            self._burger_dropdown = None
        self._burger_visible = False
        try:
            self.update_idletasks()
        except Exception:
            pass

    def _global_click_for_menus(self, event) -> None:
        """Close any open dropdown when user clicks outside it. Click on the
        owning button is handled by the button itself (which toggles)."""
        x_root, y_root = event.x_root, event.y_root

        def click_inside(widget) -> bool:
            try:
                x = widget.winfo_rootx()
                y = widget.winfo_rooty()
                w = widget.winfo_width()
                h = widget.winfo_height()
                return (x <= x_root <= x + w) and (y <= y_root <= y + h)
            except Exception:
                return False

        if self._burger_visible and self._burger_dropdown is not None:
            btn = getattr(self, "burger_button", None)
            on_burger_btn = click_inside(btn) if btn is not None else False
            if not click_inside(self._burger_dropdown) and not on_burger_btn:
                self._hide_burger()

        if self._server_menu_visible and self._server_dropdown is not None:
            if not click_inside(self._server_dropdown) and not click_inside(self.server_button):
                self._hide_server_menu()

    def _build_settings_view(self) -> None:
        view = ctk.CTkFrame(self.view_container, fg_color="transparent")
        self._view_header(view, "Настройки", back=True)

        # Bottom button bar stays outside the scrollable area so it never disappears.
        bottom = ctk.CTkFrame(view, fg_color="transparent")
        bottom.pack(fill=X, side="bottom", padx=16, pady=(0, 16))

        wrapper = ctk.CTkScrollableFrame(view, fg_color="transparent")
        wrapper.pack(fill=BOTH, expand=True, padx=16, pady=(0, 8))

        ctk.CTkLabel(wrapper, text="Путь к sing-box", font=ctk.CTkFont(size=11)).pack(anchor="w")
        self.singbox_entry = ctk.CTkEntry(wrapper, textvariable=self.settings_path_var)
        self.singbox_entry.pack(fill=X, pady=(2, 10))
        _bind_clipboard_shortcuts(self.singbox_entry)

        for text, var in [
            ("Автоподключение к выбранному профилю при запуске", self.auto_connect_var),
            ("Запускать MeDVeD автоматически при старте Windows", self.autostart_var),
            ("Стартовать свёрнутым в трей", self.start_minimized_var),
            ("Системные уведомления (ошибки VPN, обновление подписок)", self.notifications_var),
            ("Российские сайты в обход VPN (geosite-ru + geoip-ru)", self.bypass_ru_var),
            ("Kill switch (блокировать интернет при падении VPN)", self.kill_switch_var),
            ("Авто-режим: переподключаться к быстрейшему серверу каждые 5 мин", self.urltest_auto_switch_var),
        ]:
            ctk.CTkCheckBox(wrapper, text=text, variable=var).pack(anchor="w", pady=4)

        # Theme + language row
        appearance_row = ctk.CTkFrame(wrapper, fg_color="transparent")
        appearance_row.pack(fill=X, pady=(10, 0))
        ctk.CTkLabel(appearance_row, text="Тема:").pack(side=LEFT)
        ctk.CTkOptionMenu(
            appearance_row, variable=self.appearance_var,
            values=["dark", "light", "system"], width=110,
        ).pack(side=LEFT, padx=(6, 16))
        ctk.CTkLabel(appearance_row, text="Язык:").pack(side=LEFT)
        ctk.CTkOptionMenu(
            appearance_row, variable=self.language_var,
            values=["ru", "en"], width=70,
        ).pack(side=LEFT, padx=6)

        refresh_row = ctk.CTkFrame(wrapper, fg_color="transparent")
        refresh_row.pack(fill=X, pady=(10, 0))
        ctk.CTkLabel(refresh_row, text="Авто-обновление подписок каждые").pack(side=LEFT)
        ttk.Spinbox(
            refresh_row, from_=0, to=168, width=4,
            textvariable=self.subscription_refresh_var, style="Dark.TSpinbox",
        ).pack(side=LEFT, padx=6)
        ctk.CTkLabel(refresh_row, text="ч (0 = выключено)").pack(side=LEFT)

        ctk.CTkLabel(
            wrapper, text="Правила по процессам (роутинг по имени exe)",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", pady=(14, 4))
        ctk.CTkLabel(
            wrapper, text="Какой процесс пойдёт напрямую (direct) или через VPN (proxy)",
            font=ctk.CTkFont(size=10), text_color="#aaaaaa",
        ).pack(anchor="w")

        proc_holder = ctk.CTkFrame(wrapper, fg_color="transparent")
        proc_holder.pack(fill=BOTH, expand=True, pady=(6, 0))
        proc_tree = ttk.Treeview(
            proc_holder, columns=("name", "outbound"), show="headings",
            selectmode="browse", style="Dark.Treeview", height=6,
        )
        proc_tree.heading("name", text="Процесс (exe)")
        proc_tree.heading("outbound", text="Направление")
        proc_tree.column("name", width=320, anchor="w")
        proc_tree.column("outbound", width=120, anchor="center")
        proc_tree.pack(side=LEFT, fill=BOTH, expand=True)

        def reload_proc_tree() -> None:
            for item in proc_tree.get_children():
                proc_tree.delete(item)
            for index, rule in enumerate(self.settings.process_rules):
                proc_tree.insert("", END, iid=str(index), values=(rule.get("process_name", ""), rule.get("outbound", "direct")))

        reload_proc_tree()

        proc_buttons = ctk.CTkFrame(proc_holder, fg_color="transparent")
        proc_buttons.pack(side=RIGHT, fill=Y, padx=(8, 0))

        def add_rule() -> None:
            def done() -> None:
                reload_proc_tree()
                self._apply_settings_now()
            self._prompt_process_rule(on_done=done)

        def remove_rule() -> None:
            selection = proc_tree.selection()
            if not selection:
                return
            try:
                index = int(selection[0])
            except ValueError:
                return
            if 0 <= index < len(self.settings.process_rules):
                self.settings.process_rules.pop(index)
                reload_proc_tree()
                self._apply_settings_now()

        ctk.CTkButton(proc_buttons, text="+ Добавить", command=add_rule, width=110, height=30).pack(pady=(0, 6))
        ctk.CTkButton(proc_buttons, text="− Удалить", command=remove_rule, width=110, height=30, fg_color="#7a3a3a").pack()

        # ---------- Routing rules (domain / IP / port → direct/proxy/block) ----------
        ctk.CTkLabel(
            wrapper, text="Правила маршрутизации (домены, IP, порты)",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", pady=(20, 4))
        ctk.CTkLabel(
            wrapper, text="Куда отправлять трафик по домену, IP-подсети или порту",
            font=ctk.CTkFont(size=10), text_color="#aaaaaa",
        ).pack(anchor="w")

        route_holder = ctk.CTkFrame(wrapper, fg_color="transparent")
        route_holder.pack(fill=BOTH, expand=True, pady=(6, 0))
        route_tree = ttk.Treeview(
            route_holder, columns=("kind", "value", "action"), show="headings",
            selectmode="browse", style="Dark.Treeview", height=6,
        )
        route_tree.heading("kind", text="Тип")
        route_tree.heading("value", text="Значение")
        route_tree.heading("action", text="Действие")
        route_tree.column("kind", width=140, anchor="center")
        route_tree.column("value", width=260, anchor="w")
        route_tree.column("action", width=100, anchor="center")
        route_tree.pack(side=LEFT, fill=BOTH, expand=True)

        def reload_route_tree() -> None:
            for item in route_tree.get_children():
                route_tree.delete(item)
            for index, rule in enumerate(self.settings.routing_rules):
                route_tree.insert("", END, iid=str(index), values=(
                    rule.get("kind", ""), rule.get("value", ""), rule.get("action", ""),
                ))

        reload_route_tree()

        route_buttons = ctk.CTkFrame(route_holder, fg_color="transparent")
        route_buttons.pack(side=RIGHT, fill=Y, padx=(8, 0))

        def add_route_rule() -> None:
            def done() -> None:
                reload_route_tree()
                self._apply_settings_now()
            self._prompt_routing_rule(on_done=done)

        def remove_route_rule() -> None:
            selection = route_tree.selection()
            if not selection:
                return
            try:
                index = int(selection[0])
            except ValueError:
                return
            if 0 <= index < len(self.settings.routing_rules):
                self.settings.routing_rules.pop(index)
                reload_route_tree()
                self._apply_settings_now()

        ctk.CTkButton(route_buttons, text="+ Добавить", command=add_route_rule, width=110, height=30).pack(pady=(0, 6))
        ctk.CTkButton(route_buttons, text="− Удалить", command=remove_route_rule, width=110, height=30, fg_color="#7a3a3a").pack()

        # ---------- Bottom button bar (Check updates only — settings auto-save) ----------
        ctk.CTkButton(
            bottom, text=f"Проверить обновления  (v{__version__})",
            command=self._manual_check_for_update, height=34,
            fg_color="#3a3a3a", hover_color="#4a4a4a",
        ).pack(side=LEFT)

        # ---------- Wire up auto-save on every change ----------
        # Each toggle/dropdown/spinbox change calls _apply_settings_now immediately.
        # The Entry field for sing-box path uses FocusOut so we don't write on
        # every keystroke. process_rules / routing_rules are saved by the
        # reload_*_tree closures (they call _apply_settings_now after add/remove).
        for var in (
            self.auto_connect_var,
            self.autostart_var,
            self.start_minimized_var,
            self.notifications_var,
            self.bypass_ru_var,
            self.kill_switch_var,
            self.urltest_auto_switch_var,
            self.appearance_var,
            self.language_var,
            self.subscription_refresh_var,
        ):
            var.trace_add("write", self._apply_settings_now)
        self.singbox_entry.bind("<FocusOut>", lambda _e: self._apply_settings_now())

        self._proc_rules_reload = reload_proc_tree
        self._route_rules_reload = reload_route_tree
        self._settings_ui_ready = True

        self._views["settings"] = view

    _ROUTING_KIND_LABELS = [
        ("domain_suffix", "Поддомен (example.com)"),
        ("domain", "Точный домен"),
        ("domain_keyword", "Слово в домене"),
        ("ip_cidr", "IP / подсеть (1.2.3.0/24)"),
        ("port", "Порт"),
    ]

    def _prompt_routing_rule(self, on_done) -> None:
        kind_var = StringVar(value="domain_suffix")
        value_var = StringVar()
        action_var = StringVar(value="proxy")

        def build_body(card: "ctk.CTkFrame") -> None:
            ctk.CTkLabel(card, text="Тип правила", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=20, pady=(0, 4))
            kind_to_label = {k: label for k, label in self._ROUTING_KIND_LABELS}
            label_to_kind = {label: k for k, label in self._ROUTING_KIND_LABELS}
            display_var = StringVar(value=kind_to_label[kind_var.get()])

            def on_change(value: str) -> None:
                kind_var.set(label_to_kind.get(value, "domain_suffix"))

            ctk.CTkOptionMenu(
                card, variable=display_var, values=[lbl for _, lbl in self._ROUTING_KIND_LABELS],
                command=on_change, width=300,
            ).pack(anchor="w", padx=20)

            ctk.CTkLabel(card, text="Значение", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=20, pady=(12, 4))
            entry = ctk.CTkEntry(card, textvariable=value_var)
            entry.pack(fill=X, padx=20)
            _bind_clipboard_shortcuts(entry)
            entry.focus_set()

            ctk.CTkLabel(card, text="Действие", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=20, pady=(12, 4))
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(anchor="w", padx=20)
            ctk.CTkRadioButton(row, text="через VPN", variable=action_var, value="proxy").pack(side=LEFT, padx=(0, 12))
            ctk.CTkRadioButton(row, text="напрямую", variable=action_var, value="direct").pack(side=LEFT, padx=(0, 12))
            ctk.CTkRadioButton(row, text="блокировать", variable=action_var, value="block").pack(side=LEFT)

        def on_ok() -> None:
            value = value_var.get().strip()
            if not value:
                return
            self.settings.routing_rules.append({
                "kind": kind_var.get(),
                "value": value,
                "action": action_var.get(),
            })
            on_done()

        self._show_overlay(
            title="Добавить правило маршрутизации",
            build_body=build_body,
            buttons=[("Добавить", on_ok, "primary"), ("Отмена", None, "secondary")],
        )

    def _prompt_process_rule(self, on_done) -> None:
        name_var = StringVar()
        direction_var = StringVar(value="proxy")

        def build_body(card: "ctk.CTkFrame") -> None:
            ctk.CTkLabel(card, text="Имя процесса (например chrome.exe)", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=20, pady=(0, 4))
            entry = ctk.CTkEntry(card, textvariable=name_var)
            entry.pack(fill=X, padx=20)
            _bind_clipboard_shortcuts(entry)
            entry.focus_set()

            ctk.CTkLabel(card, text="Направление", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=20, pady=(12, 4))
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(anchor="w", padx=20)
            ctk.CTkRadioButton(row, text="через VPN", variable=direction_var, value="proxy").pack(side=LEFT, padx=(0, 12))
            ctk.CTkRadioButton(row, text="напрямую", variable=direction_var, value="direct").pack(side=LEFT)

        def on_ok() -> None:
            name = name_var.get().strip()
            if not name:
                return
            self.settings.process_rules.append({"process_name": name, "outbound": direction_var.get()})
            on_done()

        self._show_overlay(
            title="Добавить правило",
            build_body=build_body,
            buttons=[("Добавить", on_ok, "primary"), ("Отмена", None, "secondary")],
        )

    # ========== IN-APP OVERLAY (toast / confirm / custom) ==========

    _OVERLAY_COLORS = {
        "info":  "#1f6aa5",
        "warn":  "#b07a2d",
        "error": "#a83232",
        "ok":    "#2e7d32",
    }

    def _dismiss_overlay(self) -> None:
        overlay = getattr(self, "_overlay", None)
        card = getattr(self, "_overlay_card", None)
        for widget in (card, overlay):
            if widget is not None:
                try:
                    widget.destroy()
                except Exception:
                    pass
        self._overlay = None
        self._overlay_card = None
        self._overlay_result_var = None

    def _show_overlay(self, title: str, build_body, buttons, accent: str = "info") -> None:
        """Generic in-app overlay. `buttons` is a list of (label, callback_or_None, kind)
        where kind is 'primary' | 'secondary' | 'danger'. Callbacks are called *before*
        the overlay closes; pass None for just-close buttons.

        No darkening backdrop on purpose — Tk widgets can't be alpha-blended, and
        an opaque dimmer would hide the rest of the UI. Instead the card floats
        with a subtle border, leaving the underlying content fully visible."""
        self._dismiss_overlay()
        self._overlay = None

        card = ctk.CTkFrame(
            self, corner_radius=14,
            fg_color=("#f0f0f0", "#252525"),
            border_width=2,
            border_color=("#bbbbbb", "#3a3a3a"),
        )
        card.place(relx=0.5, rely=0.5, anchor="center")
        card.lift()
        self._overlay_card = card

        ctk.CTkLabel(
            card, text=title, font=ctk.CTkFont(size=15, weight="bold"),
            text_color=self._OVERLAY_COLORS.get(accent, "#1f6aa5"),
        ).pack(anchor="w", padx=24, pady=(18, 6))

        body_holder = ctk.CTkFrame(card, fg_color="transparent")
        body_holder.pack(fill=BOTH, padx=4, pady=(0, 8))
        build_body(body_holder)

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill=X, padx=20, pady=(8, 18))

        for label, callback, kind in buttons:
            color = {"primary": "#1f6aa5", "danger": "#a83232", "secondary": "#555555"}.get(kind, "#1f6aa5")
            hover = {"primary": "#2576b5", "danger": "#b73e3e", "secondary": "#666666"}.get(kind, "#2576b5")

            def make_handler(cb):
                def handler() -> None:
                    if cb is not None:
                        try:
                            cb()
                        except Exception:
                            pass
                    self._dismiss_overlay()
                return handler

            ctk.CTkButton(
                btn_row, text=label, command=make_handler(callback),
                height=32, fg_color=color, hover_color=hover,
            ).pack(side=RIGHT, padx=(8, 0))

    def _show_toast(self, title: str, message: str, kind: str = "info") -> None:
        def build_body(card: "ctk.CTkFrame") -> None:
            ctk.CTkLabel(
                card, text=message, font=ctk.CTkFont(size=12),
                justify="left", wraplength=420,
                text_color=("#1a1a1a", "#e0e0e0"),
            ).pack(anchor="w", padx=20, pady=(4, 12))
        self._show_overlay(title, build_body, [("ОК", None, "primary")], accent=kind)

    _SNACKBAR_COLORS = {
        "info":  "#1f6aa5",
        "warn":  "#b07a2d",
        "error": "#a83232",
        "ok":    "#2e7d32",
    }

    def _show_snackbar(self, message: str, kind: str = "ok", duration_ms: int = 2500) -> None:
        """Bottom-of-screen in-app notification that auto-dismisses.
        Stacks below previous snackbar if one is still visible."""
        existing = getattr(self, "_snackbar", None)
        if existing is not None:
            try:
                existing.destroy()
            except Exception:
                pass
        bar = ctk.CTkFrame(
            self, fg_color=self._SNACKBAR_COLORS.get(kind, "#1f6aa5"),
            corner_radius=8, border_width=0,
        )
        ctk.CTkLabel(
            bar, text=message, font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#ffffff",
        ).pack(padx=20, pady=10)
        bar.place(relx=0.5, rely=0.92, anchor="center")
        bar.lift()
        self._snackbar = bar

        def dismiss() -> None:
            current = getattr(self, "_snackbar", None)
            if current is bar:
                self._snackbar = None
            try:
                bar.destroy()
            except Exception:
                pass

        self.after(duration_ms, dismiss)

    def _show_confirm(self, title: str, message: str, danger: bool = False) -> bool:
        result_var = BooleanVar(value=False)
        self._overlay_result_var = result_var

        def build_body(card: "ctk.CTkFrame") -> None:
            ctk.CTkLabel(
                card, text=message, font=ctk.CTkFont(size=12),
                justify="left", wraplength=420,
                text_color=("#1a1a1a", "#e0e0e0"),
            ).pack(anchor="w", padx=20, pady=(4, 12))

        yes_kind = "danger" if danger else "primary"
        self._show_overlay(
            title, build_body,
            [("Да", lambda: result_var.set(True), yes_kind), ("Нет", None, "secondary")],
            accent=("error" if danger else "warn"),
        )
        if self._overlay_card is not None:
            self.wait_window(self._overlay_card)
        return bool(result_var.get())

    # ========== TRAY / STARTUP / EXPORT ==========

    def _make_tray_image(self, active: bool) -> Image.Image:
        name = "medved_active.png" if active else "medved_inactive.png"
        try:
            return Image.open(_asset_path(name)).convert("RGBA")
        except Exception:
            size = 64
            image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            color = (46, 125, 50, 255) if active else (140, 140, 140, 255)
            draw.ellipse((2, 2, size - 2, size - 2), fill=color)
            return image

    def _init_tray(self) -> None:
        try:
            menu = pystray.Menu(
                pystray.MenuItem("Открыть", self._tray_show, default=True),
                pystray.MenuItem("Подключить", self._tray_connect),
                pystray.MenuItem("Отключить", self._tray_disconnect),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Выход", self._tray_quit),
            )
            self._tray_icon = pystray.Icon(
                "MeDVeD",
                self._make_tray_image(False),
                "MeDVeD (отключено)",
                menu,
            )
            self._tray_icon.run_detached()
        except Exception as error:
            self._tray_icon = None
            self.log(f"Не удалось запустить трей: {error}")

    def _refresh_tray_icon(self, active: bool) -> None:
        if self._tray_icon is None:
            return
        try:
            self._tray_icon.icon = self._make_tray_image(active)
            self._tray_icon.title = "MeDVeD (подключено)" if active else "MeDVeD (отключено)"
        except Exception:
            pass

    def _tray_show(self, _icon=None, _item=None) -> None:
        self.after(0, self._show_window)

    def _show_window(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()

    def _tray_connect(self, _icon=None, _item=None) -> None:
        self.after(0, self.connect_selected)

    def _tray_disconnect(self, _icon=None, _item=None) -> None:
        self.after(0, self.disconnect)

    def _tray_quit(self, _icon=None, _item=None) -> None:
        self.after(0, self._real_quit)

    def _safe_auto_connect_startup(self) -> None:
        try:
            self._auto_connect_startup()
        except Exception as error:
            import traceback
            self.log(f"[auto-connect ERROR] {type(error).__name__}: {error}")
            self.log(traceback.format_exc())

    def _auto_connect_startup(self) -> None:
        target_key = self.settings.auto_connect_key
        for index, profile in enumerate(self.profiles):
            if self._profile_ping_key(profile) == target_key:
                self.selected_uuid = profile.uuid or None
                self.selected_indices = [index]
                try:
                    self.profile_list.selection_set(str(index))
                except Exception:
                    pass
                self.log(f"Автоподключение: {profile.name}")
                self.connect_selected()
                return
        self.log("Автоподключение: профиль не найден")

    # ========== PHASE 2: PING / AUTO-REFRESH / NOTIFICATIONS ==========

    def test_all_pings(self) -> None:
        if not self.profiles:
            self._show_toast("MeDVeD", "Нет профилей для проверки.", "info")
            return
        self.log(f"Проверка пинга {len(self.profiles)} профилей...")
        snapshot = list(self.profiles)

        def worker() -> None:
            for profile in snapshot:
                ping_ms = _tcp_ping(profile.server, profile.port, timeout=3.0)
                key = self._profile_ping_key(profile)
                self.after(0, self._set_profile_ping, key, ping_ms)
            self.after(0, self.log, "Проверка пинга завершена")

        threading.Thread(target=worker, daemon=True).start()

    def test_all_speeds(self) -> None:
        """TCP-download speedtest against each server's host:port. Measures raw
        throughput by reading from the open socket — works for any open TCP port
        without needing a special endpoint. Approximation, but reflects real
        latency × bandwidth."""
        if not self.profiles:
            self._show_toast("MeDVeD", "Нет профилей для проверки.", "info")
            return
        self.log(f"Speedtest: {len(self.profiles)} серверов...")
        snapshot = list(self.profiles)

        def measure(host: str, port: int, duration: float = 2.0) -> Optional[float]:
            try:
                start = time.perf_counter()
                with socket.create_connection((host, port), timeout=4.0) as sock:
                    sock.settimeout(duration + 1.0)
                    # Send a generic TLS ClientHello-ish ping so the server keeps
                    # the socket open and we get bytes back.
                    sock.sendall(b"\x16\x03\x01\x00\x05\x01\x00\x00\x01\x00")
                    received = 0
                    while time.perf_counter() - start < duration:
                        try:
                            chunk = sock.recv(65536)
                        except socket.timeout:
                            break
                        if not chunk:
                            break
                        received += len(chunk)
                    elapsed = time.perf_counter() - start
                if elapsed <= 0 or received == 0:
                    return None
                return (received * 8) / elapsed / 1000.0  # kbps
            except (OSError, socket.timeout):
                return None

        def worker() -> None:
            for profile in snapshot:
                kbps = measure(profile.server, profile.port)
                label = "—" if kbps is None else (f"{kbps/1000:.1f} Мбит/с" if kbps >= 1000 else f"{kbps:.0f} Кбит/с")
                key = self._profile_ping_key(profile)
                self.after(0, self._set_profile_speed_label, key, label)
            self.after(0, self.log, "Speedtest завершён")

        threading.Thread(target=worker, daemon=True).start()

    def _set_profile_speed_label(self, key: str, label: str) -> None:
        # Reuse the ping column to show the speed (we keep ping cache separate).
        if self.profile_list is None:
            return
        for index, profile in enumerate(self.profiles):
            if self._profile_ping_key(profile) == key:
                try:
                    self.profile_list.set(str(index), "ping", label)
                except Exception:
                    pass
                return

    def export_profiles(self) -> None:
        if not self.profiles:
            self._show_toast("MeDVeD", "Нет профилей для экспорта.", "info")
            return
        path = filedialog.asksaveasfilename(
            title="Экспортировать профили",
            defaultextension=".json",
            initialfile=f"medved_profiles_{time.strftime('%Y%m%d')}.json",
            filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")],
        )
        if not path:
            return
        try:
            payload = {
                "app": "MeDVeD",
                "version": __version__,
                "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "profiles": [p.to_dict() for p in self.profiles],
                "subscriptions": list(self.settings.subscriptions),
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            self._show_snackbar(f"Экспортировано {len(self.profiles)} профилей", "ok")
        except Exception as error:
            self._show_toast("MeDVeD", f"Не удалось экспортировать: {error}", "error")

    def import_profiles_from_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Импорт профилей из файла",
            filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as error:
            self._show_toast("MeDVeD", f"Не удалось прочитать файл: {error}", "error")
            return
        raw_profiles = data.get("profiles") if isinstance(data, dict) else data
        if not isinstance(raw_profiles, list):
            self._show_toast("MeDVeD", "Неверный формат файла.", "error")
            return
        imported = [VlessProfile.from_dict(p) for p in raw_profiles if isinstance(p, dict)]
        if not imported:
            self._show_toast("MeDVeD", "В файле нет валидных профилей.", "info")
            return
        before = len(self.profiles)
        self._append_profiles(imported)
        # Also pull subscriptions if present and not already known
        if isinstance(data, dict):
            for sub in (data.get("subscriptions") or []):
                if isinstance(sub, str) and sub and sub not in self.settings.subscriptions:
                    self.settings.subscriptions.append(sub)
            save_settings(self.settings)
        added = len(self.profiles) - before
        self._show_snackbar(f"Импортировано: +{added} (из {len(imported)})", "ok")

    def _set_profile_ping(self, key: str, ping_ms: Optional[float]) -> None:
        self._profile_pings[key] = ping_ms
        if self.profile_list is None:
            return
        for index, profile in enumerate(self.profiles):
            if self._profile_ping_key(profile) == key:
                try:
                    self.profile_list.set(str(index), "ping", self._format_profile_ping(key))
                except Exception:
                    pass
                return

    def _schedule_subscription_refresh(self) -> None:
        if self._refresh_after_id is not None:
            try:
                self.after_cancel(self._refresh_after_id)
            except Exception:
                pass
            self._refresh_after_id = None
        hours = self.settings.subscription_refresh_hours
        if hours <= 0 or not self.settings.subscriptions:
            return
        delay_ms = hours * 3600 * 1000
        self._refresh_after_id = self.after(delay_ms, self._auto_refresh_subscriptions)

    def _auto_refresh_subscriptions(self) -> None:
        self._refresh_after_id = None
        if self.settings.subscriptions:
            self.log("Авто-обновление подписок...")
            self.refresh_subscriptions()
        self._schedule_subscription_refresh()

    def _notify(self, title: str, message: str) -> None:
        if not self.settings.notifications_enabled or plyer_notification is None:
            return
        try:
            plyer_notification.notify(title=title, message=message, app_name="MeDVeD", timeout=5)
        except Exception:
            pass

    def _copy_selected_link(self) -> None:
        if self.selected_uuid is None:
            self._show_toast("MeDVeD", "Выберите профиль.", "info")
            return
        profile = next((p for p in self.profiles if p.uuid == self.selected_uuid), None)
        if profile is None:
            self._show_toast("MeDVeD", "Выберите профиль.", "info")
            return
        link = profile_to_vless_link(profile)
        self.clipboard_clear()
        self.clipboard_append(link)
        self.log(f"Ссылка скопирована: {profile.name}")

    # ========== AUTO-UPDATE ==========

    def _manual_check_for_update(self) -> None:
        if GITHUB_REPO.startswith("USERNAME/"):
            self._show_toast(
                "Обновления",
                "Источник обновлений не настроен в этой сборке.",
                "warn",
            )
            return
        if self._update_available:
            self._start_update_flow()
            return
        self._show_snackbar("Проверяю обновления…", "info", duration_ms=3000)

        def worker() -> None:
            had_update_before = self._update_available
            self._check_for_update()
            if not self._update_available and not had_update_before:
                self.after(0, lambda: self._show_snackbar(
                    f"У тебя последняя версия (v{__version__})", "ok", duration_ms=3000,
                ))

        threading.Thread(target=worker, daemon=True).start()

    def _check_for_update(self) -> None:
        if GITHUB_REPO.startswith("USERNAME/"):
            return
        api = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        req = urllib.request.Request(api, headers={
            "User-Agent": f"MeDVeD/{__version__}",
            "Accept": "application/vnd.github+json",
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return
        tag = str(data.get("tag_name", "")).strip()
        if not tag or _parse_version(tag) <= _parse_version(__version__):
            return
        asset_url = ""
        for asset in data.get("assets") or []:
            name = str(asset.get("name", "")).lower()
            if name.endswith(".exe"):
                asset_url = str(asset.get("browser_download_url", ""))
                break
        if not asset_url:
            return
        self.after(0, self._on_update_available, tag.lstrip("vV"), asset_url)

    def _on_update_available(self, version: str, asset_url: str) -> None:
        self._update_available = True
        self._update_version = version
        self._update_url = asset_url
        self.log(f"Доступно обновление: {version}")
        self._render_update_badge()

    def _render_update_badge(self) -> None:
        if not self._update_available or self.current_view != "main":
            if self._update_badge is not None:
                try:
                    self._update_badge.place_forget()
                except Exception:
                    pass
            return
        btn = getattr(self, "burger_button", None)
        if btn is None:
            return
        if self._update_badge is None:
            self._update_badge = ctk.CTkFrame(
                self, width=12, height=12, corner_radius=6,
                fg_color="#e53935", border_width=2, border_color="#212121",
            )
        try:
            self.update_idletasks()
            bx = btn.winfo_rootx() - self.winfo_rootx() + btn.winfo_width() - 8
            by = btn.winfo_rooty() - self.winfo_rooty() - 2
            self._update_badge.place(x=bx, y=by)
            self._update_badge.lift()
        except Exception:
            pass

    def _start_update_flow(self) -> None:
        if not self._update_url:
            return
        confirm = self._show_confirm(
            "Обновление MeDVeD",
            f"Скачать и установить версию {self._update_version}?\n\n"
            f"Текущая: {__version__}\n"
            f"Приложение закроется и автоматически перезапустится после обновления.",
        )
        if not confirm:
            return
        if not getattr(sys, "frozen", False):
            self._show_toast("Обновление", "Авто-обновление доступно только в собранном exe.", "warn")
            return
        self._show_snackbar("Скачиваю обновление…", "info", duration_ms=4000)
        threading.Thread(target=self._download_and_apply_update, daemon=True).start()

    def _download_and_apply_update(self) -> None:
        tmp_dir = Path(tempfile.gettempdir())
        target_exe = Path(sys.executable).resolve()
        new_exe = tmp_dir / f"MeDVeD_new_{os.getpid()}.exe"

        try:
            req = urllib.request.Request(self._update_url, headers={"User-Agent": f"MeDVeD/{__version__}"})
            with urllib.request.urlopen(req, timeout=180) as resp, new_exe.open("wb") as out:
                shutil.copyfileobj(resp, out)
        except Exception as error:
            self.after(0, lambda e=error: self._show_toast("Обновление", f"Не удалось скачать: {e}", "error"))
            return

        # Write a real .ps1 file + run it with -File. Single-line -Command was
        # flaky under DETACHED_PROCESS (script would silently skip Move-Item).
        # Each step also writes to %TEMP%\MeDVeD_updater.log via PowerShell.
        log_path = tmp_dir / "MeDVeD_updater.log"
        ps_file = tmp_dir / f"MeDVeD_updater_{os.getpid()}.ps1"
        ps_script = (
            f"$ErrorActionPreference = 'SilentlyContinue'\n"
            f"$logPath = '{log_path}'\n"
            f"\"=== updater start $(Get-Date) ===\" | Out-File -FilePath $logPath -Append\n"
            f"\"Waiting for PID {os.getpid()} to exit...\" | Out-File -FilePath $logPath -Append\n"
            f"try {{\n"
            f"    $proc = Get-Process -Id {os.getpid()} -ErrorAction Stop\n"
            f"    $proc.WaitForExit(30000) | Out-Null\n"
            f"    \"PID exited cleanly\" | Out-File -FilePath $logPath -Append\n"
            f"}} catch {{\n"
            f"    \"PID already gone (ok): $_\" | Out-File -FilePath $logPath -Append\n"
            f"}}\n"
            f"Start-Sleep -Milliseconds 800\n"
            f"try {{\n"
            f"    Move-Item -Force -Path '{new_exe}' -Destination '{target_exe}' -ErrorAction Stop\n"
            f"    \"Move OK -> {target_exe}\" | Out-File -FilePath $logPath -Append\n"
            f"}} catch {{\n"
            f"    \"Move FAILED: $_\" | Out-File -FilePath $logPath -Append\n"
            f"    exit 1\n"
            f"}}\n"
            f"try {{\n"
            f"    Start-Process -FilePath '{target_exe}'\n"
            f"    \"Start-Process OK\" | Out-File -FilePath $logPath -Append\n"
            f"}} catch {{\n"
            f"    \"Start FAILED: $_\" | Out-File -FilePath $logPath -Append\n"
            f"}}\n"
        )
        try:
            ps_file.write_text(ps_script, encoding="utf-8-sig")
        except Exception as error:
            self.after(0, lambda e=error: self._show_toast("Обновление", f"Не удалось подготовить установщик: {e}", "error"))
            return

        try:
            # Just CREATE_NO_WINDOW — DETACHED_PROCESS combined with redirected
            # DEVNULL pipes silently breaks powershell.exe in some PyInstaller
            # frozen-exe scenarios (the helper PID returns, but the script body
            # never runs). On a GUI app the child outlives the parent anyway.
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-NonInteractive",
                 "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass",
                 "-File", str(ps_file)],
                creationflags=subprocess.CREATE_NO_WINDOW,
                close_fds=False,
            )
        except Exception as error:
            self.after(0, lambda e=error: self._show_toast("Обновление", f"Не удалось запустить установщик: {e}", "error"))
            return

        # Give the OS time to actually create the PowerShell process before we
        # tear our own window down. 500ms was sometimes not enough on cold systems.
        self.after(2000, self._real_quit)


def main() -> None:
    _install_global_excepthooks()
    _write_log_line(f"=== MeDVeD v{__version__} starting (frozen={getattr(sys,'frozen',False)}) ===")
    if not _acquire_single_instance_lock():
        _activate_existing_window("MeDVeD")
        sys.exit(0)
    _cleanup_stale_tun_adapters()
    settings = load_settings()
    ctk.set_appearance_mode(settings.appearance_mode if settings.appearance_mode in ("dark", "light", "system") else "dark")
    ctk.set_default_color_theme("blue")
    app = VlessApp()
    if "--minimized" in sys.argv[1:] or settings.start_minimized:
        app.after(100, app.withdraw)
    app.mainloop()


if __name__ == "__main__":
    main()