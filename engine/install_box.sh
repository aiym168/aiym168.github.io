#!/usr/bin/env bash
# Idempotent installer for a server engine on a Simular box. Safe to re-run (also run at login/boot).
# Identity comes from ~/.engine.conf (not in the repo):
#   ENGINE_ID=B ENGINE_MINUTE=25            first server (default when the file is missing)
#   ENGINE_ID=C SITE_ENGINE=0 RADIO=1 STATION=1   second server: no site updates, runs its own station site + audio briefing
set -uo pipefail
U="${SUDO_USER:-$(id -un)}"; H="$(getent passwd "$U" | cut -d: -f6)"
E="$H/engine"
[ -r "$H/.engine.conf" ] && . "$H/.engine.conf"
EID="${ENGINE_ID:-B}"; eid="$(printf '%s' "$EID" | tr 'A-Z' 'a-z')"; MIN="${ENGINE_MINUTE:-25}"
chmod +x "$E/engine/engine_b.sh" "$E/engine/pipeline.sh" "$E/engine/resume_tick.sh" "$E/engine/radio_run.sh" 2>/dev/null || true
grep -qxF 'logs/' "$E/.git/info/exclude" 2>/dev/null || printf 'logs/\n.lock\n.tick\n' >> "$E/.git/info/exclude"

# 1) systemd timer (primary): hourly :$MIN Asia/Shanghai + 4 min after boot, catch-up after sleep
sudo -n tee /etc/systemd/system/engine-$eid.service >/dev/null <<UNIT
[Unit]
Description=aiym168 server engine $EID (self-updating site, takeover when others are stale)
Wants=network-online.target
After=network-online.target
[Service]
Type=oneshot
User=$U
Environment=HOME=$H
ExecStart=$E/engine/engine_b.sh
TimeoutStartSec=55min
Nice=5
UNIT
sudo -n tee /etc/systemd/system/engine-$eid.timer >/dev/null <<UNIT
[Unit]
Description=Run aiym168 server engine $EID hourly
[Timer]
OnCalendar=*-*-* *:$MIN:00 Asia/Shanghai
OnBootSec=4min
Persistent=true
AccuracySec=30s
[Install]
WantedBy=timers.target
UNIT
sudo -n tee /etc/systemd/system/engine-$eid-resume.service >/dev/null <<UNIT
[Unit]
Description=aiym168 server engine $EID wake detector
[Service]
Type=oneshot
User=$U
Environment=HOME=$H
ExecStart=$E/engine/resume_tick.sh
TimeoutStartSec=55min
UNIT
sudo -n tee /etc/systemd/system/engine-$eid-resume.timer >/dev/null <<UNIT
[Unit]
Description=Detect wake-up of the box every 5 min and run engine $EID after a sleep
[Timer]
OnCalendar=*:0/5
AccuracySec=20s
[Install]
WantedBy=timers.target
UNIT
TIMERS="engine-$eid.timer engine-$eid-resume.timer"
if [ "${SITE_ENGINE:-1}" = "0" ]; then
  sudo -n systemctl disable --now "engine-$eid.timer" "engine-$eid-resume.timer" >/dev/null 2>&1 || true
  TIMERS=""
fi
if [ "${RADIO:-0}" = "1" ]; then
  sudo -n tee /etc/systemd/system/radio.service >/dev/null <<UNIT
[Unit]
Description=aiym168 audio briefing (AI 羊毛电台)
Wants=network-online.target
After=network-online.target
[Service]
Type=oneshot
User=$U
Environment=HOME=$H
ExecStart=$E/engine/radio_run.sh
TimeoutStartSec=40min
Nice=10
UNIT
  sudo -n tee /etc/systemd/system/radio.timer >/dev/null <<'UNIT'
[Unit]
Description=AI 羊毛电台 morning + evening edition
[Timer]
OnCalendar=*-*-* 08,20:30:00 Asia/Shanghai
Persistent=true
AccuracySec=30s
[Install]
WantedBy=timers.target
UNIT
  TIMERS="$TIMERS radio.timer"
fi
if [ "${STATION:-0}" = "1" ] && [ -x "$H/station/install.sh" ]; then bash "$H/station/install.sh" || true; fi
sudo -n systemctl daemon-reload && { [ -z "$TIMERS" ] || sudo -n systemctl enable --now $TIMERS; }

# 2) cron (secondary, same minute; the lock file prevents double runs) + @reboot
if ! command -v crontab >/dev/null 2>&1; then
  sudo -n DEBIAN_FRONTEND=noninteractive apt-get install -y -qq cron >/dev/null 2>&1 || true
fi
if command -v crontab >/dev/null 2>&1; then
  sudo -n systemctl enable --now cron >/dev/null 2>&1 || true
  ( crontab -l 2>/dev/null | grep -v -E 'engine/engine_b.sh|engine/radio_run.sh|^CRON_TZ' ; \
    echo "CRON_TZ=Asia/Shanghai"; \
    [ "${SITE_ENGINE:-1}" = "1" ] && echo "$MIN * * * * $E/engine/engine_b.sh >/dev/null 2>&1"; \
    [ "${SITE_ENGINE:-1}" = "1" ] && echo "@reboot sleep 240 && $E/engine/engine_b.sh >/dev/null 2>&1"; \
    [ "${RADIO:-0}" = "1" ] && echo "33 8,20 * * * $E/engine/radio_run.sh >/dev/null 2>&1" ) | awk '!seen[$0]++' | crontab -
fi

# 3) self-reinstall at desktop login (home dir persists even if /etc is reset by an image upgrade)
mkdir -p "$H/.config/autostart" "$E/logs"
cat > "$H/.config/autostart/engine-b.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Server engine self-install
Exec=bash -c "sleep 30; bash $E/engine/install_box.sh >> $E/logs/install.log 2>&1"
X-GNOME-Autostart-enabled=true
NoDisplay=true
DESK
echo "[install] engine $EID at :$MIN radio=${RADIO:-0} done"; systemctl list-timers "engine-$eid.timer" radio.timer --no-pager | head -4; crontab -l 2>/dev/null | grep -E 'engine_b|radio|CRON_TZ' || true
