#!/usr/bin/env python3
import sys, csv, os

# === CONFIGURAZIONE PORTABILE ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", "..", ".."))

# Percorsi che prima erano assoluti
MNWIFI_SUMO = os.path.join(PROJECT_ROOT, "mn_wifi", "sumo")
SETUP_CONTROLLER_DIR = os.path.join(PROJECT_ROOT, "SETUP", "controller")
SETUP_APCONTROLLER_DIR = os.path.join(SETUP_CONTROLLER_DIR, "ap_controller")
LOG_DIR = os.path.join(PROJECT_ROOT, "LOG_STAZIONI")
MAPPA_DIR = BASE_DIR  # sei già in MAPPA

#sys.path.insert(0, "/home/eventura/Progetti/mininet-wifi/mininet-wifi/mn_wifi/sumo")
sys.path.insert(0, MNWIFI_SUMO)

from mininet.log import setLogLevel, info
from mn_wifi.cli import CLI
from mn_wifi.net import Mininet_wifi
from mn_wifi.node import OVSKernelAP
#from mininet.node import RemoteController
from mininet.node import Controller

import subprocess
import threading, time
from runner import sumo
from mn_wifi.link import wmediumd
from mn_wifi.wmediumdConnector import interference

# funzione di conversione degli ip to ap ..................

def host_ip_to_ap(ip_addr):
    """
    Converte un indirizzo IP in nome AP:
    10.0.0.201 -> ap1, 10.0.0.202 -> ap2, ..., 10.0.0.210 -> ap10
    """
    try:
        last_octet = int(str(ip_addr).strip().split('.')[-1])
        idx = last_octet - 200
        if 1 <= idx <= 10:
            return f"ap{idx}"
        else:
            raise ValueError("IP fuori range previsto")
    except Exception:
        return "ap_unk"


def get_ap_from_log(file_path):
    """
    Legge un file di log iperf e restituisce l'AP associato
    in base all'indirizzo IP remoto trovato nella riga:
      "connected with 10.0.0.20X"
    """
    try:
        with open(file_path, "r", errors="ignore") as f:
            for line in f:
                if "connected with" in line:
                    match = re.search(r"connected with\s+(\d+\.\d+\.\d+\.\d+)", line)
                    if match:
                        ip_remote = match.group(1)
                        ap_name = host_ip_to_ap(ip_remote)
                        print(f"[INFO] File {file_path}: trovato {ip_remote} → {ap_name}")
                        return ap_name
        print(f"[WARN] Nessun indirizzo IP trovato in {file_path}")
        return "ap_unk"
    except Exception as e:
        print(f"[ERROR] Impossibile leggere {file_path}: {e}")
        return "ap_unk"

# avvio generazione di grafici ............................

def genera_grafici():
    try:
        # Percorso assoluto della directory dove si trova QUESTO script
        base_dir = os.path.dirname(os.path.abspath(__file__))
        script_path = os.path.join(base_dir, "garfico_for_ap.py")

        print(f"[DEBUG] Directory corrente: {os.getcwd()}")
        print(f"[DEBUG] Cartella script base: {base_dir}")
        print(f"[DEBUG] Percorso completo script: {script_path}")

        if os.path.exists(script_path):
            print("\n*** Generazione automatica dei grafici in corso... ***\n")
            # imposta la directory di lavoro corretta prima di eseguire
            subprocess.run(["python3", script_path], check=True, cwd=base_dir)
            print("*** Grafici generati con successo. ***\n")
        else:
            print(f"[!] Script grafico non trovato: {script_path}\n")

    except Exception as e:
        print(f"[!] Errore durante la generazione dei grafici: {e}\n")

# gestore stazioni zombie o malconnesse ...................


import re
from datetime import datetime


def get_iperf_target(log_path):
    """
    Estrae l'IP del server dal log iperf (prima riga con 'connected with' o 'Connecting to host').
    Ritorna None se non trovato.
    """
    if not os.path.exists(log_path):
        return None

    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            m = re.search(r'connected with ([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)', line)
            if m:
                return m.group(1)
            m2 = re.search(r'Connecting to host ([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)', line)
            if m2:
                return m2.group(1)
    return None


