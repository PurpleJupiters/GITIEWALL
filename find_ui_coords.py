import xml.etree.ElementTree as ET
tree = ET.parse(r"C:\Users\equat\Downloads\ui.xml")
for node in tree.iter("node"):
    t = node.get("text", "").strip()
    if t:
        print(f"{t!r:50s} bounds={node.get('bounds')}")
