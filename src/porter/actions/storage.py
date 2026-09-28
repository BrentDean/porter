from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import PurePath

from porter.actions.command import CommandExecutionError, CommandRunner
from porter.core.models import RequestContext
from porter.intents.handlers import IntentHandler
from porter.intents.models import IntentResult, RecognizedIntent

_LSBLK_ARGV = (
    "/usr/bin/lsblk",
    "--json",
    "--bytes",
    "--output",
    "NAME,PATH,LABEL,SIZE,FSTYPE,TYPE,MOUNTPOINTS,UUID,RM",
)
_DF_ARGV = (
    "/usr/bin/df",
    "--block-size=1",
    "--output=source,fstype,size,used,avail,pcent,target",
)
_DISK_PRESSURE_THRESHOLD = 80


class StorageInventoryError(RuntimeError):
    """Read-only host storage inventory could not be collected."""


@dataclass(frozen=True, slots=True)
class BlockDevice:
    name: str
    path: str
    label: str | None
    size_bytes: int
    filesystem: str | None
    device_type: str
    mount_points: tuple[str, ...]
    uuid: str | None
    removable: bool
    depth: int
    has_children: bool

    @property
    def display_label(self) -> str:
        if self.label:
            return self.label
        if "/" in self.mount_points:
            return "Root"
        if self.mount_points:
            name = PurePath(self.mount_points[0]).name
            if name:
                return name
        return self.name


@dataclass(frozen=True, slots=True)
class FilesystemUsage:
    source: str
    filesystem: str
    size_bytes: int
    used_bytes: int
    available_bytes: int
    used_percent: int
    mount_point: str


class StorageInventory:
    """Collect read-only block-device and filesystem information."""

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self._runner = runner or CommandRunner()

    async def block_devices(self) -> tuple[BlockDevice, ...]:
        try:
            result = await self._runner.run(_LSBLK_ARGV)
            payload = json.loads(result.stdout)
        except (CommandExecutionError, json.JSONDecodeError) as exc:
            raise StorageInventoryError(f"could not read block devices: {exc}") from exc

        raw_devices = payload.get("blockdevices")
        if not isinstance(raw_devices, list):
            raise StorageInventoryError("lsblk output did not contain blockdevices")

        devices: list[BlockDevice] = []
        for raw_device in raw_devices:
            _append_block_device(devices, raw_device, depth=0)
        return tuple(devices)

    async def filesystem_usage(self) -> tuple[FilesystemUsage, ...]:
        try:
            result = await self._runner.run(_DF_ARGV)
        except CommandExecutionError as exc:
            raise StorageInventoryError(f"could not read filesystem usage: {exc}") from exc

        try:
            return _parse_df(result.stdout)
        except (TypeError, ValueError) as exc:
            raise StorageInventoryError(f"could not parse filesystem usage: {exc}") from exc


class MountedStorageHandler(IntentHandler):
    intent_name = "PorterStorageMounted"

    def __init__(self, inventory: StorageInventory) -> None:
        self._inventory = inventory

    async def handle(
        self,
        request: RequestContext,
        intent: RecognizedIntent,
    ) -> IntentResult:
        devices = await self._inventory.block_devices()
        usage = await self._inventory.filesystem_usage()
        usage_by_mount = {item.mount_point: item for item in usage}
        mounted = tuple(device for device in devices if device.mount_points)

        rows = []
        for device in mounted:
            mount_point = device.mount_points[0]
            filesystem = usage_by_mount.get(mount_point)
            rows.append(
                (
                    device.display_label,
                    device.path,
                    _human_bytes(device.size_bytes),
                    _human_bytes(filesystem.available_bytes) if filesystem else "-",
                    f"{filesystem.used_percent}%" if filesystem else "-",
                    mount_point,
                )
            )

        text = _format_table(
            ("Label", "Device", "Size", "Free", "Use", "Mount"),
            rows,
            empty="No mounted block-device filesystems found.",
        )
        return IntentResult(
            text=text,
            data={"labels": tuple(row[0] for row in rows), "count": len(rows)},
        )


class UnmountedStorageHandler(IntentHandler):
    intent_name = "PorterStorageUnmounted"

    def __init__(self, inventory: StorageInventory) -> None:
        self._inventory = inventory

    async def handle(
        self,
        request: RequestContext,
        intent: RecognizedIntent,
    ) -> IntentResult:
        devices = await self._inventory.block_devices()
        unmounted = tuple(
            device
            for device in devices
            if not device.mount_points
            and not device.has_children
            and device.size_bytes > 0
        )
        rows = [
            (
                device.display_label,
                device.path,
                device.device_type,
                _human_bytes(device.size_bytes),
                device.filesystem or "-",
                "yes" if device.removable else "no",
            )
            for device in unmounted
        ]
        text = _format_table(
            ("Label", "Device", "Type", "Size", "FS", "Removable"),
            rows,
            empty="No unmounted storage devices found.",
        )
        return IntentResult(
            text=text,
            data={"labels": tuple(row[0] for row in rows), "count": len(rows)},
        )


class StorageLayoutHandler(IntentHandler):
    intent_name = "PorterStorageLayout"

    def __init__(self, inventory: StorageInventory) -> None:
        self._inventory = inventory

    async def handle(
        self,
        request: RequestContext,
        intent: RecognizedIntent,
    ) -> IntentResult:
        devices = await self._inventory.block_devices()
        rows = [
            (
                device.display_label,
                f"{'  ' * device.depth}{device.name}",
                device.device_type,
                _human_bytes(device.size_bytes),
                device.filesystem or "-",
                ", ".join(device.mount_points) or "-",
            )
            for device in devices
            if device.size_bytes > 0
        ]
        text = _format_table(
            ("Label", "Device", "Type", "Size", "FS", "Mount"),
            rows,
            empty="No block devices found.",
        )
        return IntentResult(text=text, data={"count": len(rows)})


