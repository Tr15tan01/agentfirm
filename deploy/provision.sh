#!/usr/bin/env bash
# One-time hardening of a fresh Ubuntu 24.04 Contabo VPS (run as root, once).
# Usage: DEPLOY_SSH_KEY="ssh-ed25519 AAAA… ci@agentfirm" ADMIN_SSH_KEY="ssh-ed25519 AAAA… you" bash provision.sh
set -euo pipefail
: "${DEPLOY_SSH_KEY:?public key used by CI}" "${ADMIN_SSH_KEY:?your public key}"
export DEBIAN_FRONTEND=noninteractive

apt-get update -y && apt-get upgrade -y
apt-get install -y ca-certificates curl gnupg ufw fail2ban unattended-upgrades apt-listchanges age jq

# Automatic security updates (no automatic reboots; reboot in a maintenance window).
dpkg-reconfigure -f noninteractive unattended-upgrades

# Docker Engine from Docker's repository.
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
# shellcheck source=/dev/null
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list
apt-get update -y && apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
cat > /etc/docker/daemon.json <<'JSON'
{ "log-driver": "json-file", "log-opts": { "max-size": "20m", "max-file": "5" }, "live-restore": true, "no-new-privileges": true }
JSON
systemctl restart docker

# Users: 'admin' for people (sudo), 'deploy' for CI (docker only, no sudo).
for u in admin deploy; do id "$u" >/dev/null 2>&1 || adduser --disabled-password --gecos "" "$u"; done
usermod -aG sudo admin && usermod -aG docker deploy
install -d -m 700 -o admin -g admin /home/admin/.ssh && echo "$ADMIN_SSH_KEY" > /home/admin/.ssh/authorized_keys
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh && echo "$DEPLOY_SSH_KEY" > /home/deploy/.ssh/authorized_keys
chown admin:admin /home/admin/.ssh/authorized_keys && chown deploy:deploy /home/deploy/.ssh/authorized_keys
chmod 600 /home/*/.ssh/authorized_keys
echo "admin ALL=(ALL) ALL" > /etc/sudoers.d/admin && chmod 440 /etc/sudoers.d/admin
install -d -m 750 -o deploy -g deploy /opt/agentfirm

# SSH: keys only, no root.
cat > /etc/ssh/sshd_config.d/10-hardening.conf <<'CONF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
MaxAuthTries 3
AllowUsers admin deploy
X11Forwarding no
CONF
systemctl reload ssh

# Firewall: SSH + web only. (Docker publishes 80/443 for Caddy; Grafana is bound to 127.0.0.1.)
ufw default deny incoming && ufw default allow outgoing
ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp && ufw allow 443/udp
ufw --force enable
systemctl enable --now fail2ban

# Swap (helps small VPS plans survive memory spikes) and kernel basics.
if ! swapon --show | grep -q /swapfile; then fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile && echo "/swapfile none swap sw 0 0" >> /etc/fstab; fi
cat > /etc/sysctl.d/90-agentfirm.conf <<'CONF'
vm.swappiness = 10
vm.overcommit_memory = 1
net.core.somaxconn = 1024
CONF
sysctl --system >/dev/null
timedatectl set-timezone UTC
echo "Provisioned. Next: copy deploy/ and .env.production to /opt/agentfirm (owner deploy), then run the first deploy."
