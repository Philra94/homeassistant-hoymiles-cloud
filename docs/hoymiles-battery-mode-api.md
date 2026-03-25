# Hoymiles Battery Mode API Investigation

## Scope

This document captures an authenticated browser investigation of the Hoymiles S-Miles Cloud battery working mode UI for plant `6703580`.

- Investigation method: Playwright MCP against the live Hoymiles Cloud web UI
- UI path: `Plant -> Settings -> Battery`
- Goal: understand how battery working modes are read and written, and record the response formats for later Home Assistant integration work
- Safety note: write requests were intercepted and aborted before they reached the backend, so no battery mode was changed during this investigation

Sensitive values such as cookies and bearer tokens are intentionally omitted from this document.

## Key Findings

- The battery settings page loads current mode data through an asynchronous `read -> poll status` flow.
- Mode changes are submitted through `POST /pvm-ctl/api/0/dev/setting/write`.
- The write payload uses the same top-level schema as the read result: a numeric `mode` plus mode-specific `data`.
- The observed UI exposes six visible working modes:
  - `1` Self-Consumption Mode
  - `2` Economy Mode
  - `3` Backup Mode
  - `4` Off-Grid Mode
  - `7` Peak Shaving Mode
  - `8` Time of Use Mode
- The read response also contains backend payload buckets `k_5` and `k_6`, which were not exposed as visible modes in this plant's current web UI.
- `Time of Use Mode` still carries a default schedule block in the outgoing payload with `03:00-05:00`, matching the previously reported behavior in GitHub issue `#18`.

## UI To Backend Mode Mapping

| UI label | Backend mode | Observed write payload |
| --- | --- | --- |
| Self-Consumption Mode | `1` | `{"mode":1,"data":{"reserve_soc":10}}` |
| Economy Mode | `2` | `{"mode":2,"data":{"reserve_soc":10,"money_code":"$","date":[...]}}` |
| Backup Mode | `3` | `{"mode":3,"data":{"reserve_soc":100}}` |
| Off-Grid Mode | `4` | `{"mode":4}` |
| Peak Shaving Mode | `7` | `{"mode":7,"data":{"reserve_soc":35,"max_soc":70,"meter_power":11000}}` |
| Time of Use Mode | `8` | `{"mode":8,"data":{"reserve_soc":10,"time":[...]}}` |

## Request Headers

The browser sent these relevant headers on the authenticated API calls:

- `Accept: application/json`
- `Content-Type: application/json; charset=utf-8`
- `language: de-de`
- `authorization: <session token>`

The `authorization` header is session-specific and should be treated as opaque.

## API Flow

### 1. Capability And Rule Discovery

#### `POST https://neapi.hoymiles.com/pvm/api/0/station/setting_rule`

Request body:

```json
{"sid":6703580}
```

Observed response:

```json
{
  "status": "0",
  "message": "success",
  "data": {
    "sub_brand": 0,
    "balance": 0,
    "reflux": 0,
    "reflux_version": 0,
    "balance_version": 0,
    "dual_pipe": 1,
    "grid_type": 0,
    "ctl_mode_set": [],
    "is_de": 0,
    "sna": 0,
    "gpc": 1,
    "tlv": 0,
    "aio": 0,
    "og": 0,
    "mt": 0
  }
}
```

Notes:

- This looks like a feature-capability endpoint for station-specific control rules.
- `ctl_mode_set` was empty for this station even though the UI still exposed multiple battery modes.

#### `POST https://neapi.hoymiles.com/pvm-ai/api/0/station/sar_g_c`

Request body:

```json
{"sid":6703580}
```

Observed response:

```json
{
  "status": "0",
  "message": "success",
  "data": {
    "ai": 0,
    "compound_mode": 9000
  }
}
```

Notes:

- This appears to provide additional control metadata.
- `compound_mode` may be relevant for gating which battery modes or compound strategies are available.

### 2. Read Current Battery Mode Settings

