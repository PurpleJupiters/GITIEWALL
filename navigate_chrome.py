import pyautogui
import time
import ctypes
from ctypes import wintypes

pyautogui.FAILSAFE = False

user32 = ctypes.windll.user32

# Find Chrome window
hwnd = None

def enum_cb(h, l):
    global hwnd
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(h, buf, 512)
    if "Chrome" in buf.value or "RepostExchange" in buf.value or "Google" in buf.value:
        if user32.IsWindowVisible(h):
            hwnd = h
    return True

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
print(f"Chrome HWND: {hwnd}", flush=True)

def force_focus(target_hwnd):
    fg_hwnd = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None)
    tgt_tid = user32.GetWindowThreadProcessId(target_hwnd, None)
    user32.AttachThreadInput(fg_tid, tgt_tid, True)
    user32.ShowWindow(target_hwnd, 9)   # SW_RESTORE
    user32.BringWindowToTop(target_hwnd)
    user32.SetForegroundWindow(target_hwnd)
    time.sleep(0.5)
    user32.AttachThreadInput(fg_tid, tgt_tid, False)

if hwnd:
    force_focus(hwnd)
    time.sleep(1)

    # Click address bar (Ctrl+L)
    pyautogui.hotkey('ctrl', 'l')
    time.sleep(0.5)
    pyautogui.hotkey('ctrl', 'a')
    time.sleep(0.3)
    pyautogui.write('https://account.microsoft.com/security', interval=0.05)
    time.sleep(0.3)
    pyautogui.press('enter')
    print("URL typed and Enter pressed", flush=True)
    time.sleep(7)

# Screenshot
import subprocess
subprocess.run([
    'powershell', '-Command',
    'Add-Type -AssemblyName System.Windows.Forms,System.Drawing; '
    '$s=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds; '
    '$b=New-Object System.Drawing.Bitmap($s.Width,$s.Height); '
    '$g=[System.Drawing.Graphics]::FromImage($b); '
    '$g.CopyFromScreen($s.Location,[System.Drawing.Point]::Empty,$s.Size); '
    '$b.Save("E:\\SunoMaster\\scripts\\screen7.png"); '
    '$g.Dispose(); $b.Dispose()'
])
print("Screenshot saved.", flush=True)
