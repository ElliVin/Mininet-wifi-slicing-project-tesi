#!/usr/bin/env python3

#modulo per espressioni regolari (serve a cercare MAC address nel testo).
import re
#permette di lanciare comandi Linux (tc, iw, ip, ecc.) dal codice.
import subprocess
#serve per inserire pause (es. ogni 1 secondo nel ciclo principale).
import time


# PARAMETRI DI RETE ________________________________________________________

# interfaccia wireless dell’access point. È quella su cui passa il traffico in uscita (egress).
IF = "ap1-wlan1"
# interfaccia “virtuale” IFB (Intermediate Functional Block) per modellare il traffico in ingresso (ingress).
IFB = "ifb0"

# MODFICABILI ------------------------
# banda totale disponibile (40 Mbit/s)
TOTAL_MBIT = 7
# frazione di banda quando è presente almeno un’ambulanza (75% a PRIO, 25% a CAR).   
SPLIT_WHEN_AMB = (0.75, 0.25)
# intervallo di scansione: ogni quanti secondi il controller ricontrolla lo stato (2 secondi).
SCAN_SEC = 1
#-------------------------------------

#___________________________________________________________________________


# STRUTTURE STATO RUNTIME __________________________________________________

#Il controller tiene una memoria interna di cosa è connesso
known_clients = set()      # set di MAC attivi
ip_by_mac = {}             # MAC -> IP
class_by_mac = {}          # MAC -> "ambulance"/"car"
type_by_mac = {}           # MAC -> tipo SUMO ("passenger", "emergency", ecc.)
#stazioni = []              #array di stazioni per la generazione del file

#___________________________________________________________________________



# FUNZIONE DI IDENTIFICAZIONE DELLE STAZIONI COLLEGATE______________________

# in partica il controller deve capire quali stazioni sono connesse, perche
# dopo gli servirá l'ip per definire chi appartiene e a quale slice

# LA FUNZIONE ELEBORA IL TESTO E RITAGLIA IL MAC
MAC_RE = re.compile(r"Station\s+([0-9a-f:]{17})", re.I)

#___________________________________________________________________________



#È una utility per eseguire comandi shell (tipo iw, tc, ip) e catturare l’output
def sh(cmd):
   return subprocess.run(cmd, shell=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)



# FUNZIONI DI PARSING MAC -> IP ___________________________________________

# Lancia il comando: iw dev ap1-wlan1 station dump
# che mostra tutti i dispositivi associati all’AP.
def parse_stations():
    out = sh(f"iw dev {IF} station dump").stdout
    # Usa la regex MAC_RE per estrarre tutti i MAC address.
    return set(MAC_RE.findall(out))
# Restituisce un set di MAC connessi in quel momento.
# ESEMPIO RISULTATO: {"02:00:00:00:01:00", "02:00:00:00:01:00"}

#Serve per sapere l’indirizzo IP associato a un MAC address attraverso tabella ARP
def ip_for_mac(mac: str) -> str:
    # Divide il MAC in parti, es: "02:00:00:00:01:FA" → ["02", "00", "00", "00", "01", "FA"]
    parts = mac.split(":")
    # Prende il 5° elemento (indice 4)
    num_hex = parts[4]
    # Converte da esadecimale a decimale
    decimal = int(num_hex, 16)
    # Costruisce l'IP "10.0.0.<valore + 1>"
    ip = f"10.0.0.{decimal + 1}"
    return ip


#__________________________________________________________________________



#  GET TIPO DI VEICOLO _______________________________________________________

def classify_from_type(vehicle_type):
    """
    Determina la slice in base al tipo del veicolo SUMO.
    """
    vt = vehicle_type.lower()
    if vt == "emergency":
        return "ambulance"
    elif vt in ("passenger", "car"):
        return "car"
    else:
        return "car"


import os

