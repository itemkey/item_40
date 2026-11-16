from PyInstaller.utils.hooks import collect_all, collect_data_files
from pathlib import Path
from importlib import metadata
import os
import sys

ROOT = Path(SPECPATH).parent
# Isolate dependency discovery from unrelated DLLs supplied by the developer's PATH.
# In particular Poppler's icuuc.dll is incompatible with Windows' ICU used by Qt.
os.environ['PATH'] = os.pathsep.join([
    str(Path(sys.executable).parent), str(Path(sys.base_prefix)),
    str(Path(sys.base_prefix) / 'DLLs'),
    str(Path(os.environ['SystemRoot']) / 'System32'),
])

datas = []
binaries = []
hiddenimports = []
for package in ('faster_whisper', 'ctranslate2', 'av', 'tokenizers', 'onnxruntime'):
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports
datas += collect_data_files('certifi')
datas += [(str(ROOT / 'README.md'), '.'), (str(ROOT / 'THIRD_PARTY_NOTICES.md'), '.')]
datas.append((str(ROOT / 'docs'), 'docs'))
for distribution in metadata.distributions():
    name = distribution.metadata.get('Name', 'unknown')
    for file in distribution.files or []:
        if (any(part.lower() in ('licenses', 'license') for part in file.parts)
            or file.name.lower().startswith(('license', 'copying', 'notice'))):
            source = distribution.locate_file(file)
            if source.is_file():
                datas.append((str(source), str(Path('licenses') / name / file.parent)))
python_license = Path(sys.base_prefix) / 'LICENSE.txt'
if python_license.exists():
    datas.append((str(python_license), 'licenses/Python'))

a = Analysis([str(ROOT / 'run.py')], pathex=[str(ROOT)], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, hookspath=[],
             excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
                       'PySide6.QtQml', 'PySide6.QtQuick', 'tkinter', 'pytest'],
             noarchive=False)
a.binaries = [entry for entry in a.binaries
              if Path(entry[0]).name.lower() not in ('icuuc.dll', 'icuin.dll', 'icu.dll')]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='item-40',
          console=False, debug=False, strip=False, upx=False,
          version=str(ROOT / 'packaging/version.txt'), icon=str(ROOT / 'packaging/app.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='item-40')