#### `POST https://neapi.hoymiles.com/pvm-ctl/api/0/dev/setting/read`

Request body:

```json
{
  "action": 1013,
  "data": {
    "sid": 6703580
  }
}
```

Observed response:

```json
{
  "status": "0",
  "message": "success",
  "data": "39219485"
}
```

Notes:

- The `data` field is not the setting payload yet.
- It is an asynchronous job id and must be polled via `/status`.

### 3. Poll Read Job Status

#### `POST https://neapi.hoymiles.com/pvm-ctl/api/0/dev/setting/status`

Request body:

```json
{
  "id": "39219485"
}
```

#### In-progress response format

Observed response:

```json
{
  "status": "0",
  "message": "success",
  "data": {
    "code": 2,
    "speed": [
      {
        "sn": "214422470204",
        "type": 6,
        "rate": -1,
        "err_code": "",
        "sid": 6703580,
        "station_name": "Rau - Bad Schönborn",
        "module": "006000"
      }
    ],
    "data": [],
    "message": ""
  }
}
```

Notes:

- `code: 2` means the job is still running.
- `speed` contains per-device execution progress metadata.
- `data` is an empty array while the result is still pending.

#### Completed response format

Observed response:

```json
{
  "status": "0",
  "message": "success",
  "data": {
    "code": 0,
    "speed": [
      {
        "sn": "214422470204",
        "type": 6,
        "rate": 100,
        "err_code": "",
        "sid": 6703580,
        "station_name": "Rau - Bad Schönborn",
        "module": "006000"
      }
    ],
    "data": {
      "mode": 1,
      "data": {
        "k_1": {
          "reserve_soc": 10
        },
        "k_2": {
          "reserve_soc": 10,
          "money_code": "$",
          "date": [
            {
              "start_date": "01-01",
              "end_date": "12-31",
              "time": [
                {
                  "week": [1, 2, 3, 4, 5],
                  "duration": [
                    {
                      "type": 1,
                      "start_time": "00:00",
                      "end_time": "00:00",
                      "in": 0.0,
                      "out": 0.0
                    },
                    {
                      "type": 2,
                      "start_time": null,
                      "end_time": null,
                      "in": 0.0,
                      "out": 0.0
                    },
                    {
                      "type": 3,
                      "start_time": "00:00",
                      "end_time": "00:00",
                      "in": 0.0,
                      "out": 0.0
                    }
                  ]
                },
                {
                  "week": [6, 7],
                  "duration": [
                    {
                      "type": 1,
                      "start_time": "00:00",
                      "end_time": "00:00",
                      "in": 0.0,
                      "out": 0.0
                    },
                    {
                      "type": 2,
                      "start_time": null,
                      "end_time": null,
                      "in": 0.0,
                      "out": 0.0
                    },
                    {
                      "type": 3,
                      "start_time": "00:00",
                      "end_time": "00:00",
                      "in": 0.0,
                      "out": 0.0
                    }
                  ]
                }
              ]
            }
          ]
        },
        "k_3": {
          "reserve_soc": 100
        },
        "k_4": {},
        "k_5": {
          "reserve_soc": 70,
          "max_power": 50.0
        },
        "k_6": {
          "reserve_soc": 30,
          "max_power": 50.0
        },
        "k_7": {
          "reserve_soc": 35,
          "max_soc": 70,
          "meter_power": "11000"
        },
        "k_8": {
          "reserve_soc": 10,
          "time": [
            {
              "cs_time": "03:00",
              "ce_time": "05:00",
              "c_power": 100,
              "dcs_time": "05:00",
              "dce_time": "03:00",
              "dc_power": 100,
              "charge_soc": 90,
              "dis_charge_soc": 10
            }
          ]
        }
      }
    },
    "message": ""
  }
}
```

Notes:

