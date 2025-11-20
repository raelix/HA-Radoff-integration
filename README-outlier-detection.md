# Radoff Now Sensor – Outlier Detection

## Overview

This change extends the original Radoff Now Home Assistant integration with robust outlier handling, while keeping normal sensor behavior unchanged. The change was introduced due to some implausible readings from my TVOC and Temperature sensor. 

- TVOC had some drops to 0, especially early mornings
- Temperature sensor sometimes peaks to temperature readings above 50°C

These readings are also stored in Radoff's IOT cloud and can be seen when downloading the data. It is unknown whether they are really transfered by the device or whether it is a flaw of the transfer of sensor data into the Radoff cloud. 

**Key idea:**  
- Normal readings are passed through as-is.  
- Only detected outliers are replaced (using a small history-based median).  
- Index sensors use the cleaned base values, not raw ones.

---

## Changes compared to original code

| Aspect | Original | Outlier detection version (this version) |
| --- | --- | --- |
| Value processing | Raw sensor value is passed through | Raw value is used unless flagged as outlier |
| Outlier detection | None | Hybrid: zero-drop rule + delta-threshold |
| History tracking | None | Last 3 valid values per base sensor |
| Median usage | Not used | Only used when replacing detected outliers |
| Index sensors | Based on raw values | Based on cleaned base values; suppressed if base is suppressed |
| Configuration | Only INDEX_MAPPING | Adds OUTLIER_THRESHOLDS and ZERO_DROP_CONFIG |

---

## New configuration parameters

### OUTLIER_THRESHOLDS

Used for general outlier detection based on change magnitude from the last valid value.

```
OUTLIER_THRESHOLDS: dict[str, float] = {
	"internal_temperature": 5.0, # Max 5°C change between readings
	"tvoc": 150.0, # Max 150 V-lx change
	"eco2": 500.0, # Max 500 ppm change
	"relative_humidity": 15.0, # Max 15% change
	"pm1": 50.0,
	"pm25": 50.0,
	"pm10": 50.0,
	"pressure": 1000.0, # Max 1000 Pa change
}
```

- These values can be tuned per sensor.
- For TVOC, a relatively high threshold (150.0) is used so that legitimate large jumps (e.g. 196 → 96) are not suppressed.  
- Zero-drops to 0 are handled separately (see below).

### ZERO_DROP_CONFIG

Used for sensor-specific detection of “drops to zero / near-zero” from normal values.

```
ZERO_DROP_CONFIG: dict[str, dict[str, float]] = {
	"tvoc": {
		"low_threshold": 1.0, # Values below this are considered "zero"
		"normal_threshold": 20.0, # Previous value must be above this to trigger zero-drop detection
	}
}
```


**Effect for TVOC:**
- If a reading goes from, for example, 70 → 0 or 225 → 0:
  - Current value `< 1.0`
  - Previous value `> 20.0`
  - This is flagged as a zero-drop outlier, regardless of the 150-threshold.

---

## Outlier detection logic

### Method: `_is_outlier_detected`

1. If there is no previous valid value, no outlier is detected.
2. If there is no threshold configured for this sensor key, no outlier is detected.
3. **Zero-drop check (sensor-specific, for keys in `ZERO_DROP_CONFIG`):**
   - If `current_value < low_threshold` **and**
   - `last_valid_value > normal_threshold`  
   → Zero-drop outlier detected (e.g. TVOC dropping from 90 to 0).
4. **Threshold check (all supported sensors):**
   - `change = abs(current_value - last_valid_value)`  
   - If `change > OUTLIER_THRESHOLDS[sensor_key]`  
   → Threshold outlier detected (e.g. temperature 20.5°C → 52.2°C).

---

## Replacement strategy

When `_is_outlier_detected()` returns `True`:

1. If there is history (up to last 3 non-outlier values):
   - Compute median using `_calculate_median` and return it as the cleaned value.
2. Else if there is a `_last_valid_value`:
   - Re-use `_last_valid_value`.
3. Else (no history and no last valid value):
   - Skip this reading: return `None` and store `None` for the index sensor.

