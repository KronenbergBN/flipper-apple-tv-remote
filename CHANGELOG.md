# Changelog

## 1.6 — 2026-09-29

- Fix ignored Back on the disconnected main screen: short Back now exits.
- Hold Back exits locally in Actions or without a usable Bluetooth connection.
- Preserve the connected remote/volume Power shortcut and short Back to cancel Actions.
- Show the local Exit shortcuts on screen.
- Regression tests reproduce the old trapped-Back behavior and check that Actions exit sends no Power command.
- Installed on the owner's Flipper with byte-for-byte readback; short Back from the disconnected main screen, long Back while disconnected, and long Back in Actions all closed the app. Connected Power behavior is covered by handler regression tests, not a new physical TV test.

## 1.3 — 2026-09-26

First public release. Uses the same HID commands as the owner-tested version 1.2.

- English remote UI with drawn direction arrows.
- Directional navigation, Select, Back, Play/Pause, Wake and Power.
- Fixed Left input handling and tested all four directions against official SDK enums.
- General pairing label for any Flipper device name.
- Removed the Power action's test label after owner confirmation.
- Tested setup: Apple TV 4K A2843 (128 GB), tvOS 26.6; official Flipper firmware 1.4.3.
- Build, SDK import check, lint and input-handler tests passed. Version 1.3 has not been physically installed/retested; the device confirmation applies to version 1.2. A separate physical retest of Left is still unreported.
