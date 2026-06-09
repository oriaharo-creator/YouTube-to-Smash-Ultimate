assets/ — optional branding
===========================

Drop an application icon here as:

    assets\app.ico

If present, the PyInstaller spec automatically uses it for both executables,
and you can enable it in the Inno Setup installer by uncommenting the
SetupIconFile line in installer\yt2smash.iss.

The icon must be a real Windows .ico (multi-resolution recommended:
16/32/48/256 px). To convert a PNG, you can use ImageMagick:

    magick app.png -define icon:auto-resize=256,48,32,16 app.ico

If no app.ico is present, the build still succeeds using PyInstaller's default
icon. This README.txt is not shipped.
