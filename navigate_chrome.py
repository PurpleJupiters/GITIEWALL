import pyautogui
import time
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

# Find Chrome window by PID
hwnd = None
target_pid = 30324

def enum_cb(h, l):
    global hwnd
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    if pid.value == target_pid:
        title_len = user32.GetWindowTextLengthW(h)
        if title_len > 0:
            hwnd = h
    return True

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
user32.EnumWindows(WNDENUMPROC(enum_cb), 0)

# If PID-specific search failed, try finding any Chrome window
if not hwnd:
    def find_chrome(h, l):
        global hwnd
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(h, buf, 256)
        if "Chrome" in buf.value or "Google" in buf.value:
            hwnd = h
        return True
    user32.EnumWindows(WNDENUMPROC(find_chrome), 0)

print(f"Chrome HWND: {hwnd}", flush=True)

if hwnd:
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    time.sleep(1.5)

# Use Ctrl+L to focus address bar
pyautogui.hotkey('ctrl', 'l')
time.sleep(0.6)
pyautogui.hotkey('ctrl', 'a')
time.sleep(0.3)
pyautogui.write('https://account.microsoft.com/security', interval=0.04)
pyautogui.press('enter')
print("Navigating...", flush=True)
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
print("Screenshot saved as screen7.png", flush=True)
