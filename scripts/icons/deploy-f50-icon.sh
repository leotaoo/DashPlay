#!/bin/sh
# Put a new box-settings icon into the receiver jar of an installed F50, from this computer.
#
# Usage: deploy-f50-icon.sh [--icon PATH] [--keep-stopped] [HOST]
#
# Uploads the icon and replace-f50-icon.py to /tmp on the box, stops dashplay,
# backs the jar up beside itself, swaps the icon, and checks the jar now holds
# exactly the sha256 of the local file. dashplay is started again on the way
# out, also when the swap fails; --keep-stopped leaves it down for inspection.
# A jar that already holds this icon is left alone, without touching dashplay.
# HOST defaults to root@100.96.0.1, or $F50_HOST when set.
#
# The upload goes over ssh/tar, not scp: the box's Dropbear has no sftp-server
# and today's scp clients refuse to fall back on their own.
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)
host=${F50_HOST:-root@100.96.0.1}
icon=$root/assets/icons/f50-settings.png
replacer=$root/scripts/icons/replace-f50-icon.py
keep_stopped=0

while [ $# -gt 0 ]; do
    case $1 in
        --icon) icon=$2; shift 2 ;;
        --keep-stopped) keep_stopped=1; shift ;;
        -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) echo "unknown option: $1" >&2; exit 2 ;;
        *) host=$1; shift ;;
    esac
done

[ -f "$icon" ] || { echo "no such icon: $icon" >&2; exit 1; }
[ -f "$replacer" ] || { echo "no such script: $replacer" >&2; exit 1; }

bytes=$(wc -c < "$icon" | tr -d ' ')
sha=$({ shasum -a 256 "$icon" 2>/dev/null || sha256sum "$icon"; } | cut -d' ' -f1)
echo "icon  $icon ($bytes bytes, sha256 $sha)"
echo "box   $host"

name=$(basename "$icon")
tar cf - -C "$(dirname "$icon")" "$name" -C "$root/scripts/icons" replace-f50-icon.py |
    ssh "$host" "cd /tmp && tar xf - && { [ '$name' = f50-settings.png ] || mv -f '$name' f50-settings.png; }"

if out=$(ssh "$host" "sh -s -- $sha $keep_stopped" 2>&1 <<'REMOTE'
set -eu
sha=$1
keep_stopped=$2
lib=/opt/dashplay/playport/server/build/install/server/lib

jar=$(ls "$lib"/server-*.jar 2>/dev/null | head -n 1) || true
[ -n "$jar" ] || { echo "no server jar under $lib" >&2; exit 1; }
echo "jar   $jar"

current=$(/usr/bin/python3 -c 'import hashlib, sys, zipfile; print(hashlib.sha256(zipfile.ZipFile(sys.argv[1]).read("f50-settings.png")).hexdigest())' "$jar")
if [ "$current" = "$sha" ]; then
    echo "already carries this icon; nothing to do"
    exit 0
fi

# Start again on every exit path, so a failed swap does not leave CarPlay down.
[ "$keep_stopped" = 1 ] || trap '/etc/init.d/dashplay start' EXIT

/etc/init.d/dashplay stop
backup=$jar.bak-$(date +%Y%m%d%H%M%S)
cp -p "$jar" "$backup"
echo "spare $backup"

/usr/bin/python3 /tmp/replace-f50-icon.py "$jar" /tmp/f50-settings.png

actual=$(/usr/bin/python3 -c 'import hashlib, sys, zipfile; print(hashlib.sha256(zipfile.ZipFile(sys.argv[1]).read("f50-settings.png")).hexdigest())' "$jar")
echo "sha   $actual"
[ "$actual" = "$sha" ] || { echo "the jar does not hold the new icon; copy $backup back" >&2; exit 1; }
REMOTE
); then
    printf '%s\n' "$out"
else
    status=$?
    printf '%s\n' "$out" >&2
    if [ "$keep_stopped" = 1 ]; then
        echo "failed; dashplay is still stopped" >&2
    else
        echo "failed; dashplay was started again with the old icon" >&2
    fi
    exit "$status"
fi

case $out in
    *"already carries"*) echo "done  nothing to change" ;;
    *)
        if [ "$keep_stopped" = 1 ]; then
            echo "done  dashplay left stopped; start it with: ssh $host /etc/init.d/dashplay start"
        else
            echo "done  dashplay restarted with the new icon"
        fi ;;
esac
