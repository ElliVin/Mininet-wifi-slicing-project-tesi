#!/bin/bash
set -e

IF=ap1-wlan1
IFB=ifb0
TOTAL="7mbit"      # banda massima totale “fisica” vista dall’AP (adatta a tuo scenario)
CAR_DEF="7mbit"    # al boot, tutta la banda ai CAR (nessuna ambulanza ancora)
PRIO_MIN="1kbit"    # classe ambulanza quasi spenta finché non serve

echo "[+] Pulizia..."
tc qdisc del dev "$IF" root 2>/dev/null || true
tc qdisc del dev "$IF" ingress 2>/dev/null || true
tc qdisc del dev "$IFB" root 2>/dev/null || true
ip link set "$IFB" down 2>/dev/null || true
ip link delete "$IFB" type ifb 2>/dev/null || true

echo "[+] Root HTB egress su $IF"
tc qdisc add dev "$IF" root handle 1: htb default 20
tc class add dev "$IF" parent 1: classid 1:1 htb rate "$TOTAL" ceil "$TOTAL"

# Classe PRIO (ambulanza) – inizialmente quasi spenta
tc class add dev "$IF" parent 1:1 classid 1:10 htb rate "$PRIO_MIN" ceil "$TOTAL" prio 0
tc qdisc add dev "$IF" parent 1:10 handle 10: fq_codel

# Classe CAR (tutti i veicoli “normali”) – inizialmente tutta la banda
tc class add dev "$IF" parent 1:1 classid 1:20 htb rate "$CAR_DEF" ceil "$TOTAL" prio 1
tc qdisc add dev "$IF" parent 1:20 handle 20: fq_codel

echo "[+] Ingress mirroring su IFB ($IFB)"
modprobe ifb
ip link add "$IFB" type ifb
ip link set "$IFB" up

tc qdisc add dev "$IF" ingress
tc filter add dev "$IF" parent ffff: protocol ip u32 match u32 0 0 \
  action mirred egress redirect dev "$IFB"

# Ingress HTB su IFB
tc qdisc add dev "$IFB" root handle 2: htb default 20
tc class add dev "$IFB" parent 2: classid 2:1 htb rate "$TOTAL" ceil "$TOTAL"

# PRIO ingress (ambulanza)
tc class add dev "$IFB" parent 2:1 classid 2:10 htb rate "$PRIO_MIN" ceil "$TOTAL" prio 0
tc qdisc add dev "$IFB" parent 2:10 handle 110: fq_codel

# CAR ingress
tc class add dev "$IFB" parent 2:1 classid 2:20 htb rate "$CAR_DEF" ceil "$TOTAL" prio 1
tc qdisc add dev "$IFB" parent 2:20 handle 120: fq_codel

echo "[✓] Bootstrap completato (egress + ingress con IFB)"

