#!/usr/bin/env bash
# slo-deploy: download the stack bundle from S3, verify its SHA-256, run the Ansible playbook.
# Installed on the server by the first-boot script. Safe to run again:  sudo slo-deploy
set -euo pipefail
umask 022

log() { echo "[slo-deploy] $(date -u +%FT%TZ) $*"; }

if [ "$(id -u)" -ne 0 ]; then
  echo "Run it as root:  sudo slo-deploy" >&2
  exit 1
fi

# shellcheck source=/dev/null
. /etc/slo-cockpit/deploy.env
AWS=/snap/bin/aws
RELEASE_DIR="/opt/slo-cockpit/releases/$BUNDLE_SHA256"

# Only one deploy at a time.
exec 9>/run/slo-deploy.lock
flock 9

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

log "downloading s3://$BUNDLE_BUCKET/$BUNDLE_KEY"
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if "$AWS" s3 cp "s3://$BUNDLE_BUCKET/$BUNDLE_KEY" "$work/stack.zip" \
       --region "$AWS_REGION" --only-show-errors; then
    break
  fi
  if [ "$attempt" -eq 10 ]; then
    log "download failed 10 times - giving up"
    exit 1
  fi
  log "download failed (attempt $attempt/10), new permissions can take a minute; retrying in 15s"
  sleep 15
done

# Only run a bundle whose fingerprint matches the one Terraform planned.
actual=$(sha256sum "$work/stack.zip" | cut -d' ' -f1)
if [ "$actual" != "$BUNDLE_SHA256" ]; then
  log "REFUSING TO DEPLOY: checksum mismatch (expected $BUNDLE_SHA256, got $actual)"
  exit 1
fi
log "checksum OK"

rm -rf "$RELEASE_DIR"
mkdir -p "$RELEASE_DIR"
unzip -q "$work/stack.zip" -d "$RELEASE_DIR"
ln -sfn "$RELEASE_DIR" /opt/slo-cockpit/current

export ANSIBLE_CONFIG="$RELEASE_DIR/ansible/ansible.cfg"
PLAYBOOK=(ansible-playbook "$RELEASE_DIR/ansible/site.yml"
          -e "@/etc/slo-cockpit/vars.json" -e "bundle_dir=$RELEASE_DIR")

# A broken bundle (missing role, YAML typo) fails the same way every time, so check it once
# and stop with a clear message. Neither a retry nor "sudo slo-deploy" can fix it.
if ! "${PLAYBOOK[@]}" --syntax-check; then
  log "deploy FAILED: the bundle itself is broken (see the error above)."
  log "Fix the file on your computer, then run 'terraform apply' to build a new server."
  exit 1
fi

# Retries are for passing trouble only: apt locks, a slow network, a registry hiccup.
for attempt in 1 2 3; do
  log "running Ansible (attempt $attempt/3)"
  if "${PLAYBOOK[@]}"; then
    log "deploy finished - the stack is up"
    exit 0
  fi
  sleep 20
done
log "deploy FAILED - read the Ansible output above"
exit 1
