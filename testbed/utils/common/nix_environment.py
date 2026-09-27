"""Shared Nix environment for checks, builds and switch consoles."""

# A nested login shell may reset PATH while inheriting Nix's sourced guard.
# Restore profile paths explicitly instead of depending on sourcing a second time.
NIX_ENV = ('export PATH="$HOME/.nix-profile/bin:$HOME/.local/state/nix/profiles/profile/bin:'
           '/nix/var/nix/profiles/default/bin:$PATH"; ')

NIX_PING = NIX_ENV + 'nix --extra-experimental-features nix-command store ping --store daemon'

# Start only an existing installation. ONL may not expose a working systemd API.
NIX_START = '''if test -d /run/systemd/system && command -v systemctl >/dev/null; then
  sudo -n systemctl start nix-daemon.socket || sudo -n systemctl start nix-daemon.service
elif test -x /etc/init.d/nix-daemon; then
  sudo -n /etc/init.d/nix-daemon start
else
  sudo -n sh -c 'test -x /nix/var/nix/profiles/default/bin/nix-daemon &&
    (flock -x 9
     if pgrep -x nix-daemon >/dev/null; then exit 0; fi
     nohup /nix/var/nix/profiles/default/bin/nix-daemon --daemon </dev/null >>/var/log/nix-daemon.log 2>&1 9>&- &
    ) 9>/run/revisitps-nix-daemon.lock'
fi'''
