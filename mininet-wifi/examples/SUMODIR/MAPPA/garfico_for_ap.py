import os
import re
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timedelta

# === CONFIGURAZIONE ===
# Cartella di questo script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Root del progetto: salgo di 3 livelli da MAPPA → SUMODIR → examples → mininet-wifi
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", "..", ".."))

LOG_DIR = os.path.join(PROJECT_ROOT, "LOG_STAZIONI")
#LOG_DIR = "/home/eventura/Progetti/mininet-wifi/mininet-wifi/LOG_STAZIONI"
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "grafici_output")

fmt = "%H:%M:%S"

def estrai_blocchi_da_file(percorso_file):
    """Estrae tutti i blocchi di connessione con orari e throughput da un file di log."""
    blocchi = []
    with open(percorso_file, 'r') as file:
        contenuto = file.read()

    # Divide il file in blocchi delimitati da "ORARIO D'INIZIO"
    sezioni = contenuto.split("ORARIO DI INIZIO:")
    for sezione in sezioni[1:]:
        linee = sezione.strip().splitlines()
        if not linee:
            continue

        try:
            orario_inizio = datetime.strptime(linee[0].strip(), fmt)
        except Exception:
            continue

        valori = []
        for line in linee:
            if "Mbits/sec" in line or "Kbits/sec" in line:
                parti = line.split()
                try:
                    if "Mbits/sec" in parti:
                        index = parti.index("Mbits/sec")
                        valore = float(parti[index - 1])
                    elif "Kbits/sec" in parti:
                        index = parti.index("Kbits/sec")
                        valore = float(parti[index - 1]) / 1024
                    else:
                        continue
                    valori.append(valore)
                    valori.append(valore)  # ogni valore dura 2 secondi
                except (ValueError, IndexError):
                    continue

        # cerca orario di fine
        match_fine = re.search(r"ORARIO DI FINE\s*:\s*([\d:]+)", sezione)
        if match_fine:
            orario_fine = datetime.strptime(match_fine.group(1), fmt)
        else:
            orario_fine = orario_inizio + timedelta(seconds=2 * len(valori))

        blocchi.append({
            "inizio": orario_inizio,
            "fine": orario_fine,
            "valori": valori
        })
    return blocchi


# === CICLO SU TUTTI GLI AP ===
for n in range(1, 11):  # ap1 → ap10
    AP_TARGET = f"ap{n}"
    print(f"\n===== ANALISI {AP_TARGET} =====")

    # Cerca i file relativi a questo AP
    files_ap = [f for f in os.listdir(LOG_DIR)
                if AP_TARGET in f and (f.endswith(".log") or f.endswith(".txt"))]

    if not files_ap:
        print(f"Nessun file trovato per {AP_TARGET}")
        continue

    print(f"Trovati {len(files_ap)} file per {AP_TARGET}: {', '.join(files_ap)}")

    # --- Lettura e unione blocchi ---
    tutti_blocchi = []
    for file in files_ap:
        percorso = os.path.join(LOG_DIR, file)
        stazione = file.split("_")[0]
        blocchi = estrai_blocchi_da_file(percorso)
        for b in blocchi:
            b["stazione"] = stazione
            tutti_blocchi.append(b)

    if not tutti_blocchi:
        print("Nessun dato valido trovato.")
        continue

    ora_min = min(b["inizio"] for b in tutti_blocchi)
    ora_max = max(b["fine"] for b in tutti_blocchi)
    durata_tot = int((ora_max - ora_min).total_seconds())

    print(f"Intervallo totale: {ora_min.strftime(fmt)} - {ora_max.strftime(fmt)} ({durata_tot} sec)")

    # --- Costruzione serie temporali ---
    serie = {}
    tempo = list(range(durata_tot + 1))

    for b in tutti_blocchi:
        s = b["stazione"]
        if s not in serie:
            serie[s] = [0] * (durata_tot + 1)
        offset_inizio = int((b["inizio"] - ora_min).total_seconds())
        for i, val in enumerate(b["valori"]):
            if offset_inizio + i < len(serie[s]):
                serie[s][offset_inizio + i] = val

    # --- Calcolo media ---
    throughput_media = []
    for i in range(durata_tot + 1):
        valori = [serie[s][i] for s in serie]
        throughput_media.append(sum(valori) / len(serie))

    media_media = np.mean(throughput_media)
    std_media = np.std(throughput_media)

    print(f"Throughput medio complessivo: {media_media:.2f} Mbits/sec")
    print(f"Deviazione standard: {std_media:.2f} Mbits/sec")

    # --- Grafico ottimizzato per grandi quantità di dati (senza media) ---
    DOWNSAMPLE = 5   # mantiene 1 punto ogni 5
    SMOOTH_WINDOW = 5  # media mobile per linee più morbide

    plt.figure(figsize=(16, 8), dpi=130)
    plt.title(f"Andamento del Throughput nel Tempo - {AP_TARGET}", fontsize=14)
    plt.xlabel("Tempo (secondi)",fontsize=14)
    plt.ylabel("Throughput (Mbits/sec)",fontsize=14)

    for s in serie:
        # Downsampling
        y = np.array(serie[s])[::DOWNSAMPLE]
        x = np.array(tempo)[::DOWNSAMPLE]

        # Smoothing (media mobile)
        if len(y) >= SMOOTH_WINDOW:
            kernel = np.ones(SMOOTH_WINDOW) / SMOOTH_WINDOW
            y_smooth = np.convolve(y, kernel, mode='same')
        else:
            y_smooth = y

        plt.plot(x, y_smooth, linewidth=1.0, label=s, alpha=0.9)

    plt.grid(True, linestyle=":", linewidth=0.7, alpha=0.7)
    plt.legend(fontsize=14)
    plt.tight_layout()

    # --- SALVATAGGIO SICURO DEL GRAFICO ---
    #OUTPUT_DIR = "/home/eventura/Progetti/mininet-wifi/mininet-wifi/grafici_output"
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    nome_file_output = os.path.join(OUTPUT_DIR, f"grafico_{AP_TARGET}.png")

    print(f"[DEBUG] Salvataggio in: {nome_file_output}")  # per controllo

    plt.savefig(nome_file_output)
    plt.close()

    print(f"Grafico salvato: {nome_file_output}")



    