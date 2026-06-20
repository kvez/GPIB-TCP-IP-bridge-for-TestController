# HP / Agilent 3458A – NPLC and Logging Start Freeze

**Related file:** `AgilentHP3458A.txt` (TestController device definition)  
**Date:** 2026-06-20

---

## The Phenomenon

When logging starts, TestController reads back all Setup panel settings (range, NPLC, AZERO, etc.) using the `:read:` queries defined in the `#cmdSetup` sections. Each query sends a GPIB command to the meter and waits for a response.

If the meter is currently executing a long measurement cycle (e.g. NPLC 1000 = 20 s integration at 50 Hz), it will not respond to any query until the current measurement cycle finishes. During this time TestController appears to freeze — **it is not crashed, it is waiting**.

---

## Timeout Limits

The GPIB read timeout is controlled by the `#readingDelay` directive (currently **28 s**).  
The maximum `++read` timeout ceiling of AR488 / Prologix adapters is approximately **32 s**.

If the meter's integration time exceeds the `#readingDelay` value, the setting readback will fail with a timeout, and the displayed value may be stale or invalid.

---

## Integration Times (50 Hz mains)

| NPLC | Integration time | With AZERO ON (approx.) | Note |
|------|-----------------|--------------------------|------|
| 1    | 20 ms           | ~40 ms                   | No problem |
| 10   | 200 ms          | ~400 ms                  | No problem |
| 100  | 2 s             | ~4 s                     | Safe, well within timeout |
| 1000 | 20 s            | ~40 s                    | **TIMEOUT RISK** – exceeds #readingDelay 28 s |

> AZERO ON approximately doubles the integration time, because the meter performs a zero measurement after each reading.

---

## Recommendations

1. **Keep NPLC ≤ 100 for logging** (2 s integration, ~4 s with AZERO ON) — this stays well below the 28 s timeout.

2. **If NPLC 1000 is required** for maximum accuracy:
   - Turn off autozero (`AZERO OFF`) — this reduces integration time to ~20 s, which just fits within the timeout, but approaches the adapter maximum.
   - Consider raising `#readingDelay` toward the adapter maximum (~30 s), keeping in mind that every failed readback will now block TC for 30 s.

3. **Do not start logging immediately** after changing to a high NPLC value — wait for the current measurement cycle to complete before TC sends its readback queries.

4. **Separate setup and logging profiles:** if possible, use a high NPLC only in the interactive setup profile, and reduce it before starting a logging session.

---

## Technical Background

TestController executes every `:read:` directive in the `#cmdSetup` sections at logging start to synchronize the current meter state. The 3458A uses HP proprietary commands (not SCPI) such as `TARM`, `NRDGS`, `FUNC?`, and the INBUF input buffer does not protect against blocking caused by slow measurements, because TC must receive the response directly from the GPIB bus.

---

*See also: `AgilentHP3458A_elemzes_log_fagyas_20260617.txt` – earlier analysis log covering the same phenomenon.*
