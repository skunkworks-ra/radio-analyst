---
description: Inspect a CASA Measurement Set and hand precal the four inputs it needs -
             intents present, calibrator fields, bandpass field, and bandpass-calibrator
             minimum elevation.
allowed-tools: mcp__plugin_radio-analyst_ms-inspect__ms_field_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_elevation_vs_time
---

Inspect this Measurement Set for precal: $ARGUMENTS

Do not load a skill or read any file. Use only the two tools below.

Run these two tools, in this order:
1. ms_field_list
2. ms_elevation_vs_time

Then output this handoff block and nothing else:

```
INSPECT HANDOFF
intents_present: <yes | no>  (yes if any field has intents)
cal_fields: <comma-separated calibrator field names>
bp_field: <bandpass calibrator field name>
bp_cal_min_elevation_deg: <lowest elevation over the bandpass calibrator's scans>
bp_field_centre_ghz: <observing_frequency centre_ghz of the bandpass field>
```