def get_vehicle_type(ip: str) -> str:
    """
    Data l'IP di una stazione (es. 10.0.0.7),
    deduce il nome del veicolo SUMO (car7) e ne restituisce il tipo.
    """
    # 1) Estraggo il numero finale dell'IP
    try:
        id_num = int(ip.split('.')[-1])  # esempio: 10.0.0.7 → 7
    except ValueError:
        return "passenger"  # fallback

    # 2️) Percorso assoluto del file
    file_path = os.path.expanduser(
        "/home/elena/Progetti/mininet-wifi/mininet-wifi/examples/SUMODIR/PROVA/vehicle_types.txt"
    )

    # 3) Apro il file e lo scorro riga per riga
    try:
        with open(file_path, "r") as f:
            for line in f:
                # Elimino eventuali spazi e newline
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("ID"):
                    continue  # salta righe vuote o commenti

                # Divido per virgole
                parts = [p.strip() for p in line.split(",")]

                # Deve avere almeno due colonne (id, tipo)
                if len(parts) < 2:
                    continue

                # Confronto l'ID (colonna 0) con id_num
                try:
                    file_id = int(parts[0])
                except ValueError:
                    continue

                if file_id == id_num:
                    return parts[1]  # restituisce il tipo (seconda colonna)
    except FileNotFoundError:
        print(f"File non trovato: {file_path}")
        return "passenger"

    # 4️) Se non trova nulla
    return "passenger"



#_____________________________________________________________________________

# FUNZIONE CHE RISCRIVE IL FILE.SH E LO SOVRASCRIVE __________________________

class Station:
    """
    Oggetto stazione con due attributi:
    - tipo: tipo di veicolo (es. 'car', 'ambulance')
    - ip: indirizzo IP associato
    """
    def __init__(self, tipo, ip):
        self.tipo = tipo
        self.ip = ip


