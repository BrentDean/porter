# Desktop notifications

Porter presents due reminders through the local desktop without making the tray application a second reminder worker.

## Delivery ownership

`porter service` remains the only reminder delivery worker. It owns due-reminder claims, retry state, and the transition to `delivered`.

The graphical tray is a presentation endpoint only. When it is running, it listens on a user-private Unix socket under:

```text
$XDG_RUNTIME_DIR/porter/reminders.sock
```

The socket's parent directory is mode `0700`. The service sends only the reminder ID, principal ID, and reminder text required to render the popup.

## Tray-first delivery

For each claimed reminder:

1. the service tries the Porter tray socket;
2. the tray validates the payload and queues a Porter-owned popup;
3. the tray acknowledges acceptance;
4. the service finalizes the reminder as delivered.

The popup is positioned relative to the Porter system-tray icon when its geometry is available and exposes **Snooze 10 min**, **Open Porter**, and **Dismiss**. Timer notifications are labeled **Porter Timer**; ordinary reminders are labeled **Porter Reminder**. Some Linux system trays do not report icon geometry until the first icon activation; before that, Porter uses the bottom-right of the primary screen rather than the arbitrary cursor position. Later tray activations are cached as positioning hints.

Popup presentation is deferred to the next Qt event-loop turn after the socket callback, and the popup stays available for 30 seconds unless dismissed. The tray emits content-free `tray.notification.queued` and `tray.notification.show_requested` operational events to assist desktop-specific troubleshooting. Some Wayland compositors can override a top-level window's requested position.

Multiple reminders are queued by the tray instead of replacing one another.

## Timers

Timers are reminder records with a durable `kind=timer` and original duration in whole seconds. Existing reminder rows migrate to `kind=reminder` without losing their state. Timer creation, delivery claiming, retries, finalization, cancellation, and history use the original reminder service and one background delivery worker, not a second scheduler.

The tray renders scheduled timers under **Active timers**. A separate 1-second Qt timer updates only countdown labels; the existing 2-second snapshot poll remains responsible for observing SQLite state changes. Cards provide **Restart** (original duration from now) and **Cancel**. Recently delivered timers offer **Restart** and **Clear**. A resumed application uses the persisted due timestamp, not the elapsed time since the tray opened, so missed timers are delivered as overdue by the existing worker.

Reminder confirmation text shows seconds for second-level relative requests. The current service poll interval is one second; actual desktop presentation can vary slightly with scheduler and desktop-session latency. This is an ordinary wall-clock countdown, not a precision stopwatch.

## Fallback behavior

If the tray is not running, the socket is unavailable, or the tray rejects the request, the same reminder attempt falls back to the existing `notify-send` adapter.

A successful fallback still uses Porter's existing reminder finalization path. If both tray delivery and `notify-send` fail, the reminder returns to scheduled state with Porter's durable retry backoff.

The fallback preserves reminder delivery when the desktop tray has not started, crashes, or is intentionally disabled.

## Desktop-session autostart

The tray is a graphical desktop application and therefore uses XDG desktop autostart rather than a systemd user service.

Install autostart with:

```bash
porter tray install
```

Inspect or remove it with:

```bash
porter tray status
porter tray uninstall
```

The generated entry is stored at:

```text
$XDG_CONFIG_HOME/autostart/porter-tray.desktop
```

or `~/.config/autostart/porter-tray.desktop` when `XDG_CONFIG_HOME` is unset. It records the exact `porter` executable resolved during installation, so moving or recreating the virtual environment requires rerunning `porter tray install`.

## Local-only boundary

This feature does not expose a network listener. The IPC endpoint is a local Unix-domain socket inside the logged-in user's runtime directory.

The tray does not run inference, own reminder scheduling, replace SQLite, or create a second authoritative reminder state.
