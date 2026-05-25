from datetime import date, datetime
from typing import Any

from sunshine_core.models import (
    DateSource,
    DestinationResolution,
    FolderTarget,
    PlacementRule,
    PlacementRuleType,
)


class PlacementResolutionError(ValueError):
    pass


def resolve_destination(
    folder: FolderTarget,
    placement_rule: PlacementRule,
    metadata: dict[str, Any],
) -> DestinationResolution:
    if not folder.is_active:
        raise PlacementResolutionError("Destination folder is inactive.")
    if not placement_rule.is_active:
        raise PlacementResolutionError("Placement rule is inactive.")

    base_path = folder.path_hint.strip("/")

    if placement_rule.rule_type == PlacementRuleType.FLAT:
        destination_path = base_path
    elif placement_rule.rule_type == PlacementRuleType.BY_YEAR:
        year = _extract_year(metadata, placement_rule.date_source)
        destination_path = f"{base_path}/{year}"
    elif placement_rule.rule_type == PlacementRuleType.BY_YEAR_MONTH:
        year, month = _extract_year_month(metadata, placement_rule.date_source)
        destination_path = f"{base_path}/{year}/{month:02d}"
    else:
        raise PlacementResolutionError(f"Unsupported rule type: {placement_rule.rule_type}")

    return DestinationResolution(
        folder_id=folder.id,
        drive_folder_file_id=folder.drive_folder_file_id,
        destination_path=destination_path,
        rule_type=placement_rule.rule_type,
    )


def _extract_year(metadata: dict[str, Any], date_source: DateSource) -> int:
    value = metadata.get(date_source.value)
    parsed = _parse_date(value)
    if parsed is None:
        raise PlacementResolutionError(f"Missing usable {date_source.value} for year placement.")
    return parsed.year


def _extract_year_month(metadata: dict[str, Any], date_source: DateSource) -> tuple[int, int]:
    value = metadata.get(date_source.value)
    parsed = _parse_date(value)
    if parsed is None:
        raise PlacementResolutionError(f"Missing usable {date_source.value} for year-month placement.")
    return parsed.year, parsed.month


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None
