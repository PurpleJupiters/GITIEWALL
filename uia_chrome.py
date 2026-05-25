"""
Use Windows UI Automation to find Chrome's address bar and set URL directly.
No keyboard focus required.
"""
import ctypes
import ctypes.wintypes
import time
import subprocess
import sys

sys.stdout.reconfigure(line_buffering=True)

# Load UIAutomation via comtypes
try:
    import comtypes.client
    import comtypes.gen
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "comtypes", "-q"])
    import comtypes.client

from comtypes import GUID
import comtypes.client

# Initialize UIAutomation
uia = comtypes.client.CreateObject(
    "{ff48dba4-60ef-4201-aa87-54103eef594e}",
    interface=comtypes.gen.UIAutomationClient.IUIAutomation if hasattr(comtypes.gen, 'UIAutomationClient') else None
)
