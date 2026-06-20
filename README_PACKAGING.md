# itent 打包说明

## 1. 安装依赖

```bash
pip install pyinstaller pillow
```

## 2. PyInstaller 打包

```bash
# 生成 ICO 图标（首次需要）
python -c "from PIL import Image; Image.open(r'C:\Users\人机\.itent\app_icon.png').save(r'C:\Users\人机\.itent\app_icon.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"

# 执行打包
python -m PyInstaller --onedir --windowed --name=itent --icon=C:\Users\人机\.itent\app_icon.ico --hidden-import PySide6.QtCore --hidden-import PySide6.QtGui --hidden-import PySide6.QtWidgets --hidden-import psutil --collect-all PySide6 main.py
```

打包完成后，exe 在 `dist/itent/itent.exe`

## 3. NSIS 安装包

1. 安装 NSIS: https://nsis.sourceforge.io/
2. 将 `dist/itent` 文件夹复制到项目目录
3. 右键 `itent_installer.nsi` → "Compile NSIS Script"
4. 生成的 `itent_setup.exe` 在安装包输出目录

## 4. 运行

直接运行 `dist/itent/itent.exe` 即可。
