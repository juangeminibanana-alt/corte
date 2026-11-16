#!/bin/bash
# COS startup; never print tokens, environment contents or Secret Manager payloads.
set -euo pipefail
set +x
umask 077

mountpoint_bin=$(command -v mountpoint)
docker_bin=$(command -v docker)
[[ "$mountpoint_bin" =~ ^/[A-Za-z0-9/_-]+$ ]] && [ -x "$mountpoint_bin" ] || exit 1
[[ "$docker_bin" =~ ^/[A-Za-z0-9/_-]+$ ]] && [ -x "$docker_bin" ] || exit 1

metadata() {
  curl --fail --silent --show-error --retry 3 --max-time 15 \
    -H 'Metadata-Flavor: Google' \
    "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"
}

device=/dev/disk/by-id/google-corte-data
for attempt in $(seq 1 60); do
  [ -b "$device" ] && break
  sleep 1
done
[ -b "$device" ] || { echo 'Corte data disk is not attached; refusing startup.' >&2; exit 1; }

# Only a new, signature-free disk may be formatted with an explicit first-boot opt-in.
# An unknown filesystem, I/O error or missing opt-in stops the deployment.
if filesystem=$(blkid -p -s TYPE -o value "$device"); then
  [ "$filesystem" = ext4 ] || { echo 'Unexpected data filesystem; refusing to alter it.' >&2; exit 1; }
else
  status=$?
  [ "$status" -eq 2 ] && [ "$(metadata corte-initialize-data-disk)" = true ] || {
    echo 'Data disk is not initialized. Explicit first-boot permission is required.' >&2; exit 1;
  }
  mkfs.ext4 -L corte-data "$device"
fi

mkdir -p /mnt/disks/corte
if ! mountpoint -q /mnt/disks/corte; then
  mount -t ext4 -o defaults,discard "$device" /mnt/disks/corte
fi
# Verify the mounted device, not merely that the mount path exists.
[ "$(findmnt -n -o UUID --target /mnt/disks/corte)" = "$(blkid -s UUID -o value "$device")" ] || {
  echo 'Wrong disk mounted; refusing startup.' >&2; exit 1;
}
mkdir -p /mnt/disks/corte/data
chown 10001:10001 /mnt/disks/corte/data
chmod 0700 /mnt/disks/corte/data

mkdir -p /run/corte/docker
chmod 0700 /run/corte /run/corte/docker
image=$(metadata corte-image)
[[ "$image" =~ ^[a-z0-9-]+-docker\.pkg\.dev/[a-z0-9-]+/corte/corte@sha256:[a-f0-9]{64}$ ]] || {
  echo 'An immutable Artifact Registry image is required.' >&2; exit 1;
}
registry=${image%%/*}
token_response=$(curl --fail --silent --show-error --retry 3 --max-time 15 -H 'Metadata-Flavor: Google' \
  http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token)
token=$(printf '%s' "$token_response" | sed -n 's/.*"access_token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
[ -n "$token" ] || { echo 'Unable to obtain VM identity.' >&2; exit 1; }
printf '%s' "$token" | docker --config /run/corte/docker login -u oauth2accesstoken --password-stdin "https://$registry" >/dev/null
unset token token_response
pulled=false
for attempt in $(seq 1 10); do
  if docker --config /run/corte/docker pull "$image"; then
    pulled=true
    break
  fi
  sleep 15
done
[ "$pulled" = true ] || { echo 'Image pull failed; check Artifact Registry IAM.' >&2; exit 1; }

# The same reviewed application image supplies Python; COS needs no gcloud/Python install.
docker --config /run/corte/docker run --rm --network host --user 0:0 --cap-drop ALL \
  --security-opt no-new-privileges --read-only --mount type=bind,src=/run/corte,dst=/run/corte \
  --entrypoint python "$image" -m cloud.google.bootstrap
rm -f /run/corte/docker/config.json
rmdir /run/corte/docker

systemctl stop corte.service 2>/dev/null || true
cat > /etc/systemd/system/corte.service <<EOF
[Unit]
Description=Corte private Google Cloud application
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target
RequiresMountsFor=/mnt/disks/corte
ConditionPathIsMountPoint=/mnt/disks/corte
StartLimitIntervalSec=0

[Service]
Type=simple
ExecStartPre=$mountpoint_bin -q /mnt/disks/corte
ExecStartPre=-$docker_bin rm -f corte
ExecStart=$docker_bin run --rm --name corte --cap-drop ALL --security-opt no-new-privileges --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m --env-file /run/corte/runtime.env --publish 8080:10000 --mount type=bind,src=/mnt/disks/corte/data,dst=/var/lib/corte --log-driver gcplogs --log-opt mode=non-blocking --log-opt max-buffer-size=4m $image
ExecStop=$docker_bin stop --time 40 corte
StandardOutput=journal+console
StandardError=journal+console
Restart=always
RestartSec=5
TimeoutStopSec=50

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now corte.service
if ! systemctl is-active --quiet corte.service; then
  systemctl status corte.service --no-pager -l || true
  journalctl -u corte.service --no-pager -n 20 || true
  exit 1
fi
echo 'Corte service active; verify gateway health, Hosting and authenticated access separately.'