When no outlier is detected:

- The raw (normalized) value is:
  - Added to the history buffer (`_value_history`),  
  - Stored as `_last_valid_value`,  
  - Written to `_FILTERED_VALUES` for index sensors,  
  - Returned as the sensor state.

---

## Behavior of index sensors

- Index sensors no longer perform their own filtering or history management.
- They obtain the filtered base sensor value from `_FILTERED_VALUES[device_id][sensor_key]`.
- If the base value is `None` (outlier skipped), the index sensor returns `None` as well and does not update.
- This ensures:
  - Indices are always based on cleaned data.
  - No index is produced for readings that were suppressed as outliers.

---

## Examples

### 1) Temperature spike

- Raw data:
  - 20.5°C → **52.2°C** → 20.8°C
- Threshold: `internal_temperature = 5.0`
- Change: 52.2 – 20.5 ≈ 31.7 > 5.0 → Threshold outlier detected.

**Original integration:**
- State: 20.5 → 52.2 → 20.8  
- Index: “good” → “terrible” → “good”  
- Graph: Strong spike to 52°C.

**Outlier detection integration:**
- State: 20.5 → median(history) ≈ 20.5 → 20.8  
- Index: consistent “good” readings  
- Graph: No erroneous 52°C spike.

---

### 2) TVOC zero-drop (multiple days)

Example raw patterns:

- 91.0 → **0.0**
- 225.0 → **0.0**
- 90.0 → **0.0**
- 108.0 → **0.0**
- 100.0 → **0.0**
- 70.0 → **0.0**

**Zero-drop detection:**
- Previous value `> 20.0`, current value `< 1.0`  
→ Zero-drop outlier detected (even though delta might be less than 150 for some cases).

**Original integration:**
- TVOC briefly drops to 0 → graph shows dips to 0 → misleading for interpretation.

**Outlier detection integration:**
- For these readings:
  - Marked as zero-drop outliers.
  - Replaced by median of recent valid TVOC values (e.g. around previous level).
  - Index stays consistent; no “fake fresh air” because of 0 TVOC.

---

### 3) Legitimate TVOC jump (allowed)

From your data:

- 196.0 → 96.0 (delta = 100.0)
- Both values are reasonable and not near zero.

With `OUTLIER_THRESHOLDS["tvoc"] = 150.0`:

- `change = 100.0 < 150.0` → **no outlier**.
- Outlier detection version will pass this as a normal reading.

**Result:**
- Sensor remains responsive to valid, large variations (e.g. airing a room, cooking, etc.).
- Only obviously erroneous values (like sudden zeros) are filtered.

---

## File-level changes vs. original `sensor.py`

Compared to the original integration file:

- Added import:
  - `from collections import deque`
- Added new module-level constants:
  - `OUTLIER_THRESHOLDS`
  - `ZERO_DROP_CONFIG`
  - `_FILTERED_VALUES`
- In `async_setup_entry`:
  - Initialization of `_FILTERED_VALUES[device_id]` for each device.
- In `RadoffSensor.__init__`:
  - New attributes for base sensors:
    - `_value_history: deque` (size 3)
    - `_last_valid_value`
- New methods in `RadoffSensor`:
  - `_calculate_median`
  - `_is_outlier_detected` (with hybrid logic)
  - `_get_filtered_base_value`
  - `_store_filtered_value`
- Modified `native_value`:
  - Uses `_is_outlier_detected` to decide when to replace/suppress a value.
  - Uses median/last_valid_value for replacements.
  - Stores cleaned values in `_FILTERED_VALUES` for index sensors.
  - Returns `None` if a reading is skipped.

All other behavior (device info, translation keys, index mapping, etc.) retains the original design.

---

## Summary

This change keeps your sensor behavior natural for normal operation, but:

- Eliminates spurious TVOC zero readings.
- Suppresses unrealistic spikes (e.g. 52°C).
- Ensures index sensors always reflect cleaned, reliable values.
- Provides tunable parameters for both general thresholds and special zero-drop detection.
