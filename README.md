# Custom Lock Screen Date (Nugget)

**English** · [Русский](README.ru.md)

Brings back the long date format on the iOS 26 lock screen — «Friday, September 18»
instead of the shortened «Fri Sep 18» that Apple left with no setting to change.

Built on the restore engine of [LeminLimez/Nugget](https://github.com/leminlimez/Nugget).
Works on iOS **26.0 – 26.6.2**.

<img width="707" height="889" alt="image" src="https://github.com/user-attachments/assets/afc54927-8187-41b6-a83d-112e79c8bb46" />

## How it works

iOS renders the lock-screen date from a fixed short template (`EEE d MMM`). You cannot
change the template, but the standard CoreFoundation key `AppleICUDateTimeSymbols` lets you
override the *short* month and weekday names. This tool replaces those short names with long
ones, so the system draws the full date thinking it is printing abbreviations.

The tool writes a single file — the user preferences
`HomeDomain/Library/Preferences/.GlobalPreferences.plist` — and never touches the managed
preferences file, so it does not interfere with other Nugget tweaks (Liquid Glass, etc.).

## Features

- All iPhone system languages and all regions — pick the exact pair your device uses.
- Month and weekday names are editable: change any of the 19 strings to whatever you want.
- Per-language presets from CLDR, with verified overrides for ru / uk / be / kk.
- Optional comma after the weekday («Friday, 18 September»).
- Optional 12/24-hour override.
- Live preview and a match indicator against the locale on the connected device.
- Bilingual UI (English / Russian).

## Requirements

- Windows with the "Apple Devices" app (or iTunes) installed.
- Python 3.12 (3.14 has no prebuilt `lzfse`/`pylzss`).
- **Find My must be turned off** on the device before applying.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```powershell
python lockscreen_date.py
```

On Windows the app relaunches itself with administrator rights (needed to save the device
pairing record). Connect the iPhone, unlock it, pick language + region, edit the names if you
like, and press **Apply**. The device reboots to apply.

Use **Remove tweak from device** to restore the default iOS date format.

## Warning

Do **not** update to iOS 27. Apple closed the partial-restore mechanism Nugget relies on;
applying tweaks there wipes the device.

## Credits

Restore engine and device handling by [LeminLimez](https://github.com/leminlimez/Nugget).
This project only adds the standalone `lockscreen_date.py` utility.
