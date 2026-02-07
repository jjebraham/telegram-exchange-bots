#!/bin/bash
# Setup supervisor configurations for Kiani Exchange

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

echo "Setting up Supervisor for Kiani Exchange..."

# Copy all configs
sudo cp "$REPO_DIR/deploy/supervisor/"*.conf /etc/supervisor/conf.d/

# Create log files
for svc in api user_bot admin_bot miniapp adminpanel; do
    sudo touch "/var/log/kiani_${svc}.out.log" "/var/log/kiani_${svc}.err.log"
    sudo chown kianirad2020:kianirad2020 "/var/log/kiani_${svc}.out.log" "/var/log/kiani_${svc}.err.log"
done

# Update supervisor
sudo supervisorctl reread
sudo supervisorctl update

echo "Supervisor configured successfully!"
echo "Use './start_all.sh' to start all services."
