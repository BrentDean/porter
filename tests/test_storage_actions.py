from __future__ import annotations

import json

import pytest

from porter.actions.command import CommandExecutionError, CommandResult
from porter.actions.storage import (
    DiskPressureHandler,
    DiskUsageHandler,
    MountedStorageHandler,
    StorageInventory,
    StorageInventoryError,
    StorageLayoutHandler,
    UnmountedStorageHandler,
)
from porter.intents import DeterministicIntentExecutor, IntentHandlerRegistry
from tests.fakes import make_request

_LSBLK_OUTPUT = json.dumps(
    {
        "blockdevices": [
            {
                "name": "nvme1n1",
                "path": "/dev/nvme1n1",
                "label": None,
                "size": 2_000_000_000_000,
                "fstype": None,
                "type": "disk",
                "mountpoints": [None],
                "uuid": None,
                "rm": 0,
                "children": [
                    {
                        "name": "nvme1n1p1",
                        "path": "/dev/nvme1n1p1",
                        "label": None,
                        "size": 500_000_000_000,
                        "fstype": "crypto_LUKS",
                        "type": "part",
                        "mountpoints": [None],
                        "uuid": "luks-uuid",
                        "rm": 0,
                        "children": [
                            {
                                "name": "luksroot",
                                "path": "/dev/mapper/luksroot",
                                "label": None,
                                "size": 500_000_000_000,
                                "fstype": "ext4",
                                "type": "crypt",
                                "mountpoints": ["/"],
                                "uuid": "root-uuid",
                                "rm": 0,
                            }
                        ],
                    },
                    {
                        "name": "nvme1n1p2",
                        "path": "/dev/nvme1n1p2",
                        "label": None,
                        "size": 1_300_000_000_000,
                        "fstype": None,
                        "type": "part",
                        "mountpoints": [None],
                        "uuid": None,
                        "rm": 0,
                        "children": [
                            {
                                "name": "veracrypt1",
                                "path": "/dev/mapper/veracrypt1",
                                "label": "sandbox",
                                "size": 1_300_000_000_000,
                                "fstype": "ntfs",
                                "type": "dm",
                                "mountpoints": ["/mnt/sandbox"],
                                "uuid": "sandbox-uuid",
                                "rm": 0,
                            }
                        ],
                    },
                ],
            },
            {
                "name": "sdc",
                "path": "/dev/sdc",
                "label": None,
                "size": 14_000_000_000_000,
                "fstype": None,
                "type": "disk",
                "mountpoints": [None],
                "uuid": None,
                "rm": 0,
                "children": [
                    {
                        "name": "veracrypt3",
                        "path": "/dev/mapper/veracrypt3",
                        "label": "Mach2A",
                        "size": 14_000_000_000_000,
                        "fstype": "ntfs",
                        "type": "dm",
                        "mountpoints": ["/mnt/Mach2A"],
                        "uuid": "mach2a-uuid",
                        "rm": 0,
                    }
                ],
            },
            {
                "name": "sdd",
                "path": "/dev/sdd",
                "label": "Archive",
                "size": 4_000_000_000_000,
                "fstype": "ext4",
                "type": "disk",
                "mountpoints": [None],
                "uuid": "archive-uuid",
                "rm": 1,
            },
            {
                "name": "sde",
                "path": "/dev/sde",
                "label": None,
                "size": 0,
                "fstype": None,
                "type": "disk",
                "mountpoints": [None],
                "uuid": None,
                "rm": 1,
            },
        ]
    }
)

_DF_OUTPUT = """Filesystem Type 1B-blocks Used Available Use% Mounted on
/dev/mapper/luksroot ext4 500000000000 325000000000 175000000000 65% /
/dev/mapper/veracrypt1 fuseblk 1300000000000 1092000000000 208000000000 84% /mnt/sandbox
/dev/mapper/veracrypt3 fuseblk 14000000000000 13160000000000 840000000000 94% /mnt/Mach2A
tmpfs tmpfs 1000000000 1000000 999000000 1% /run
"""


class FakeCommandRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    async def run(
        self,
        argv: tuple[str, ...],
        *,
        check: bool = True,
    ) -> CommandResult:
        self.calls.append(argv)
        if argv[0] == "/usr/bin/lsblk":
            stdout = _LSBLK_OUTPUT
        elif argv[0] == "/usr/bin/df":
            stdout = _DF_OUTPUT
        else:
            raise AssertionError(f"unexpected command: {argv}")
        return CommandResult(argv=argv, returncode=0, stdout=stdout, stderr="")


