# App icons (optional)

Drop icon files here to brand the packaged app:

- `echo.icns` — macOS app icon (build from a 1024×1024 PNG via an `.iconset` +
  `iconutil -c icns echo.iconset`).
- `echo.ico` — Windows app icon (multi-size, e.g. 16/32/48/256; convert from PNG
  with Pillow or an online tool).

`echo_gui.spec` picks these up automatically if present, and builds fine without
them (no icon). Keep a 1024×1024 `echo.png` source here too if you have one.