- `code: 0` means the async job completed successfully.
- `data.mode` is the currently active backend mode.
- `data.data.k_<n>` stores the persisted configuration block for each backend mode.
- `k_1`, `k_2`, `k_3`, `k_4`, `k_7`, and `k_8` map cleanly to the six visible UI modes observed in this session.
- `k_5` and `k_6` were returned by the backend but were not exposed as visible modes in this plant's battery settings UI.

## Observed Write Endpoint

### `POST https://neapi.hoymiles.com/pvm-ctl/api/0/dev/setting/write`

Two kinds of evidence were collected for the write endpoint:

- the full browser-generated request payloads were captured while being aborted before they reached Hoymiles
- a same-state live write was later submitted with the active Self-Consumption payload to confirm the real response format without intentionally changing the plant configuration

All writes used the same wrapper:

```json
{
  "action": 1013,
  "data": {
    "sid": 6703580,
    "data": {
      "mode": "<mode number>",
      "data": {
        "...": "mode-specific payload"
      }
    }
  }
}
```

Note:

- `mode: 4` was sent without a nested `data` object in the observed UI request.

### Confirmed live write response format

Observed response for a same-state live write:

```json
{
  "status": "0",
  "message": "success",
  "data": "39284764"
}
```

Notes:

- `data` is a command/job id string, not the final completion payload.
- This confirms that `dev/setting/write` follows the same async command pattern as `dev/setting/read`.

### Confirmed live write status polling format

Polling `POST https://neapi.hoymiles.com/pvm-ctl/api/0/dev/setting/status` with the returned write job id produced:

In progress:

```json
{
  "status": "0",
  "message": "success",
  "data": {
    "code": 2,
    "speed": [
      {
        "sn": "214422470204",
        "type": 6,
        "rate": -1,
        "err_code": "",
        "sid": 6703580,
        "station_name": "Rau - Bad Schönborn",
        "module": "006000"
      }
    ],
    "data": [],
    "message": ""
  }
}
```

Complete:

```json
{
  "status": "0",
  "message": "success",
  "data": {
    "code": 0,
    "speed": [
      {
        "sn": "214422470204",
        "type": 6,
        "rate": 100,
        "err_code": "",
        "sid": 6703580,
        "station_name": "Rau - Bad Schönborn",
        "module": "006000"
      }
    ],
    "data": [],
    "message": ""
  }
}
```

Notes:

- Successful writes complete with `code: 0` and an empty `data` array.
- The read and write command flows therefore share the same job submission and polling pattern, but only the read completion returns a structured settings payload.

### Self-Consumption Mode

Observed write body:

```json
{
  "action": 1013,
  "data": {
    "sid": 6703580,
    "data": {
      "mode": 1,
      "data": {
        "reserve_soc": 10
      }
    }
  }
}
```

### Economy Mode

Observed write body:

```json
{
  "action": 1013,
  "data": {
    "sid": 6703580,
    "data": {
      "mode": 2,
      "data": {
        "reserve_soc": 10,
        "money_code": "$",
        "date": [
          {
            "start_date": "01-01",
            "end_date": "12-31",
            "time": [
              {
                "week": [1, 2, 3, 4, 5],
                "duration": [
                  {
                    "type": 2,
                    "start_time": null,
                    "end_time": null,
                    "in": 0,
                    "out": 0
                  },
                  {
                    "type": 1,
                    "start_time": "00:00",
                    "end_time": "00:00",
                    "in": 0,
                    "out": 0
                  },
                  {
                    "type": 3,
                    "start_time": "00:00",
                    "end_time": "00:00",
                    "in": 0,
                    "out": 0
                  }
                ]
              },
              {
                "week": [6, 7],
                "duration": [
                  {
                    "type": 2,
                    "start_time": null,
                    "end_time": null,
                    "in": 0,
                    "out": 0
                  },
                  {
                    "type": 1,
                    "start_time": "00:00",
                    "end_time": "00:00",
                    "in": 0,
                    "out": 0
                  },
                  {
                    "type": 3,
                    "start_time": "00:00",
                    "end_time": "00:00",
                    "in": 0,
                    "out": 0
                  }
                ]
              }
            ]
          }
        ]
      }
    }
  }
}
```

