FROM alpine:3.20

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
