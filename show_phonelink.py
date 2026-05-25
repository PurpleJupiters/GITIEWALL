import ctypes, time, subprocess
from ctypes import wintypes

user32 = ctypes.windll.user32
time.sleep(3)

proc_id = None
import subprocess
result = subprocess.run(['powershell', '-Command',
    '(Get-Process PhoneExperienceHost -ErrorAction SilentlyContinue | Select-Object -First 1).Id'],
    capture_output=True, text=True)
try:
    proc_id = int(result.stdout.strip())
except:
    pass

hwnd = None
def enum_cb(h, l):
    global hwnd
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    if proc_id and pid.value == proc_id and user32.IsWindowVisible(h):
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(h, buf, 512)
        if len(buf.value) > 0:
            hwnd = h
    return True

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
user32.EnumWindows(WNDENUMPROC(enum_cb), 0)

SPI_SETFOREGROUNDLOCKTIMEOUT = 0x2001
user32.SystemParametersInfoW(SPI_SETFOREGROUNDLOCKTIMEOUT, 0, 0, 0x02)

if hwnd:
    user32.ShowWindow(hwnd, 9)
    user32.BringWindowToTop(hwnd)
    fg = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(fg, None)
    ch_tid = user32.GetWindowThreadProcessId(hwnd, None)
    user32.AttachThreadInput(fg_tid, ch_tid, True)
    user32.SetForegroundWindow(hwnd)
    user32.AttachThreadInput(fg_tid, ch_tid, False)

time.sleep(2)
subprocess.run(['powershell', '-Command',
    'Add-Type -AssemblyName System.Windows.Forms,System.Drawing;'
    '$s=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;'
    '$b=New-Object System.Drawing.Bitmap($s.Width,$s.Height);'
    '$g=[System.Drawing.Graphics]::FromImage($b);'
    '$g.CopyFromScreen($s.Location,[System.Drawing.Point]::Empty,$s.Size);'
    '$b.Save("E:\\SunoMaster\\scripts\\phonelink_state.png");'
    '$g.Dispose();$b.Dispose()'
])
