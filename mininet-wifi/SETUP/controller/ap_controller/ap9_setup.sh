#!/bin/bash

echo "[+] Inizializzo HTB su ap9-wlan1 (egress)"

# Pulizia configurazioni precedenti

tc qdisc del dev ap9-wlan1 root 2>/dev/null
tc qdisc del dev ap9-wlan1 ingress 2>/dev/null
tc qdisc del dev ifb_ap9 root 2>/dev/null
ip link set ifb_ap9 down 2>/dev/null
ip link delete ifb_ap9 type ifb 2>/dev/null

# Parte 1: traffico in uscita da {IF}

tc qdisc add dev ap9-wlan1 root handle 1: htb default 30
tc class add dev ap9-wlan1 parent 1: classid 1:1 htb rate 7mbit ceil 7mbit

# DEFAULT slice
tc class add dev ap9-wlan1 parent 1:1 classid 1:30 htb rate 7mbit ceil 7mbit
tc qdisc add dev ap9-wlan1 parent 1:30 handle 30: pfifo limit 100

# Filter per traffico in uscita (server -> stazioni)

tc filter add dev ap9-wlan1 protocol ip parent 1:0 prio 1 u32 match ip dst 10.0.0.8 flowid 1:30
tc filter add dev ap9-wlan1 protocol ip parent 1:0 prio 1 u32 match ip dst 10.0.0.17 flowid 1:30

echo "[+] Configuro IFB per ingress shaping su ap9-wlan1"

# Parte 2: traffico in ingresso su ap9-wlan1

modprobe ifb
ip link add ifb_ap9 type ifb
ip link set ifb_ap9 up

# Redirige tutto l'ingresso di ap9-wlan1 su ifb_ap9

tc qdisc add dev ap9-wlan1 ingress
tc filter add dev ap9-wlan1 parent ffff: protocol ip u32 match u32 0 0 \
    action mirred egress redirect dev ifb_ap9

# Shaping su {IFB} (traffico da stazioni verso server)

tc qdisc add dev ifb_ap9 root handle 2: htb default 10
tc class add dev ifb_ap9 parent 2: classid 2:1 htb rate 7mbit ceil 7mbit

# Slice 2:20 unica per tutte le stazioni
tc class add dev ifb_ap9 parent 2:1 classid 2:20 htb rate 7mbit ceil 7mbit
tc qdisc add dev ifb_ap9 parent 2:20 handle 20: pfifo limit 100

tc filter add dev ifb_ap9 protocol ip parent 2:0 prio 1 u32 match ip src 10.0.0.8 flowid 2:20
tc filter add dev ifb_ap9 protocol ip parent 2:0 prio 1 u32 match ip src 10.0.0.17 flowid 2:20

echo "[✓] Configurazione completa (egress + ingress con IFB)"