def genera_script_htb(stations, output_path="/home/elena/Progetti/mininet-wifi/mininet-wifi/SETUP/controller/wlan1_dynamic.sh"):
    """
    Genera uno script .sh con struttura completa per egress + ingress shaping (HTB + IFB)
    e filtri basati sulle stazioni attive.
    """

    has_ambulance = any(sta.tipo.lower() == "ambulance" or sta.tipo.lower() == "ambulanza" for sta in stations)

    # parametri base
    base_rate = 2
    prio_rate = 5
    total_rate = 7

    # Apriamo il file in UTF-8 (fondamentale su Windows!)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("#!/bin/bash\n\n")
        f.write('echo "[+] Inizializzo HTB su ap1-wlan1 (egress)"\n\n')

        # Pulizia iniziale
        f.write("# Pulizia configurazioni precedenti\n\n")
        f.write("tc qdisc del dev ap1-wlan1 root 2>/dev/null\n")
        f.write("tc qdisc del dev ap1-wlan1 ingress 2>/dev/null\n")
        f.write("tc qdisc del dev ifb0 root 2>/dev/null\n")
        f.write("ip link set ifb0 down 2>/dev/null\n")
        f.write("ip link delete ifb0 type ifb 2>/dev/null\n\n")

        # Parte 1: traffico in uscita
        f.write("# Parte 1: traffico in uscita da ap1-wlan1\n\n")
        f.write("tc qdisc add dev ap1-wlan1 root handle 1: htb default 30\n")
        f.write(f"tc class add dev ap1-wlan1 parent 1: classid 1:1 htb rate {total_rate}mbit ceil {total_rate}mbit\n\n")

        # Slice configurazioni
        if has_ambulance:
            # slice prioritaria
            f.write("# PRIORITARY slice\n")
            f.write(f"tc class add dev ap1-wlan1 parent 1:1 classid 1:10 htb rate {prio_rate}mbit ceil {prio_rate}mbit\n")
            f.write("tc qdisc add dev ap1-wlan1 parent 1:10 handle 10: pfifo limit 100\n\n")

            # slice non prioritaria
            f.write("# NON-PRIORITARY slice\n")
            f.write(f"tc class add dev ap1-wlan1 parent 1:1 classid 1:20 htb rate {base_rate}mbit ceil {base_rate}mbit\n")
            f.write("tc qdisc add dev ap1-wlan1 parent 1:20 handle 20: pfifo limit 100\n\n")
        #else:
        f.write("# DEFAULT slice\n")
        f.write(f"tc class add dev ap1-wlan1 parent 1:1 classid 1:30 htb rate {total_rate}mbit ceil {total_rate}mbit\n")
        f.write("tc qdisc add dev ap1-wlan1 parent 1:30 handle 30: pfifo limit 100\n\n")

        # Filtri egress
        f.write("# Filter per traffico in uscita (server -> stazioni)\n\n")
        for sta in stations:
            if has_ambulance:
                if sta.tipo.lower() == "ambulance" or sta.tipo.lower() == "ambulanza":
                    f.write(f"tc filter add dev ap1-wlan1 protocol ip parent 1:0 prio 1 u32 match ip dst {sta.ip} flowid 1:10\n")
                else:
                    f.write(f"tc filter add dev ap1-wlan1 protocol ip parent 1:0 prio 1 u32 match ip dst {sta.ip} flowid 1:20\n")
            else:
                f.write(f"tc filter add dev ap1-wlan1 protocol ip parent 1:0 prio 1 u32 match ip dst {sta.ip} flowid 1:30\n")

        f.write('\necho "[+] Configuro IFB per ingress shaping su ap1-wlan1"\n\n')

        # Parte 2: traffico in ingresso
        f.write("# Parte 2: traffico in ingresso su ap1-wlan1\n\n")
        f.write("modprobe ifb\n")
        f.write("ip link add ifb0 type ifb\n")
        f.write("ip link set ifb0 up\n\n")
        f.write("# Redirige tutto l'ingresso di ap1-wlan1 su ifb0\n\n")
        f.write("tc qdisc add dev ap1-wlan1 ingress\n")
        f.write("tc filter add dev ap1-wlan1 parent ffff: protocol ip u32 match u32 0 0 \\\n")
        f.write("    action mirred egress redirect dev ifb0\n\n")

        # Shaping IFB
        f.write("# Shaping su ifb0 (traffico da stazioni verso server)\n\n")
        f.write("tc qdisc add dev ifb0 root handle 2: htb default 10\n")
        f.write(f"tc class add dev ifb0 parent 2: classid 2:1 htb rate {total_rate}mbit ceil {total_rate}mbit\n\n")

        if has_ambulance:
            f.write("# Slice 2:10 prioritaria\n")
            f.write(f"tc class add dev ifb0 parent 2:1 classid 2:10 htb rate {prio_rate}mbit ceil {prio_rate}mbit\n")
            f.write("tc qdisc add dev ifb0 parent 2:10 handle 10: pfifo limit 100\n\n")

            f.write("# Slice 2:20 non prioritaria\n")
            f.write(f"tc class add dev ifb0 parent 2:1 classid 2:20 htb rate {base_rate}mbit ceil {base_rate}mbit\n")
            f.write("tc qdisc add dev ifb0 parent 2:20 handle 20: pfifo limit 100\n\n")

            for sta in stations:
                if sta.tipo.lower() == "ambulance" or sta.tipo.lower() == "ambulanza":
                    f.write(f"tc filter add dev ifb0 protocol ip parent 2:0 prio 1 u32 match ip src {sta.ip} flowid 2:10\n")
                else:
                    f.write(f"tc filter add dev ifb0 protocol ip parent 2:0 prio 1 u32 match ip src {sta.ip} flowid 2:20\n")

        else:
            f.write("# Slice 2:20 unica per tutte le stazioni\n")
            f.write(f"tc class add dev ifb0 parent 2:1 classid 2:20 htb rate {total_rate}mbit ceil {total_rate}mbit\n")
            f.write("tc qdisc add dev ifb0 parent 2:20 handle 20: pfifo limit 100\n\n")
            for sta in stations:
                f.write(f"tc filter add dev ifb0 protocol ip parent 2:0 prio 1 u32 match ip src {sta.ip} flowid 2:20\n")

        f.write('\necho "[✓] Configurazione completa (egress + ingress con IFB)"\n')

    print(f"[Writer] File {output_path} aggiornato ({len(stations)} stazioni, "
          f"{'ambulanza presente' if has_ambulance else 'nessuna ambulanza'}).")

