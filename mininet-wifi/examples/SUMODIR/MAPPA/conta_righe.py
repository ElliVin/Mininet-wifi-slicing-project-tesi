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


if __name__ == "__main__":
    file_input = input("Inserisci il percorso del file: ")
    max_count = conta_righe_uguali(file_input)
    print(max_count)
