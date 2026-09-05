@echo off
echo ================================================================
echo Building Crypto90's OBS Now Playing Widget Executable
echo ================================================================

python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

pyinstaller --onefile --noconsole --name "Crypto90s_OBS_NowPlayingWidget" ^
    --add-data "templates;templates" ^
    obs_now_playing_widget_windows_media_api.py

echo.
echo ================================================================
echo Build complete! Your standalone executable is located in:
echo   dist\Crypto90s_OBS_NowPlayingWidget.exe
echo ================================================================
pause
