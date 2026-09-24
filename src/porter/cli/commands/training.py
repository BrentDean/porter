from __future__ import annotations

import argparse
from uuid import uuid4

from porter.app import PorterApplication
from porter.training import TrainingGroupHandling

_KNOWN_BEHAVIOR_NAMES = {
    "HassGetCurrentTime": "Time — current time",
    "HassGetCurrentDate": "Date — current date",
    "HassListAddItem": "Todo — add item",
    "HassListCompleteItem": "Todo — complete item",
    "HassListRemoveItem": "Todo — remove item",
    "PorterPlannerToday": "Planner — today",
    "PorterPlannerOverdue": "Planner — overdue",
    "PorterPlannerUpcoming": "Planner — upcoming",
    "PorterPlannerUnscheduled": "Planner — unscheduled",
    "PorterReminderCreate": "Reminder — create",
    "PorterReminderList": "Reminder — list",
    "PorterReminderCancel": "Reminder — cancel",
    "PorterPlexStart": "Plex — start",
    "PorterPlexStop": "Plex — stop",
    "PorterPlexRestart": "Plex — restart",
    "PorterStorageMounted": "Storage — mounted drives",
    "PorterStorageUnmounted": "Storage — unmounted drives",
    "PorterStorageLayout": "Storage — layout",
    "PorterDiskUsage": "Storage — disk usage",
    "PorterDiskPressure": "Storage — disks almost full",
}


