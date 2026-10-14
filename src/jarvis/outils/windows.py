"""Accès bas niveau à Windows (ctypes) partagé par les outils : fenêtres, touches, raccourcis, corbeille."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

WINDOWS = sys.platform == "win32"

# Touches multimédia
VK_MEDIA_NEXT, VK_MEDIA_PREV, VK_MEDIA_STOP, VK_MEDIA_PLAY_PAUSE = 0xB0, 0xB1, 0xB2, 0xB3
VK_VOLUME_MUTE = 0xAD


def appuyer_touche(vk: int) -> None:
    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, 0x1, 0)  # KEYEVENTF_EXTENDEDKEY
    user32.keybd_event(vk, 0, 0x1 | 0x2, 0)  # + KEYEVENTF_KEYUP


def fenetres_visibles() -> list[dict]:
    """Fenêtres de premier niveau visibles avec un titre : handle, titre, pid."""
    if not WINDOWS:
        return []
    user32 = ctypes.windll.user32
    resultat: list[dict] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def rappel(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            longueur = user32.GetWindowTextLengthW(hwnd)
            if longueur:
                tampon = ctypes.create_unicode_buffer(longueur + 1)
                user32.GetWindowTextW(hwnd, tampon, longueur + 1)
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                resultat.append({"hwnd": hwnd, "titre": tampon.value, "pid": pid.value})
        return True

    user32.EnumWindows(rappel, 0)
    return resultat


def premier_plan(hwnd: int) -> bool:
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    # Astuce classique : une pression sur Alt autorise SetForegroundWindow depuis un autre processus
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 2, 0)
    return bool(user32.SetForegroundWindow(hwnd))


def fenetre_au_premier_plan() -> dict | None:
    if not WINDOWS:
        return None
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    longueur = user32.GetWindowTextLengthW(hwnd)
    tampon = ctypes.create_unicode_buffer(longueur + 1)
    user32.GetWindowTextW(hwnd, tampon, longueur + 1)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return {"hwnd": hwnd, "titre": tampon.value, "pid": pid.value,
            "rect": (rect.left, rect.top, rect.right, rect.bottom)}


def ecran_principal() -> tuple[int, int]:
    user32 = ctypes.windll.user32
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def secondes_inactivite() -> float:
    """Temps depuis la dernière action clavier/souris (pour le briefing à la première activité)."""
    if not WINDOWS:
        return 0.0

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
    return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0


def mettre_a_la_corbeille(chemin: Path) -> bool:
    """Suppression récupérable (SHFileOperation + FOF_ALLOWUNDO)."""

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    FO_DELETE, FOF_ALLOWUNDO, FOF_NOCONFIRMATION, FOF_SILENT, FOF_NOERRORUI = 3, 0x40, 0x10, 0x4, 0x400
    op = SHFILEOPSTRUCTW(None, FO_DELETE, str(chemin) + "\0\0", None,
                         FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI, False, None, None)
    return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0 and not op.fAnyOperationsAborted


def _bureau_reel() -> Path:
    from jarvis.outils.fichiers import dossier_connu  # import tardif : fichiers importe ce module

    return dossier_connu("Desktop")


def dossiers_menu_demarrer() -> list[Path]:
    dossiers = [Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
                Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
                Path.home() / "Desktop", _bureau_reel(), Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop"]
    return list(dict.fromkeys(d for d in dossiers if d.exists()))


def cible_raccourci(lnk: Path) -> str:
    """Chemin cible d'un raccourci .lnk (via WScript.Shell)."""
    try:
        import comtypes.client

        shell = comtypes.client.CreateObject("WScript.Shell")
        return str(shell.CreateShortcut(str(lnk)).TargetPath or "")
    except Exception:  # noqa: BLE001
        return ""


def powershell(script: str, delai: float = 30) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                          text=True, timeout=delai, encoding="utf-8", errors="replace",
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
