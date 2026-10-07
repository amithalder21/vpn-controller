#!/bin/sh
set -e
mkdir -p /dev/net
[ -c /dev/net/tun ] || mknod /dev/net/tun c 10 200
# NAT VPN clients out of this server, so they reach its private LAN (and the internet)
iptables -t nat -A POSTROUTING -s 10.8.0.0/24 -j MASQUERADE
exec openvpn --config /etc/openvpn/server.conf