def _run_training_session(application: PorterApplication) -> int:
    session_id = str(uuid4())
    captured = 0

    print("Training mode started.")
    print("Nothing entered here will execute.")
    print("Type END on its own line to finish.")
    print()

    while True:
        try:
            raw_text = input("training> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if raw_text.strip() == "END":
            break
        if not raw_text.strip():
            continue

        application.training_repository.add(session_id=session_id, raw_text=raw_text)
        captured += 1

    noun = "example" if captured == 1 else "examples"
    print(f"Training session saved: {captured} {noun}")
    return 0


def _print_training_review_summary(application: PorterApplication) -> None:
    summary = application.training_repository.review_summary()
    print(
        "Training corpus: "
        f"{summary.ungrouped} need grouping, "
        f"{summary.grouped} grouped into {summary.groups} groups, "
        f"{summary.promoted} promoted"
    )


def _parse_training_selection(text: str, available_ids: set[int]) -> tuple[int, ...]:
    selected: list[int] = []
    seen: set[int] = set()

    for token in text.split(","):
        part = token.strip()
        if not part:
            raise ValueError("empty example selection")

        if "-" in part:
            pieces = part.split("-", 1)
            if len(pieces) != 2 or not all(piece.strip().isdigit() for piece in pieces):
                raise ValueError("invalid example range")
            start, end = (int(piece.strip()) for piece in pieces)
            if start > end:
                raise ValueError("example ranges must be ascending")
            ids = range(start, end + 1)
        else:
            if not part.isdigit():
                raise ValueError("example selections must be ids or ranges")
            ids = (int(part),)

        for example_id in ids:
            if example_id not in available_ids:
                raise ValueError(f"example {example_id} is not available for grouping")
            if example_id not in seen:
                selected.append(example_id)
                seen.add(example_id)

    if not selected:
        raise ValueError("select at least one example")
    return tuple(selected)


def _read_training_handling() -> TrainingGroupHandling | str:
    print("How should Porter eventually handle this group?")
    print("  1. existing Porter behavior")
    print("  2. new deterministic behavior")
    print("  3. AI / inference")
    print("  4. discard")
    print("  s. skip")
    print("  q. quit")

    options = {
        "1": TrainingGroupHandling.EXISTING_BEHAVIOR,
        "2": TrainingGroupHandling.NEW_DETERMINISTIC,
        "3": TrainingGroupHandling.INFERENCE,
        "4": TrainingGroupHandling.DISCARD,
    }
    while True:
        try:
            response = input("Choice: ").strip().casefold()
        except (EOFError, KeyboardInterrupt):
            print()
            return "q"

        if response in options:
            return options[response]
        if response in {"s", "skip", "q", "quit"}:
            return response[0]
        print("Choose 1, 2, 3, 4, s, or q.")


def _available_known_behaviors(
    application: PorterApplication,
) -> tuple[tuple[str, str], ...]:
    supported = application.intent_handler_registry.supported_intents()
    intents = [(_KNOWN_BEHAVIOR_NAMES.get(intent, intent), intent) for intent in supported]
    return tuple(sorted(intents, key=lambda item: item[0].casefold()))


def _choose_known_behavior(application: PorterApplication) -> str | None:
    behaviors = _available_known_behaviors(application)
    print("Existing Porter behaviors")
    for index, (name, _) in enumerate(behaviors, start=1):
        print(f"  {index:>2}. {name}")

    while True:
        try:
            response = input("Behavior number (or q): ").strip().casefold()
        except (EOFError, KeyboardInterrupt):
            print()
            return None

        if response in {"q", "quit"}:
            return None
        if response.isdigit():
            index = int(response)
            if 1 <= index <= len(behaviors):
                return behaviors[index - 1][1]
        print(f"Choose a number from 1 to {len(behaviors)}, or q.")


def _print_training_groups(application: PorterApplication) -> None:
    groups = application.training_repository.list_groups()
    if not groups:
        print("No training groups yet.")
        return

    print("Training groups")
    print()
    for group in groups:
        if group.handling is TrainingGroupHandling.EXISTING_BEHAVIOR:
            target = f"existing: {group.target_label}"
        elif group.handling is TrainingGroupHandling.NEW_DETERMINISTIC:
            target = "new deterministic behavior; internal label pending"
        else:
            target = group.handling.value
        print(f"{group.id:>4}  {group.name}  ({group.example_count} examples)  [{target}]")


def _print_recognition_gaps(application: PorterApplication) -> None:
    gaps = application.recognition_gap_repository.list_common()
    if not gaps:
        return

    print()
    print("Recognition gaps")
    print()
    print("Count  AI  No AI  Request")
    for gap in gaps:
        print(
            f"{gap.occurrence_count:>5}  "
            f"{gap.ai_approved_count:>2}  "
            f"{gap.ai_declined_count:>5}  "
            f"{gap.latest_raw_text}"
        )


def _run_training_review(application: PorterApplication) -> int:
    if not application.training_repository.list_ungrouped():
        _print_training_review_summary(application)
        print("No training examples need grouping.")
        _print_recognition_gaps(application)
        return 0

    while True:
        examples = application.training_repository.list_ungrouped()
        if not examples:
            break

        print()
        _print_training_review_summary(application)
        print()
        print("Examples needing grouping")
        print()
        for example in examples:
            print(f"{example.id:>4}  {example.raw_text}")

        try:
            selection = input(
                "\nSelect IDs to group (for example 2-5,7), or q to quit: "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if selection.casefold() in {"q", "quit"}:
            break

        try:
            selected_ids = _parse_training_selection(
                selection,
                {example.id for example in examples},
            )
        except ValueError as exc:
            print(f"Invalid selection: {exc}")
            continue

        selected = [example for example in examples if example.id in selected_ids]
        print()
        print("Selected examples")
        for example in selected:
            print(f"  {example.id:>4}  {example.raw_text}")

        try:
            group_name = input("\nWhat do these requests mean? ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not group_name:
            print("Group cancelled; description cannot be empty.")
            continue

        handling = _read_training_handling()
        if handling == "q":
            break
        if handling == "s":
            continue

        assert isinstance(handling, TrainingGroupHandling)
        target_label = None
        if handling is TrainingGroupHandling.EXISTING_BEHAVIOR:
            target_label = _choose_known_behavior(application)
            if target_label is None:
                print("Group cancelled; no existing behavior selected.")
                continue

        group = application.training_repository.create_group(
            name=group_name,
            handling=handling,
            example_ids=selected_ids,
            target_label=target_label,
        )
        print(f"Saved group {group.id}: {group.name} ({group.example_count} examples).")
        if handling is TrainingGroupHandling.NEW_DETERMINISTIC:
            print(
                "No internal intent label is required yet; Porter will assign it "
                "when implemented."
            )

    print()
    _print_training_review_summary(application)
    print()
    _print_training_groups(application)
    _print_recognition_gaps(application)
    return 0


def run(application: PorterApplication, args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="porter training",
        description="Capture and review deterministic-recognition training examples",
    )
    parser.add_argument("action", nargs="?", choices=("review", "groups"))
    parsed = parser.parse_args(args)

    if parsed.action == "review":
        return _run_training_review(application)
    if parsed.action == "groups":
        _print_training_groups(application)
        return 0
    return _run_training_session(application)
