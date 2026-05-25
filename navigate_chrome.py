import ctypes, time, sys
from ctypes import wintypes
import pyautogui

pyautogui.FAILSAFE = False

user32 = ctypes.windll.user32

# Give time for this process to become independent before acting
time.sleep(4)

# Disable Windows foreground lock timeout
SPI_SETFOREGROUNDLOCKTIMEOUT = 0x2001
user32.SystemParametersInfoW(SPI_SETFOREGROUNDLOCKTIMEOUT, 0, 0, 0x02)

# Find Chrome window
hwnd = None
def enum_cb(h, l):
    global hwnd
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(h, buf, 512)
    title = buf.value
    if user32.IsWindowVisible(h) and len(title) > 3:
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, cls, 256)
        if "Chrome_WidgetWin" in cls.value:
            hwnd = h
    return True

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
user32.EnumWindows(WNDENUMPROC(enum_cb), 0)

if hwnd:
    # Force Chrome to front from this independent process
    fg = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(fg, None)
    ch_tid = user32.GetWindowThreadProcessId(hwnd, None)
    user32.AttachThreadInput(fg_tid, ch_tid, True)
    user32.ShowWindow(hwnd, 9)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    user32.AttachThreadInput(fg_tid, ch_tid, False)
    time.sleep(1.5)

    pyautogui.hotkey('ctrl', 'l')
    time.sleep(0.6)
    pyautogui.hotkey('ctrl', 'a')
    time.sleep(0.3)
    pyautogui.write('https://account.microsoft.com/security', interval=0.05)
    pyautogui.press('enter')
    time.sleep(8)

# Screenshot to confirm
import subprocess
subprocess.run([
    'powershell', '-Command',
    'Add-Type -AssemblyName System.Windows.Forms,System.Drawing;'
    '$s=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;'
    '$b=New-Object System.Drawing.Bitmap($s.Width,$s.Height);'
    '$g=[System.Drawing.Graphics]::FromImage($b);'
    '$g.CopyFromScreen($s.Location,[System.Drawing.Point]::Empty,$s.Size);'
    '$b.Save("E:\\SunoMaster\\scripts\\screen_final.png");'
    '$g.Dispose();$b.Dispose()'
])
