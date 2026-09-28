# Local service management

Porter's reminder worker can run as a systemd user service. This keeps reminder delivery inside the logged-in user's desktop session rather than introducing a root-owned system daemon.

## Why a user service

The current reminder delivery adapter uses `notify-send`, which targets the user's desktop notification session. A system-wide root service would have the wrong ownership and session boundary.

The generated unit therefore lives under:

```text
~/.config/systemd/user/porter-reminders.service
```

or the equivalent `XDG_CONFIG_HOME` path.

## Install

From the same Python environment in which Porter is installed:

```bash
porter service install
```

This writes the unit and reloads the user systemd manager. It does not enable or start the service unless requested.

Install and start immediately:

```bash
porter service install --enable-now
```

The generated unit records the exact installed `porter` executable resolved during installation:

```text
ExecStart=/path/to/porter service
```

This avoids depending on the user service manager's PATH. If the Porter virtual environment is moved or recreated at another path, rerun `porter service install`.

## Status

```bash
porter service status
systemctl --user status porter-reminders.service | cat
```

The unit uses `Restart=on-failure` with a five-second delay. Porter's existing SIGTERM/SIGINT handling still performs graceful shutdown and lets an in-flight reminder pass finish.

## Uninstall

```bash
porter service uninstall
```

Uninstall stops and disables the unit if present, removes the unit file, and reloads the user systemd manager. It does not delete Porter data, reminders, configuration, or backups.

## Runtime boundary

This service manages only the lightweight reminder worker.

It does not:

- expose Porter on the network;
- start or reconfigure Ollama;
- run the web interface;
- start Grafana or Prometheus;
- grant root privileges;
- change Porter's SQLite location.

The user-session model deliberately matches the local-only architecture. The tray application remains an interactive desktop process and is not converted into a systemd background service.

The tray instead uses XDG desktop-session autostart:

```bash
porter tray install
porter tray status
porter tray uninstall
```

This keeps graphical startup coupled to the desktop session while the reminder worker remains independently supervised by systemd.
