#!/bin/sh

echo "Disabling reverse path filtering"
for i in /proc/sys/net/ipv4/conf/*/rp_filter
do
  echo 0 > $i
done

cd /router/
exec env XTABLES_LIBDIR=/usr/lib/xtables/ ./router.py
