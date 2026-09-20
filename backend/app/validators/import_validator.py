"""Import batch validation helpers."""
from app.normalizers.catalog_normalizer import CatalogNormalizer

class ImportValidator:
    """Reject empty or partially invalid batches before staging."""
    def __init__(self) -> None:
        self.normalizer = CatalogNormalizer()

    def validate(self, records: list[dict]) -> dict:
        if not records: return {'valid': False, 'status': 'partial', 'errorCode': 'NO_DATA', 'validCount': 0, 'errors': []}
        result = self.normalizer.validate_batch(records)
        result['status'] = 'validated' if result['valid'] else 'partial'
        return result
