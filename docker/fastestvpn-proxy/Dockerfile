FROM alpine:3.20@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc

RUN apk add --no-cache \
    bash \
    ca-certificates \
    coreutils \
    grep \
    netcat-openbsd \
    openvpn \
    sed \
    tinyproxy

COPY docker/fastestvpn-proxy/start.sh /usr/local/bin/fastestvpn-proxy-start
COPY docker/fastestvpn-proxy/tinyproxy.conf.template /etc/tinyproxy/tinyproxy.conf.template

RUN chmod +x /usr/local/bin/fastestvpn-proxy-start && \
    mkdir -p /state /vpn/fastestvpn && \
    touch /tmp/openvpn.log /tmp/openvpn-status.log

ENTRYPOINT ["/usr/local/bin/fastestvpn-proxy-start"]
