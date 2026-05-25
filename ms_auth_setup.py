"""
Runs after Chrome has been brought to front with Microsoft security page open.
Takes a screenshot, checks state, and proceeds with authenticator setup.
"""
import pyautogui, time, subprocess, ctypes
from ctypes import wintypes

pyautogui.FAILSAFE = False

def screenshot(path):
    subprocess.run([
        'powershell', '-Command',
        f'Add-Type -AssemblyName System.Windows.Forms,System.Drawing;'
        f'$s=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;'
        f'$b=New-Object System.Drawing.Bitmap($s.Width,$s.Height);'
        f'$g=[System.Drawing.Graphics]::FromImage($b);'
        f'$g.CopyFromScreen($s.Location,[System.Drawing.Point]::Empty,$s.Size);'
        f'$b.Save("{path}");$g.Dispose();$b.Dispose()'
    ])

# Wait for Chrome to open URL and come to front
time.sleep(8)
screenshot(r'E:\SunoMaster\scripts\ms_state1.png')
print("Initial state captured", flush=True)

# Wait for page to fully load
time.sleep(4)
screenshot(r'E:\SunoMaster\scripts\ms_state2.png')
print("Page loaded state captured", flush=True)