class DiskUsageHandler(IntentHandler):
    intent_name = "PorterDiskUsage"

    def __init__(self, inventory: StorageInventory) -> None:
        self._inventory = inventory

    async def handle(
        self,
        request: RequestContext,
        intent: RecognizedIntent,
    ) -> IntentResult:
        usage = _physical_filesystems(await self._inventory.filesystem_usage())
        rows = [
            (
                _label_from_mount(item.mount_point),
                item.filesystem,
                _human_bytes(item.size_bytes),
                _human_bytes(item.used_bytes),
                _human_bytes(item.available_bytes),
                f"{item.used_percent}%",
                item.mount_point,
            )
            for item in usage
        ]
        text = _format_table(
            ("Label", "FS", "Size", "Used", "Free", "Use", "Mount"),
            rows,
            empty="No physical filesystems found.",
        )
        return IntentResult(text=text, data={"count": len(rows)})


class DiskPressureHandler(IntentHandler):
    intent_name = "PorterDiskPressure"

    def __init__(self, inventory: StorageInventory) -> None:
        self._inventory = inventory

    async def handle(
        self,
        request: RequestContext,
        intent: RecognizedIntent,
    ) -> IntentResult:
        usage = _physical_filesystems(await self._inventory.filesystem_usage())
        pressured = tuple(
            item for item in usage if item.used_percent >= _DISK_PRESSURE_THRESHOLD
        )
        rows = [
            (
                _label_from_mount(item.mount_point),
                f"{item.used_percent}%",
                _pressure_status(item.used_percent),
                _human_bytes(item.available_bytes),
                item.mount_point,
            )
            for item in pressured
        ]
        text = _format_table(
            ("Label", "Use", "Status", "Free", "Mount"),
            rows,
            empty=(
                "No mounted physical filesystems are at or above "
                f"{_DISK_PRESSURE_THRESHOLD}% usage."
            ),
        )
        return IntentResult(
            text=text,
            data={"count": len(rows), "threshold_percent": _DISK_PRESSURE_THRESHOLD},
        )


def _append_block_device(
    devices: list[BlockDevice],
    raw: object,
    *,
    depth: int,
) -> None:
    if not isinstance(raw, dict):
        raise StorageInventoryError("lsblk device entry was not an object")

    children = raw.get("children")
    has_children = isinstance(children, list) and bool(children)
    mount_points_raw = raw.get("mountpoints")
    mount_points = tuple(
        str(value)
        for value in mount_points_raw or ()
        if value not in (None, "")
    )

    try:
        device = BlockDevice(
            name=str(raw["name"]),
            path=str(raw.get("path") or f"/dev/{raw['name']}"),
            label=_optional_text(raw.get("label")),
            size_bytes=int(raw.get("size") or 0),
            filesystem=_optional_text(raw.get("fstype")),
            device_type=str(raw.get("type") or "unknown"),
            mount_points=mount_points,
            uuid=_optional_text(raw.get("uuid")),
            removable=bool(int(raw.get("rm") or 0)),
            depth=depth,
            has_children=has_children,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise StorageInventoryError(f"invalid lsblk device entry: {exc}") from exc

    devices.append(device)
    if isinstance(children, list):
        for child in children:
            _append_block_device(devices, child, depth=depth + 1)


def _parse_df(output: str) -> tuple[FilesystemUsage, ...]:
    lines = output.splitlines()
    if not lines:
        return ()

    usage: list[FilesystemUsage] = []
    for line in lines[1:]:
        if not line.strip():
            continue
        fields = line.split(None, 6)
        if len(fields) != 7:
            raise ValueError(f"unexpected df row: {line!r}")
        source, filesystem, size, used, available, percent, mount_point = fields
        usage.append(
            FilesystemUsage(
                source=source,
                filesystem=filesystem,
                size_bytes=int(size),
                used_bytes=int(used),
                available_bytes=int(available),
                used_percent=int(percent.removesuffix("%")),
                mount_point=mount_point,
            )
        )
    return tuple(usage)


def _physical_filesystems(
    usage: tuple[FilesystemUsage, ...],
) -> tuple[FilesystemUsage, ...]:
    return tuple(item for item in usage if item.source.startswith("/dev/"))


def _optional_text(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _label_from_mount(mount_point: str) -> str:
    if mount_point == "/":
        return "Root"
    return PurePath(mount_point).name or mount_point


def _pressure_status(percent: int) -> str:
    if percent >= 95:
        return "Critical"
    if percent >= 90:
        return "High"
    return "Watch"


def _human_bytes(value: int) -> str:
    amount = float(value)
    units = ("B", "K", "M", "G", "T", "P")
    for unit in units:
        if abs(amount) < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(amount)}B"
            text = f"{amount:.1f}".rstrip("0").rstrip(".")
            return f"{text}{unit}"
        amount /= 1024
    raise AssertionError("unreachable")


def _format_table(
    headers: tuple[str, ...],
    rows: list[tuple[str, ...]],
    *,
    empty: str,
) -> str:
    if not rows:
        return empty

    widths = [len(header) for header in headers]
    for row in rows:
        if len(row) != len(headers):
            raise ValueError("table row width does not match headers")
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    def render(row: tuple[str, ...]) -> str:
        return "  ".join(value.ljust(widths[index]) for index, value in enumerate(row)).rstrip()

    separator = "  ".join("─" * width for width in widths)
    return "\n".join((render(headers), separator, *(render(row) for row in rows)))