def has_zero_throughput(log_path, threshold=20):
    """
    Ritorna True se nel log iperf ci sono almeno `threshold` righe consecutive
    che contengono '0.00' (indicando throughput nullo).
    """
    if not os.path.exists(log_path):
        return False

    zero_count = 0
    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f.readlines()[-threshold:]:
            if "0.00" in line:
                zero_count += 1
    return zero_count >= threshold


def monitor_iperf_and_position(cars, base_dir="/tmp", check_interval=5):
    """
    Monitora periodicamente le stazioni:
      - se la posizione non cambia per troppo tempo → ferma iperf
      - se throughput = 0 e stazione non ferma → riavvia iperf
    """
    frozen_threshold = 50
    restart_cooldown = 30
    last_restart = {}
    log_path = os.path.join(base_dir, "iperf_monitor.log")

    while True:
        for sta in cars:
            try:
                sta_name = sta.name
                pid_file = os.path.join(base_dir, f"{sta_name}.pid")
                iperf_log = os.path.join(base_dir, f"{sta_name}_iperf.log")
                #base_dir_positions = "/home/eventura/Progetti/mininet-wifi/mininet-wifi/examples/SUMODIR/MAPPA"
                base_dir_positions = MAPPA_DIR
                pos_file = os.path.join(base_dir_positions, f"position-{sta_name}-mn-telemetry.txt")

                # se non ha un iperf attivo, passa
                if not os.path.exists(pid_file):
                    continue
                with open(pid_file) as f:
                    pid = f.read().strip()
                if not pid or not pid.isdigit():
                    continue

                # controlla throughput
                zero_problem = has_zero_throughput(iperf_log)

                # controllo blocco tramite conta-righe
                ripetizioni = conta_righe_uguali(pos_file)

                # inizializza msg per evitare errori
                msg = None

                # timestamp per riavvii iperf
                now = time.time()

                #serve una condizione per le stazioni ch non vanno mai a 0

                if ripetizioni > 100 :
                    msg = f"[{datetime.now():%H:%M:%S}] {sta_name} POSIZIONE RIPETUTA {ripetizioni} volte — eliminazione\n"
                    print(msg.strip())

                    # elimina stazione (metodo "remove" del Mininet-WiFi)
                    try:
                        sta.setPosition("0.0,0.0,0.0")
                        sta.cmd(f"kill {pid}")      # termina iperf
                        # rimuovo pid file (per evitare controlli successivi)
                        #20/11/2025 AGGIUNTA PER NON FARE RIPARTIRE IL CICLO
                        if os.path.exists(pid_file):
                            os.remove(pid_file)

                        # azzero il file log
                        open(iperf_log, "w").close()
                        
                    except Exception as e:
                        print(f"[ERRORE] impossibile terminare {sta_name}: {e}")

                    with open(log_path, "a") as log:
                        log.write(msg)
                    continue

                if zero_problem:

                    if ripetizioni > frozen_threshold :

                        msg = f"[{datetime.now():%H:%M:%S}] {sta_name} POSIZIONE RIPETUTA {ripetizioni} volte — eliminazione\n"
                        print(msg.strip())

                        # elimina stazione (metodo "remove" del Mininet-WiFi)
                        try:
                            sta.setPosition("0.0,0.0,0.0")
                            sta.cmd(f"kill {pid}")      # termina iperf
                            # rimuovo pid file (per evitare controlli successivi)
                            #20/11/2025 AGGIUNTA PER NON FARE RIPARTIRE IL CICLO
                            if os.path.exists(pid_file):
                                os.remove(pid_file)

                            # azzero il file log
                            open(iperf_log, "w").close()
                            
                        except Exception as e:
                            print(f"[ERRORE] impossibile terminare {sta_name}: {e}")

                        with open(log_path, "a") as log:
                            log.write(msg)
                        continue

                    # verifica che non sia appena stata killata
                    elif now - last_restart.get(sta_name, 0) > restart_cooldown:
                        server_ip = get_iperf_target(iperf_log)
                        if server_ip:
                            msg = f"[{datetime.now():%H:%M:%S}] {sta_name} THR=0 ma non ferma — riavvio iperf verso {server_ip}\n"
                            sta.cmd(f"kill {pid}")
                            sta.cmd(f"iperf -c {server_ip} -t 9999 -i 2 > {iperf_log} 2>&1 & echo $! > {pid_file}")
                            #sta.cmd(f"xterm -hold -e 'iperf -c {server_ip} -t 9999 -i 2 | tee {iperf_log}' & echo $! > {pid_file}")
                            last_restart[sta_name] = now
                        else:
                            msg = f"[{datetime.now():%H:%M:%S}] {sta_name} THR=0 ma IP sconosciuto — kill iperf\n"
                            sta.cmd(f"kill {pid}")
                            last_restart[sta_name] = now

                if msg:
                    print(msg.strip())
                    with open(log_path, "a", encoding="utf-8") as f:
                        f.write(msg)

            except Exception as e:
                print(f"[WARN] monitor error for {sta.name}: {e}")

        time.sleep(check_interval)

