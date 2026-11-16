"""期望值：由样例数据与规则手工推导，不在测试里回读实现。"""

MAIN = {
    "raw_records": 92,
    "accepted": 83,
    "duplicates": 2,
    "quarantined": 7,
    "observed": 83,
    "filled": 8,
    "gaps": 19,
    "expected_buckets": 110,
    "grid_points": 110,
    "windows": 14,
    "blank_lines": 2,
    "late": 1,
    "accepted_sum": "5482.000",
    "filled_sum": "1476.650",
    "grid_sum": "6958.650",
    "partial_windows": 7,
}

GAP = {
    "raw_records": 5,
    "accepted": 5,
    "duplicates": 0,
    "quarantined": 0,
    "observed": 5,
    "filled": 3,
    "gaps": 10,
    "expected_buckets": 18,
    "windows": 2,
    "threshold_sums": [
        {"sensor_id": "TH-02", "bucket": "2026-03-01T00:02:00Z", "value": "42.000"},
        {"sensor_id": "TH-02", "bucket": "2026-03-01T00:03:00Z", "value": "43.000"},
        {"sensor_id": "TH-02", "bucket": "2026-03-01T00:05:00Z", "value": "45.000"},
    ],
}

EDGE = {
    "raw_records": 4,
    "accepted": 3,
    "duplicates": 1,
    "observed": 3,
    "gaps": 59,
    "expected_buckets": 62,
    "windows": 6,
}

MAIN_FILLS = [
    ("TH-01", "2026-03-01T00:04:00Z", "46.1", "FILLED_HOLD"),
    ("TH-01", "2026-03-01T00:22:00Z", "46.8", "FILLED_HOLD"),
    ("TH-01", "2026-03-01T00:26:00Z", "46.0", "FILLED_HOLD"),
    ("CO-03", "2026-03-01T00:15:00Z", "13.200", "FILLED_LINEAR"),
    ("WS-05", "2026-03-01T00:18:00Z", "2.750", "FILLED_LINEAR"),
    ("PM-02", "2026-03-01T00:25:00Z", "41.2", "FILLED_HOLD"),
]

MAIN_DUPLICATES = [
    {"sensor_id": "TH-01", "bucket": "2026-03-01T00:08:00Z", "kept_row": 30, "dropped_row": 31,
     "kept_value": "47.2", "dropped_value": "47.9"},
    {"sensor_id": "PM-02", "bucket": "2026-03-01T00:05:00Z", "kept_row": 89, "dropped_row": 20,
     "kept_value": "39.9", "dropped_value": "39.5"},
]

MAIN_QUARANTINE = [
    ("NO-04", "SENTINEL_VALUE"),
    ("WS-05", "UNIT_MISMATCH"),
    ("TH-01", "OUT_OF_RANGE"),
    ("TH-01", "SENTINEL_VALUE"),
    ("PM-02", "NOT_DECIMAL"),
    ("PM-02", "OFF_RATE"),
    ("XX-99", "UNKNOWN_SENSOR"),
]

THREE_PLACES = "0.001"
SEVEN_DAY = "2026-03-01"
