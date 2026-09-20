"""Raw spreadsheet row mapping and normalization."""
from typing import Any

class CatalogNormalizer:
    """Map source columns to template paths while preserving raw values."""
    def map_headers(self, raw: list[str], mapping: list[dict]) -> dict:
        aliases = {}
        for item in mapping:
            aliases[item['target_path']] = [item['source_column'], *item.get('aliases', [])]
        return {'columns': {target: next((name for name in raw if name in names), None) for target, names in aliases.items()}}

    def normalize_row(self, row: dict[str, Any], template: dict, mapping: list[dict]) -> dict:
        parsed: dict[str, Any] = {}
        for item in mapping:
            source = item['source_column']
            value = row.get(source)
            transform = item.get('transform')
            if value not in (None, '') and transform == 'percent': value = float(str(value).strip('%')) / 100
            if value not in (None, '') and transform == 'number': value = float(value)
            parsed[item['target_path']] = value
        stable = str(row.get('stable_key') or row.get('runId') or '')
        return {'stableKey': stable, 'raw': dict(row), 'parsed': parsed, 'derived': {}}

    def validate_batch(self, records: list[dict[str, Any]]) -> dict:
        errors = []
        seen = set()
        for index, record in enumerate(records, 2):
            key = record.get('stableKey', '')
            if not key: errors.append({'sourceRow': str(index), 'code': 'MISSING_STABLE_KEY', 'message': 'stable key is required'})
            elif key in seen: errors.append({'sourceRow': str(index), 'code': 'DUPLICATE_STABLE_KEY', 'message': 'stable key is duplicated'})
            seen.add(key)
        return {'valid': not errors, 'validCount': len(records) - len(errors), 'errors': errors}
