import ctypes, time
from ctypes import wintypes
import pyautogui
import subprocess

pyautogui.FAILSAFE = False
user32 = ctypes.windll.user32

time.sleep(3)

SPI_SETFOREGROUNDLOCKTIMEOUT = 0x2001
user32.SystemParametersInfoW(SPI_SETFOREGROUNDLOCKTIMEOUT, 0, 0, 0x02)

# Find Chrome window by class name
hwnd = None
def enum_cb(h, l):
    global hwnd
    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, cls, 256)
    if "Chrome_WidgetWin_1" == cls.value and user32.IsWindowVisible(h):
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(h, buf, 512)
        if len(buf.value) > 0:
            hwnd = h
    return True

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
user32.EnumWindows(WNDENUMPROC(enum_cb), 0)

if hwnd:
    # Get Chrome window rect to find address bar coordinates
    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
    rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))

    # Restore and force to front
    fg = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(fg, None)
    ch_tid = user32.GetWindowThreadProcessId(hwnd, None)
    user32.AttachThreadInput(fg_tid, ch_tid, True)
    user32.ShowWindow(hwnd, 9)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    user32.AttachThreadInput(fg_tid, ch_tid, False)
    time.sleep(1.5)

    # Click address bar: ~center-x of window, ~65px from top of window
    addr_x = (rect.left + rect.right) // 2
    addr_y = rect.top + 65
    pyautogui.click(addr_x, addr_y)
    time.sleep(0.5)
    pyautogui.hotkey('ctrl', 'a')
    time.sleep(0.3)
    pyautogui.write('https://account.microsoft.com/security', interval=0.05)
    pyautogui.press('enter')
    time.sleep(8)

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
