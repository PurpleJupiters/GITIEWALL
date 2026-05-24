import os
import pytesseract
from PIL import Image

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

folder = r"C:\Users\equat\Desktop\TEMPORARY\Screen Saves"
apps = set()

for f in sorted(os.listdir(folder)):
    if f.lower().endswith(('.jpg', '.jpeg', '.png')):
        path = os.path.join(folder, f)
        try:
            text = pytesseract.image_to_string(Image.open(path))
            for line in text.splitlines():
                line = line.strip()
                if 2 < len(line) < 40 and not any(c in line for c in ['|','/','{','}','=']):
                    apps.add(line)
        except Exception as e:
            print(f"Error on {f}: {e}")

output = r"E:\SunoMaster\scripts\app_list.txt"
with open(output, 'w', encoding='utf-8') as out:
    for app in sorted(apps):
        out.write(app + '\n')

print(f"Done — {len(apps)} items saved to {output}")
