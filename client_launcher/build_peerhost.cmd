@echo off
echo Installing PyInstaller...
py -m pip install pyinstaller

echo Building Bootstrap Launcher (Runtime Manager)...

py -m PyInstaller --noconfirm --onefile --console --name "PeerHost" --hidden-import=requests bootstrap.py

echo Build Complete! Check dist/PeerHost.exe
pause
