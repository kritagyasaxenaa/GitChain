#!/bin/sh
set -eu

mkdir -p /data
chown gitchain:gitchain /data
exec gosu gitchain "$@"
