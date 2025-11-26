#!/usr/bin/env python3
import xml.etree.ElementTree as ET
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))        # .../mn_wifi/sumo
ROU_DIR = os.path.join(BASE_DIR, "MAPPA")                    # .../mn_wifi/sumo/MAPPA
rou_file = os.path.join(ROU_DIR, "mappa_emergency.rou.xml")  # file di input
out_file = os.path.join(BASE_DIR, "vehicle_types.txt")       # file di output

# Percorso del file .rou.xml
#rou_file = "/home/eventura/Progetti/mininet-wifi/mininet-wifi/mn_wifi/sumo/MAPPA/mappa_emergency.rou.xml"
#out_file = "vehicle_types.txt"

# Legge e parse del file XML
tree = ET.parse(rou_file)
root = tree.getroot()

# Apre il file di output
with open(out_file, "w", encoding="utf-8") as f:
    f.write("ID,TYPE\n")
    for veh in root.findall("vehicle"):
        vid = str(int(veh.get("id")) + 1)   # +1 per coerenza con Mininet
        vtype = veh.get("type")
        f.write(f"{vid},{vtype}\n")

print(f"✅ File '{out_file}' generato con {len(root.findall('vehicle'))} veicoli.")
