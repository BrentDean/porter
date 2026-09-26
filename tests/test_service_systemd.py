from __future__ import annotations

import subprocess
from pathlib import Path

from porter.service.systemd import UserServiceManager, _quote_unit_arg


class FakeRunner:
    def __init__(self, *, active: bool = True) -> None:
        self.active = active
        self.calls: list[tuple[list[str], bool]] = []

    def __call__(
        self,
        args: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert capture_output is True
        assert text is True
        self.calls.append((args, check))
        returncode = 0
        if "is-active" in args and not self.active:
            returncode = 3
        return subprocess.CompletedProcess(
            args=args,
            returncode=returncode,
            stdout="",
            stderr="",
        )


def _manager(
    tmp_path: Path,
    runner: FakeRunner,
) -> UserServiceManager:
    return UserServiceManager(
        porter_executable=tmp_path / "venv path" / "bin" / "porter",
        systemctl_path=Path("/usr/bin/systemctl"),
        config_home=tmp_path / "config",
        runner=runner,
    )


def test_quote_unit_arg_escapes_spaces_quotes_and_backslashes() -> None:
    assert _quote_unit_arg('a b"c\\d') == '"a b\\\"c\\\\d"'


def test_render_unit_uses_exact_porter_executable(tmp_path: Path) -> None:
    manager = _manager(tmp_path, FakeRunner())

    unit = manager.render_unit()

    assert "Description=Porter local reminder delivery" in unit
    assert (
        f'ExecStart="{tmp_path}/venv path/bin/porter" service'
        in unit
    )
    assert "Restart=on-failure" in unit
    assert "WantedBy=default.target" in unit


def test_install_writes_user_unit_and_reloads_systemd(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    manager = _manager(tmp_path, runner)

    manager.install()

    assert manager.installed is True
    assert manager.unit_path.read_text(encoding="utf-8") == manager.render_unit()
    assert runner.calls == [
        (
            ["/usr/bin/systemctl", "--user", "daemon-reload"],
            True,
        )
    ]


def test_install_can_enable_and_start_service(tmp_path: Path) -> None:
    runner = FakeRunner()
    manager = _manager(tmp_path, runner)

    manager.install(enable_now=True)

    assert runner.calls == [
        (
            ["/usr/bin/systemctl", "--user", "daemon-reload"],
            True,
        ),
        (
            [
                "/usr/bin/systemctl",
                "--user",
                "enable",
                "--now",
                "porter-reminders.service",
            ],
            True,
        ),
    ]


def test_status_uses_systemd_user_manager(tmp_path: Path) -> None:
    runner = FakeRunner(active=False)
    manager = _manager(tmp_path, runner)

    assert manager.is_active() is False
    assert runner.calls == [
        (
            [
                "/usr/bin/systemctl",
                "--user",
                "is-active",
                "--quiet",
                "porter-reminders.service",
            ],
            False,
        )
    ]


def test_uninstall_stops_disables_removes_and_reloads(tmp_path: Path) -> None:
    runner = FakeRunner()
    manager = _manager(tmp_path, runner)
    manager.install()
    runner.calls.clear()

    manager.uninstall()

    assert manager.installed is False
    assert runner.calls == [
        (
            [
                "/usr/bin/systemctl",
                "--user",
                "disable",
                "--now",
                "porter-reminders.service",
            ],
            False,
        ),
        (
            ["/usr/bin/systemctl", "--user", "daemon-reload"],
            True,
        ),
    ]


def test_uninstall_is_noop_when_unit_is_absent(tmp_path: Path) -> None:
    runner = FakeRunner()
    manager = _manager(tmp_path, runner)

    manager.uninstall()

    assert runner.calls == []