### Backup Mode

Observed write body:

```json
{
  "action": 1013,
  "data": {
    "sid": 6703580,
    "data": {
      "mode": 3,
      "data": {
        "reserve_soc": 100
      }
    }
  }
}
```

### Off-Grid Mode

Observed write body:

```json
{
  "action": 1013,
  "data": {
    "sid": 6703580,
    "data": {
      "mode": 4
    }
  }
}
```

### Peak Shaving Mode

Observed write body:

```json
{
  "action": 1013,
  "data": {
    "sid": 6703580,
    "data": {
      "mode": 7,
      "data": {
        "reserve_soc": 35,
        "max_soc": 70,
        "meter_power": 11000
      }
    }
  }
}
```

### Time of Use Mode

Observed write body:

```json
{
  "action": 1013,
  "data": {
    "sid": 6703580,
    "data": {
      "mode": 8,
      "data": {
        "reserve_soc": 10,
        "time": [
          {
            "cs_time": "03:00",
            "ce_time": "05:00",
            "c_power": 100,
            "dcs_time": "05:00",
            "dce_time": "03:00",
            "dc_power": 100,
            "charge_soc": 90,
            "dis_charge_soc": 10
          }
        ]
      }
    }
  }
}
```

Notes:

- The default `03:00-05:00` schedule is still emitted by the current web UI when `Time of Use Mode` is selected.
- This behavior is important for the Home Assistant integration because blindly sending mode `8` may overwrite user-defined schedules.

## Response Envelope Patterns

These envelope shapes were actually observed during the investigation.

### Common success envelope

```json
{
  "status": "0",
  "message": "success",
  "data": "<endpoint-specific payload>"
}
```

### Async job id envelope

Used by `dev/setting/read`.

```json
{
  "status": "0",
  "message": "success",
  "data": "<job id as string>"
}
```

### Async status envelope while running

```json
{
  "status": "0",
  "message": "success",
  "data": {
    "code": 2,
    "speed": [
      {
        "sn": "<device sn>",
        "type": 6,
        "rate": -1,
        "err_code": "",
        "sid": 6703580,
        "station_name": "<station name>",
        "module": "006000"
      }
    ],
    "data": [],
    "message": ""
  }
}
```

### Async status envelope when complete

```json
{
  "status": "0",
  "message": "success",
  "data": {
    "code": 0,
    "speed": [
      {
        "sn": "<device sn>",
        "type": 6,
        "rate": 100,
        "err_code": "",
        "sid": 6703580,
        "station_name": "<station name>",
        "module": "006000"
      }
    ],
    "data": {
      "mode": "<active mode number>",
      "data": {
        "k_1": {},
        "k_2": {},
        "k_3": {},
        "k_4": {},
        "k_5": {},
        "k_6": {},
        "k_7": {},
        "k_8": {}
      }
    },
    "message": ""
  }
}
```

## Integration Implications

- The Home Assistant integration should likely treat battery settings as an asynchronous command flow:
  - submit request
  - receive job id
  - poll status until `code` changes from `2` to `0` or an error state
- Mode switching should preserve and resend the complete per-mode config block expected by Hoymiles.
- `Time of Use Mode` requires special handling because the web UI still sends a default schedule block that can overwrite user configuration.
- The integration should avoid assuming only one schedule-capable mode exists:
  - `mode 2` uses an electricity-rate and weekday/date schedule structure
  - `mode 8` uses a direct charge/discharge time block structure
- Hidden backend payload buckets `k_5` and `k_6` suggest there may be additional model-dependent modes or capabilities not visible in every plant UI.

## Open Questions

- What exact semantics do backend payload buckets `k_5` and `k_6` represent?
- Are `mode 2` and `mode 8` both intended to remain user-visible long-term, or is one a legacy/region-specific presentation of the other?
- Which fields in `station/setting_rule` and `sar_g_c` should be used to gate entity creation in Home Assistant?