@pytest.mark.asyncio
async def test_storage_inventory_uses_machine_readable_commands() -> None:
    runner = FakeCommandRunner()
    inventory = StorageInventory(runner)  # type: ignore[arg-type]

    devices = await inventory.block_devices()
    usage = await inventory.filesystem_usage()

    assert runner.calls[0][:3] == ("/usr/bin/lsblk", "--json", "--bytes")
    assert runner.calls[1][0] == "/usr/bin/df"
    assert any(device.display_label == "Mach2A" for device in devices)
    assert any(item.mount_point == "/mnt/Mach2A" for item in usage)


@pytest.mark.asyncio
async def test_mounted_storage_pretty_prints_labels_and_usage() -> None:
    inventory = StorageInventory(FakeCommandRunner())  # type: ignore[arg-type]
    handler = MountedStorageHandler(inventory)

    result = await handler.handle(
        make_request(content="which drives are mounted"),
        intent=None,  # type: ignore[arg-type]
    )

    assert "Label" in result.text
    assert "Device" in result.text
    assert "Free" in result.text
    assert "Root" in result.text
    assert "sandbox" in result.text
    assert "Mach2A" in result.text
    assert "/mnt/Mach2A" in result.text


@pytest.mark.asyncio
async def test_unmounted_storage_lists_leaf_devices_and_skips_empty_readers() -> None:
    inventory = StorageInventory(FakeCommandRunner())  # type: ignore[arg-type]
    handler = UnmountedStorageHandler(inventory)

    result = await handler.handle(
        make_request(content="which drives are unmounted"),
        intent=None,  # type: ignore[arg-type]
    )

    assert "Archive" in result.text
    assert "/dev/sdd" in result.text
    assert "/dev/sde" not in result.text
    assert "/dev/nvme1n1" not in result.text


@pytest.mark.asyncio
async def test_disk_usage_filters_virtual_filesystems() -> None:
    inventory = StorageInventory(FakeCommandRunner())  # type: ignore[arg-type]
    handler = DiskUsageHandler(inventory)

    result = await handler.handle(
        make_request(content="disk usage"),
        intent=None,  # type: ignore[arg-type]
    )

    assert "Root" in result.text
    assert "sandbox" in result.text
    assert "Mach2A" in result.text
    assert "/run" not in result.text
    assert "94%" in result.text


@pytest.mark.asyncio
async def test_disk_pressure_reports_only_filesystems_at_or_above_80_percent() -> None:
    inventory = StorageInventory(FakeCommandRunner())  # type: ignore[arg-type]
    handler = DiskPressureHandler(inventory)

    result = await handler.handle(
        make_request(content="which drives are almost full"),
        intent=None,  # type: ignore[arg-type]
    )

    assert "sandbox" in result.text
    assert "Watch" in result.text
    assert "Mach2A" in result.text
    assert "High" in result.text
    assert "Root" not in result.text


@pytest.mark.asyncio
async def test_storage_layout_preserves_device_hierarchy() -> None:
    inventory = StorageInventory(FakeCommandRunner())  # type: ignore[arg-type]
    handler = StorageLayoutHandler(inventory)

    result = await handler.handle(
        make_request(content="show my drives"),
        intent=None,  # type: ignore[arg-type]
    )

    assert "nvme1n1" in result.text
    assert "  nvme1n1p1" in result.text
    assert "    luksroot" in result.text
    assert "Mach2A" in result.text


@pytest.mark.asyncio
async def test_storage_phrases_are_deterministic() -> None:
    inventory = StorageInventory(FakeCommandRunner())  # type: ignore[arg-type]
    registry = IntentHandlerRegistry(
        (
            MountedStorageHandler(inventory),
            UnmountedStorageHandler(inventory),
            StorageLayoutHandler(inventory),
            DiskUsageHandler(inventory),
            DiskPressureHandler(inventory),
        )
    )
    executor = DeterministicIntentExecutor(registry)

    mounted = await executor.execute(make_request(content="which drives are mounted"))
    usage = await executor.execute(make_request(content="disk usage"))
    pressure = await executor.execute(
        make_request(content="which drives are almost full")
    )

    assert mounted is not None and "Mach2A" in mounted.text
    assert usage is not None and "94%" in usage.text
    assert pressure is not None and "High" in pressure.text


@pytest.mark.asyncio
async def test_storage_inventory_wraps_command_failures() -> None:
    class FailingRunner:
        async def run(
            self,
            argv: tuple[str, ...],
            *,
            check: bool = True,
        ) -> CommandResult:
            raise CommandExecutionError("synthetic failure")

    inventory = StorageInventory(FailingRunner())  # type: ignore[arg-type]

    with pytest.raises(StorageInventoryError, match="could not read block devices"):
        await inventory.block_devices()