# gestore controller .......................................

stop_threads = False  #flag globale
def monitor_updates(ap):
    """
    Monitora il file /tmp/update_<ap.name>.flag.
    Quando viene creato, esegue lo script di slicing corrispondente:
        /home/eventura/.../controller/<ap.name>_setup.sh
    """
    global stop_threads
    flag_path = f"/tmp/update_{ap.name}.flag"
    script_path = os.path.join(SETUP_APCONTROLLER_DIR, f"{ap.name}_setup.sh")
    #script_path = f"/home/eventura/Progetti/mininet-wifi/mininet-wifi/SETUP/controller/{ap.name}_setup.sh"

    while stop_threads:
        if os.path.exists(flag_path):
            os.remove(flag_path)
            info(f"\n*** [Signal] Aggiornamento richiesto per {ap.name} ***\n")

            # Debug: verifica che l'interfaccia esista nel namespace
            debug = ap.cmd("ip link show | grep wlan1")
            info(f"*** [DEBUG] Namespace {ap.name}:\n{debug}\n")

            # Esegui lo script corrispondente
            if os.path.exists(script_path):
                result = ap.cmd(f"bash {script_path}")
                info(result + "\n")
                info(f"*** [Signal] Script di slicing applicato su {ap.name}\n")
            else:
                info(f"!!! [Warning] Script non trovato: {script_path}\n")

        time.sleep(1)

