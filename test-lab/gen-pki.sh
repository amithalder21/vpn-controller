#!/bin/sh
# Builds a separate CA + server cert + client cert for each test VPN,
# then writes an inline client .ovpn like a real provider would hand you.
set -e
cd /work
for name in a b; do
  d=pki/$name; mkdir -p $d; cd $d
  openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 365 \
    -keyout ca.key -out ca.crt -subj "/CN=POC VPN $name CA" 2>/dev/null
  for role in server client; do
    eku=$([ $role = server ] && echo serverAuth || echo clientAuth)
    openssl req -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes \
      -keyout $role.key -out $role.csr -subj "/CN=vpn-$name-$role" 2>/dev/null
    printf "extendedKeyUsage=%s\nkeyUsage=digitalSignature,keyAgreement\n" $eku > $role.ext
    openssl x509 -req -in $role.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 365 \
      -extfile $role.ext -out $role.crt 2>/dev/null
    rm $role.csr $role.ext
  done
  ip=$([ $name = a ] && echo 172.30.0.11 || echo 172.30.0.12)
  {
    printf "client\ndev tun\nproto udp\nremote %s 1194\nnobind\nremote-cert-tls server\n" $ip
    printf "tls-version-min 1.2\ndata-ciphers AES-256-GCM:AES-128-GCM\nverb 3\n"
    printf "<ca>\n%s\n</ca>\n<cert>\n%s\n</cert>\n<key>\n%s\n</key>\n" "$(cat ca.crt)" "$(cat client.crt)" "$(cat client.key)"
  } > ../../client-$name.ovpn
  cd /work
done
chmod 644 pki/*/*.key client-*.ovpn
echo "PKI ready"