#_____________________________________________________________________________


def rimuovi_stazione_per_ip(lista, ip):
    return [s for s in lista if s.ip != ip]

def stampa_stazioni(stazioni):
    """Stampa tutte le stazioni presenti nella lista."""
    if not stazioni:
        print("[!] Nessuna stazione attiva.")
        return
    print("\n[Elenco stazioni attive]:")
    for s in stazioni:
        print(f" - Tipo: {s.tipo:<10} | IP: {s.ip}")

# ---- Funzioni placeholder per evitare errori ----
def ensure_filters(mac, ip, cls):
    """Placeholder: in questa versione non fa nulla."""
    pass

def delete_filters(ip):
    """Placeholder: in questa versione non fa nulla."""
    pass
# -------------------------------------------------

def main():
    print("[*] starting controller")
    global known_clients, ip_by_mac, class_by_mac, type_by_mac
    stazioni = []
    while True:
        try:
            current = parse_stations()

            # DISCONNESSIONI
            gone = known_clients - current
            if gone:
                print(f"→ Disconnessioni trovate: {gone}")
            for mac in list(gone):
                ip = ip_by_mac.get(mac)
                if ip:
                    delete_filters(ip)
                    stazioni = rimuovi_stazione_per_ip(stazioni, ip)
                    genera_script_htb(stazioni)
                    sh("chmod +x /home/elena/Progetti/mininet-wifi/mininet-wifi/SETUP/wlan1_dynamic.sh && bash /home/elena/Progetti/mininet-wifi/mininet-wifi/SETUP/wlan1_dynamic.sh")
                    print("[*] File .sh aggiornato (disconnessione)")
                    # Segnala al processo principale di aggiornare l'AP
                    with open("/tmp/update_ap.flag", "w") as f:
                        f.write("update\n")
                    print("[Signal] Richiesto aggiornamento AP")

                    #stampa_stazioni(stazioni)

                print(f"[-] Disconnessione {ip}")
                known_clients.discard(mac)
                ip_by_mac.pop(mac, None)
                class_by_mac.pop(mac, None)
                type_by_mac.pop(mac, None)

            # NUOVE CONNESSIONI
            new = current - known_clients
            if new:
                print(f"→ Nuove connessioni trovate: {new}")
            for mac in new:
                known_clients.add(mac)   # 🔹 spostato qui!
                ip = ip_for_mac(mac) or ip_by_mac.get(mac)
                if not ip:
                    time.sleep(0.5)
                    ip = ip_for_mac(mac)
                    if not ip:
                        continue

                vehicle_type = get_vehicle_type(ip)
                cls = classify_from_type(vehicle_type)
                print(f"[+] Nuova connessione {ip} ({vehicle_type}) → slice {cls}")

                stazioni.append(Station(cls, ip))
                genera_script_htb(stazioni)
                sh("chmod +x /home/elena/Progetti/mininet-wifi/mininet-wifi/SETUP/wlan1_dynamic.sh && bash /home/elena/Progetti/mininet-wifi/mininet-wifi/SETUP/wlan1_dynamic.sh")
                print("[*] File .sh aggiornato (connessione)")
                with open("/tmp/update_ap.flag", "w") as f:
                    f.write("update\n")
                print("[Signal] Richiesto aggiornamento AP")
                #stampa_stazioni(stazioni)

                ip_by_mac[mac] = ip
                class_by_mac[mac] = cls
                type_by_mac[mac] = vehicle_type

            time.sleep(SCAN_SEC)

        except KeyboardInterrupt:
            print("\n[!] Stop richiesto.")
            break
        except Exception as e:
            print(f"[!] Errore: {e}")
            time.sleep(SCAN_SEC)



if __name__ == "__main__":
    main()
