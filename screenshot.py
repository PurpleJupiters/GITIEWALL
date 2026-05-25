import subprocess, sys
from PIL import Image
import io

result = subprocess.run(
    ["adb", "-s", "AE6RUT4531003110", "exec-out", "screencap", "-p"],
    capture_output=True, timeout=10
)
img = Image.open(io.BytesIO(result.stdout))
w, h = img.size
img.resize((int(w*0.667), int(h*0.667)), Image.LANCZOS).save(r"C:\Users\equat\Downloads\screen_small.png")
print(f"Original: {w}x{h}, saved resized copy")
