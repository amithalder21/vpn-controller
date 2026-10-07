# Test OpenVPN server (stands in for a remote VPN you'd normally connect to)
FROM alpine:3.22
RUN apk add --no-cache openvpn iptables
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
