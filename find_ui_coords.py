import xml.etree.ElementTree as ET
tree = ET.parse(r"C:\Users\equat\Downloads\ui.xml")
for node in tree.iter("node"):
    text = node.get("text", "")
    if "Music" in text or "YouTube" in text or "storage" in text.lower():
        print(f"text={text!r}  bounds={node.get('bounds')}")
