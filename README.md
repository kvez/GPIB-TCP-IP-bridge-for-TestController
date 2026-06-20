# GPIB Bridge — NI GPIB-USB-HS to Prologix TCP Bridge

A Windows bridge that exposes an NI GPIB-USB-HS adapter as a
Prologix GPIB-ETHERNET controller over TCP. Designed for use with
[TestController](https://lygte-info.dk/project/TestControllerIntro%20UK.html)
and the HP / Agilent / Keysight 3458A 8.5-digit multimeter.

## Features

- Prologix GPIB-ETHERNET protocol emulation on TCP port 1234
- Listens on all interfaces (`0.0.0.0`) — accessible over LAN
- Automatic GPIB board and HP 3458A detection on startup
- System tray icon and scrollable log window (windowed app, no console)
- Extended commands: `++hp3458_init`, `++scan`, `MREAD`

## Requirements

**Hardware**
- NI GPIB-USB-HS adapter
- HP / Agilent / Keysight 3458A multimeter (or other GPIB instrument)

**Software**
- Windows 10 or 11
- NI-488.2 driver — `ni4882.dll` must be present in `C:\Windows\System32\`
- Python 3.13+ with packages: `pystray`, `Pillow`

## Installation

Install Python dependencies:

```
pip install pystray Pillow
```

Run directly:

```
python gpib_bridge.py
```

Or build a standalone executable using PyInstaller:

```
pip install pyinstaller
pyinstaller gpib_bridge.spec
```

The executable is created at `dist\gpib_bridge.exe`.

## TestController Configuration

In TestController, open **GPIB interfaces → Add**:

| Setting    | Value                             |
|------------|-----------------------------------|
| Type       | PrologixEthernet                  |
| Connection | Socket → `<server IP>` : `1234`   |
| Address    | 0                                 |

Use `127.0.0.1` if TestController runs on the same machine as the bridge.

### HP 3458A Device File

The file **`AgilentHP3458A.txt`** is the TestController device definition for
the HP / Agilent / Keysight 3458A. Copy it to the TestController device
definitions folder before connecting.

## Prologix Commands

Standard Prologix GPIB-ETHERNET commands supported:

| Command           | Description                                   |
|-------------------|-----------------------------------------------|
| `++addr [n]`      | Get or set GPIB address                       |
| `++read`          | Read one response from the instrument         |
| `++auto 0\|1`     | Enable / disable auto-read after write        |
| `++clr`           | Send Device Clear (ibclr)                     |
| `++ifc`           | Send Interface Clear (ibsic)                  |
| `++loc`           | Go to Local (ibloc)                           |
| `++trg`           | Send Trigger (ibtrg)                          |
| `++ver`           | Return firmware version string                |
| `++read_tmo_ms n` | Set read timeout in milliseconds              |

Extended commands specific to this bridge:

| Command          | Description                                          |
|------------------|------------------------------------------------------|
| `++scan`         | Re-scan GPIB bus for HP 3458A                        |
| `++hp3458_init`  | HP 3458A: Device Clear + output buffer flush         |
| `MREAD`          | Read pending measurement into internal buffer        |

## Repository Files

| File                 | Description                                  |
|----------------------|----------------------------------------------|
| `gpib_bridge.py`     | Bridge application source code               |
| `gpib_bridge.spec`   | PyInstaller build specification              |
| `AgilentHP3458A.txt` | TestController device file for HP 3458A      |
