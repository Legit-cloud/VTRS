"""Deterministic synthetic master data shaped like Oyo State (33 / 351 / ~6,390).

Stand-in until the approved INEC dataset is provided (PB-03). Codes are prefixed SYN so this
data can never be mistaken for the real directory.
"""

import random

OYO_LAT = (7.0, 9.2)
OYO_LNG = (2.7, 4.6)


def _spread(total: int, buckets: int) -> list[int]:
    base, extra = divmod(total, buckets)
    return [base + (1 if i < extra else 0) for i in range(buckets)]


def synthetic_master_data(
    *,
    lgas: int = 33,
    wards: int = 351,
    polling_units: int = 6390,
    missing_coordinate_ratio: float = 0.03,
    seed: int = 7,
) -> list[dict[str, str]]:
    if wards < lgas or polling_units < wards:
        raise ValueError("Need at least one ward per LGA and one polling unit per ward")
    rng = random.Random(seed)  # noqa: S311 - test data, not security sensitive
    ward_counts = _spread(wards, lgas)
    pu_counts = iter(_spread(polling_units, wards))
    rows: list[dict[str, str]] = []
    for lga_no, ward_count in enumerate(ward_counts, start=1):
        lga_code = f"SYN-{lga_no:02d}"
        for ward_no in range(1, ward_count + 1):
            ward_code = f"{lga_code}-{ward_no:02d}"
            for pu_no in range(1, next(pu_counts) + 1):
                has_coordinates = rng.random() >= missing_coordinate_ratio
                rows.append(
                    {
                        "state_code": "SYN",
                        "state_name": "Synthetic Oyo",
                        "lga_code": lga_code,
                        "lga_name": f"Synthetic LGA {lga_no:02d}",
                        "ward_code": ward_code,
                        "ward_name": f"Synthetic Ward {lga_no:02d}/{ward_no:02d}",
                        "pu_code": f"{ward_code}-{pu_no:03d}",
                        "pu_name": f"Synthetic PU {lga_no:02d}/{ward_no:02d}/{pu_no:03d}",
                        "latitude": f"{rng.uniform(*OYO_LAT):.6f}" if has_coordinates else "",
                        "longitude": f"{rng.uniform(*OYO_LNG):.6f}" if has_coordinates else "",
                        "registered_voters": str(rng.randint(300, 1500)),
                    }
                )
    return rows