# file conta righe ........................................
def conta_righe_uguali(percorso_file):
    conteggi = {}

    with open(percorso_file, "r", encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()  # togli newline e spazi
            if not linea:
                continue

            # ignora le posizioni 0,0
            if linea in ("0,0", "0.0,0.0"):
                continue

            conteggi[linea] = conteggi.get(linea, 0) + 1

    # se non ci sono posizioni diverse da 0,0
    if not conteggi:
        return 0

    # restituisce SOLO il numero massimo di ripetizioni
    count_max = max(conteggi.values())
    return count_max


# setp dei file di setup ;) ...............................
def ensure_ap_setup_files(ap_names):
    """
    Crea la cartella e gli script di setup per ogni AP se non esistono.
    """
    #base_dir = "/home/eventura/Progetti/mininet-wifi/mininet-wifi/SETUP/controller/ap_controller"
    base_dir = SETUP_APCONTROLLER_DIR
    os.makedirs(base_dir, exist_ok=True)

    for ap_name in ap_names:

        script_path = os.path.join(base_dir, f"{ap_name}_setup.sh")
        if not os.path.exists(script_path):
            with open(script_path, "w", encoding="utf-8") as f:
                f.write("#!/bin/bash\n\n# Script iniziale vuoto per slicing HTB/IFB\n")
            os.chmod(script_path, 0o755)
            print(f"[Init] Creato file: {script_path}")
        else:
            print(f"[Init] File già esistente: {script_path}")

# gestore kill iperf rimasti ..............................


def kill_all_iperf():
    """
    Chiude SOLO le sessioni ancora attive usando i PID file /tmp/<nodo>.pid
    e, per ciascuna, appende il contenuto di /tmp/<nodo>_iperf.log
    nel file LOG_STAZIONI/<nodo>_apM.log, aggiungendo l'ORARIO DI FINE.
    Poi termina xterm (PID nel .pid) e i suoi figli.
    """
    print("[*] Chiusura sessioni iperf attive (basata sui PID file)...")

    #log_dir = "/home/eventura/Progetti/mininet-wifi/mininet-wifi/LOG_STAZIONI"
    log_dir = LOG_DIR
    os.makedirs(log_dir, exist_ok=True)

    # cerca PID file delle stazioni/auto (staN.pid, carN.pid)
    pid_files = [f for f in os.listdir("/tmp") if f.endswith(".pid") and (f.startswith("sta") or f.startswith("car"))]
    if not pid_files:
        print("[✓] Nessun PID file trovato in /tmp; nulla da fare.")
        return

    for pid_fname in pid_files:
        node_name = pid_fname[:-4]  # rimuove ".pid" -> sta1 / car3
        pid_path  = os.path.join("/tmp", pid_fname)

        try:
            with open(pid_path) as pf:
                pid = pf.read().strip()
            if not pid or not pid.isdigit():
                continue

            # processo vivo? (xterm)
            alive = (subprocess.run(f"ps -p {pid} >/dev/null 2>&1", shell=True).returncode == 0)
            if not alive:
                continue  # non attivo: salta

            # log temporaneo prodotto da tee
            tmp_log = f"/tmp/{node_name}_iperf.log"

            # trova il file storico: <node>_apM.log se esiste, altrimenti _unknown.log
            
            ap_val = get_ap_from_log(tmp_log)

            target_log = None
            for f in os.listdir(log_dir):
                if f.startswith(node_name + "_"+ ap_val) and f.endswith(".log"):
                    
                    target_log = os.path.join(log_dir, f)
                    break
            if target_log is None:
                target_log = os.path.join(log_dir, f"{node_name}_unknown.log")

            end_time = datetime.now().strftime("%H:%M:%S")

            print(f"   → [{node_name}] salvo log in {os.path.basename(target_log)} e chiudo PID {pid}")

            # appende contenuto iperf (se c'è) + orario di fine
            if os.path.exists(tmp_log):
                with open(target_log, "a") as fout, open(tmp_log, "r", errors="ignore") as fin:
                    fout.write(f"\n--- LOG IPERF CHIUSO ({node_name}) ---\n")
                    fout.write(fin.read())
                    fout.write(f"\nORARIO DI FINE: {end_time}\n")
                # opzionale: pulizia del tmp
                # os.remove(tmp_log)
            else:
                # non c'è ancora il file tmp: scrivo solo l'orario di fine (almeno segno che ho chiuso)
                with open(target_log, "a") as fout:
                    fout.write(f"\n--- LOG IPERF CHIUSO ({node_name}) ---\n")
                    fout.write(f"(nessun tmp log trovato: {tmp_log})\n")
                    fout.write(f"ORARIO DI FINE: {end_time}\n")

            # termina xterm e i suoi figli (iperf/tee)
            subprocess.run(f"pkill -9 -P {pid}", shell=True)  # figli del xterm
            subprocess.run(f"kill -9 {pid}", shell=True)      # xterm stesso

        except Exception as e:
            print(f"[!] Errore su {pid_fname}: {e}")

    print("[✓] Chiusura completata.\n")



# topologia ...............................................

def topology():
    "Crea rete Wi-Fi con AP da CSV e un host per ogni AP"

    # -------------------------------------------------------
    # Pulizia dei log precedenti in LOG_STAZIONI
    #log_dir = "/home/eventura/Progetti/mininet-wifi/mininet-wifi/LOG_STAZIONI"
    log_dir = LOG_DIR
    os.makedirs(log_dir, exist_ok=True)

    info("*** Pulizia file in LOG_STAZIONI...\n")
    for f in os.listdir(log_dir):
        file_path = os.path.join(log_dir, f)
        if os.path.isfile(file_path):
            os.remove(file_path)
            info(f"   → Svuotato {file_path}\n")
    # -------------------------------------------------------

    net = Mininet_wifi(controller=Controller,
                       accessPoint=OVSKernelAP,
                       link=wmediumd,
                       wmediumd_mode=interference)
    
    #  CREAZIONE DEI NODI  #################################

    info("*** Adding Ryu controller\n")
    c0 = net.addController('c0')

    info("*** Creating nodes\n")
    ap_list = []
    with open("ap.csv", "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            ap_list.append(row)
    info(f"*** Trovati {len(ap_list)} Access Point nel file\n")

    aps = []
    channels = [36,40,44]
    for i, ap in enumerate(ap_list, start=1):
        ap_name = f"ap{i}"
        x, y = float(ap["x"]), float(ap["y"])
        r = float(ap["range_m"])
        aps.append(net.addAccessPoint(
            ap_name,
            ssid="new-ssid",
            mode='ac',
            channel=str(channels[(i-1)%len(channels)]),
            vht_capab='[VHT80]',
            ht_capab='[HT40+]',
            position=f"{x},{y},0",
            range=r
        ))
        info(f"   → {ap_name} pos=({x},{y}) range={r}\n")

    # Creazione host cablati per ciascun AP ---
    hosts = []
    for i in range(len(aps)):
        ip_host = f"10.0.0.{200 + i + 1}/8"
        host_name = f"h{i+1}"
        h = net.addHost(host_name, ip=ip_host)
        hosts.append(h)

    # --- Auto mobili controllate da SUMO ---
    for id in range(0, 200):
        net.addCar('car%s' % (id + 1), wlans=1, mode='ac')

    info("*** Configuro modello di propagazione\n")
    net.setPropagationModel(model="logDistance", exp=2.0)
    net.configureNodes()
    
    for i in range(len(hosts)):
        info(f"   → Access Point collegato: {aps[i]}\n")
        net.addLink(hosts[i], aps[i])  # collegamento diretto host <-> AP
        #info(f"   → Host {host_name} collegato a {aps[i].name} ({ip_host})\n")
    ###########################################################


    # GENERATORE FILE MAPPATUA TIPI ###########################
    info("*** Generazione del file vehicle_types.txt da SUMO .rou.xml\n")

    try:
        '''
        result = subprocess.run(
            ["python3", "/home/eventura/Progetti/mininet-wifi/mininet-wifi/mn_wifi/sumo/extract_vehicle_types.py"],
            check=True,
            capture_output=True,
            text=True
        )
        '''
        result = subprocess.run(
            ["python3", os.path.join(MNWIFI_SUMO, "extract_vehicle_types.py")],
            check=True,
            capture_output=True,
            text=True
        )
        info(result.stdout)   # stampa il messaggio "File 'vehicle_types.txt' generato..."
    except subprocess.CalledProcessError as e:
        info(f"Errore durante la generazione del file: {e}\n")
        info(f"Output: {e.stdout}\n")
        info(f"Errore: {e.stderr}\n")
    ###########################################################


    # COLLEGAMENTO SUMO #######################################
    info("*** Avvio SUMO\n")
    net.useExternalProgram(program=sumo, port=8813,
                           extra_params=["--start --delay 1000 --step-length 0.1"],
                           clients=1, exec_order=0)
    ###########################################################
    
    info("*** Avvio rete\n")
    net.build()
    c0.start()
    for ap in aps:
        ap.start([c0])

    # AVVIO THREAD DEL CONTROLLER DI POSIZIONI ################

    # Prima di avviare il thread di monitoraggio
    info("*** Pulizia log precedenti\n")
    for sta in net.cars:
        sta_name = sta.name
        for ext in ["_iperf.log", "_iperf_restarted.log", ".pid"]:
            path = f"/tmp/{sta_name}{ext}"
            if os.path.exists(path):
                os.remove(path)
                info(f"   → Pulito {path}\n")

    #avvio thread
    threading.Thread(
        target=lambda: (time.sleep(2), monitor_iperf_and_position(net.cars)),
        daemon=True
    ).start()
    ###########################################################

    # AVVIO THREAD DEL CONTROLLER DI SLICE ####################
    
    ensure_ap_setup_files([ap.name for ap in aps])
    #il controller va avviato per ogni ap 
    #ogni ap fara riferimento al suo dcumento di setup apN_setup.sh
    for ap in aps:
        timeout = 20  # massimo 20 secondi
        while (not ap.shell or ap.waiting) and timeout > 0:
            time.sleep(0.2)
            timeout -= 0.2

        if not ap.shell:
            info(f"[!] Shell non pronta per {ap.name}, salto il controller\n")
            continue
        
        threading.Thread(target=monitor_updates, args=(ap,), daemon=True).start()
        #DEBUG: mi permette di aprire un trmilnale per visualizzare le connessioni
        #controller_path = "/home/eventura/Progetti/mininet-wifi/mininet-wifi/SETUP/controller/generic_slicing_controller.py"
        controller_path = os.path.join(SETUP_CONTROLLER_DIR, "generic_slicing_controller.py")
        ap.cmd(f"xterm -hold -e bash -c 'python {controller_path} {ap.name}; exec bash' &")
        info(f"*** Controller di slicing avviato su {ap.name}\n")
    
    ###########################################################

    # --- inizializzazione server iperf ---
    info("*** Avvio server iperf su h1-h10\n")
    for h in hosts:
        h.cmd(f"iperf -s -i 2 & echo $! > /tmp/{h.name}.pid")
        #h.cmd(f"xterm -hold -e 'iperf -s -i 2' & echo $! > /tmp/{h.name}.pid")

    # --- Assegna IP dinamici alle auto ---
    for id, car in enumerate(net.cars):
        car.setIP(f"10.0.0.{id + 1}/8", intf=car.wintfs[0].name)

    # --- Telemetria: auto + AP ---
    net.telemetry(nodes=net.cars + aps, data_type='position',
                  min_x=0, min_y=0, max_x=2446.84, max_y=1372.38)


    info("*** CLI in esecuzione\n")
    CLI(net)

    # --- Terminazione ---
    for h in hosts:
        try:
            pid = h.cmd(f"cat /tmp/{h.name}.pid").strip()
            if pid:
                h.cmd("kill -9 " + pid)
                info(f"*** Server iperf terminato su {h.name}\n")
        except:
            pass
    
    

    info("*** Stop rete\n")

    # --- Terminazione controllata ---
    info("\n*** Arresto controllato...\n")

    # Termina tutti i processi iperf
    kill_all_iperf()

    # Avvia in thread separato ----------------------------------------
    grafico_thread = threading.Thread(target=genera_grafici)
    grafico_thread.start()

    # Aspetta la fine del thread di generazione grafici
    grafico_thread.join()
    info("*** Thread grafici completato.\n")
    #------------------------------------------------------------------

    # Segnala ai thread di fermarsi
    global stop_threads
    stop_threads = True
    info("*** Attendo terminazione dei thread di monitoraggio...\n")

    # Pausa per permettere ai thread di uscire
    time.sleep(2)

    # Termina eventuali controller e finestre xterm rimaste aperte
    subprocess.run("pkill -9 -f generic_slicing_controller.py", shell=True)
    subprocess.run("pkill -9 -f xterm", shell=True)

    # Arresta la rete
    info("*** Arresto rete Mininet-WiFi...\n")
    try:
        net.stop()
        info("*** Rete chiusa correttamente.\n")
    except Exception as e:
        info(f"[!] Errore durante l'arresto della rete: {e}\n")


if __name__ == '__main__':
    setLogLevel('info')
    topology()
