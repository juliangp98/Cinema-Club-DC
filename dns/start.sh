#!/bin/sh
# Start the caching resolver: the router to ask comes from DNS_UPSTREAM
# (docker-compose.yml). A config that doesn't check out stops here, loudly.
set -e
sed "s/@UPSTREAM@/${DNS_UPSTREAM:-192.168.0.1}/" /etc/unbound/unbound.conf.in > /etc/unbound/unbound.conf
unbound-checkconf /etc/unbound/unbound.conf
echo "dns: caching lookups, asking ${DNS_UPSTREAM:-192.168.0.1}"
exec unbound -d -c /etc/unbound/unbound.conf
