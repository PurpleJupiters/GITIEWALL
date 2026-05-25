import ctypes, time
from ctypes import wintypes

user32 = ctypes.windll.user32

WM_KEYDOWN  = 0x0100
WM_KEYUP    = 0x0101
WM_CHAR     = 0x0102
VK_CONTROL  = 0x11
VK_L        = 0x4C
VK_RETURN   = 0x0D
VK_A        = 0x41

# Find Chrome main window
hwnd = None
def enum_cb(h, l):
    global hwnd
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(h, buf, 512)
    title = buf.value
    if ("Chrome" in title or "RepostExchange" in title) and user32.IsWindowVisible(h):
        hwnd = h
    return True

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
print(f"Chrome hwnd: {hwnd}", flush=True)

if not hwnd:
    print("Chrome not found!", flush=True)
    exit(1)

# Restore and raise Chrome
user32.ShowWindow(hwnd, 9)
user32.BringWindowToTop(hwnd)

# Disable foreground lock timeout so we CAN steal focus
SPI_SETFOREGROUNDLOCKTIMEOUT = 0x2001
user32.SystemParametersInfoW(SPI_SETFOREGROUNDLOCKTIMEOUT, 0, 0, 0x02)
user32.SetForegroundWindow(hwnd)
time.sleep(1.5)

# Send Ctrl+L via PostMessage to focus address bar
user32.PostMessageW(hwnd, WM_KEYDOWN, VK_CONTROL, 0)
user32.PostMessageW(hwnd, WM_KEYDOWN, VK_L, 0)
user32.PostMessageW(hwnd, WM_KEYUP,   VK_L, 0)
user32.PostMessageW(hwnd, WM_KEYUP,   VK_CONTROL, 0)
time.sleep(0.6)

# Send Ctrl+A to select all in address bar
user32.PostMessageW(hwnd, WM_KEYDOWN, VK_CONTROL, 0)
user32.PostMessageW(hwnd, WM_KEYDOWN, VK_A, 0)
user32.PostMessageW(hwnd, WM_KEYUP,   VK_A, 0)
user32.PostMessageW(hwnd, WM_KEYUP,   VK_CONTROL, 0)
time.sleep(0.4)

# Type URL char by char via WM_CHAR
url = "https://account.microsoft.com/security"
for ch in url:
    user32.PostMessageW(hwnd, WM_CHAR, ord(ch), 0)
    time.sleep(0.02)

time.sleep(0.4)
user32.PostMessageW(hwnd, WM_KEYDOWN, VK_RETURN, 0)
user32.PostMessageW(hwnd, WM_KEYUP,   VK_RETURN, 0)
print("URL sent via PostMessage", flush=True)
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
