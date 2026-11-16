"""Verify Inno's upgrade path under a separate AppId, without touching real installations.

Requires the previous dist/Masterskaya/Masterskaya.exe and the current dist/item-40 build.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts" / "upgrade-verification"
TEST_ID = "item40-upgrade-verification"


def execute(args, *, timeout=180):
    result = subprocess.run([str(arg) for arg in args], capture_output=True,
                            creationflags=subprocess.CREATE_NO_WINDOW, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"Exit {result.returncode}: " + result.stdout.decode("utf8", errors="replace")
                           + result.stderr.decode("utf8", errors="replace"))
    return result


def main():
    import winreg
    sys.stdout.reconfigure(encoding="utf8")
    compiler = Path(sys.argv[1]).resolve()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    old_exe = ROOT / "dist" / "Masterskaya" / "Masterskaya.exe"
    assert old_exe.is_file()
    old_dir = ARTIFACTS / "existing-install"
    new_default = ARTIFACTS / "new-default"
    registry_path = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{TEST_ID}_is1"

    def installed_version():
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry_path, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            return winreg.QueryValueEx(key, "DisplayVersion")[0]

    # The fixture's old application uses the real 0.1.0 binary and a dedicated uninstall key.
    baseline = ARTIFACTS / "baseline.iss"
    baseline.write_text(f'''[Setup]
AppId={TEST_ID}
AppName=item-40 upgrade verification
AppVersion=0.1.0
DefaultDirName={old_dir}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=item-40 upgrade verification
OutputDir={ARTIFACTS}
OutputBaseFilename=baseline
Compression=lzma2
SolidCompression=yes
[Files]
Source: "{old_exe}"; DestDir: "{{app}}"; Flags: ignoreversion
''', encoding="utf-8-sig")
    execute([compiler, "/Q", baseline])
    execute([compiler, "/Q", f"/DTestAppId={TEST_ID}", f"/DTestDefaultDir={new_default}",
             f"/O{ARTIFACTS}", "/Fupdate", ROOT / "packaging" / "installer.iss"])
    silent = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOICONS"]
    data = ARTIFACTS / "profile"
    data.mkdir(exist_ok=True)
    history = data / "history.marker"
    model = data / "models" / "model.marker"
    model.parent.mkdir(exist_ok=True)
    history.write_bytes(b"history must survive")
    model.write_bytes(b"model must survive")
    hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (history, model)}
    try:
        execute([ARTIFACTS / "baseline.exe", *silent, f"/DIR={old_dir}"])
        assert installed_version() == "0.1.0"
        assert (old_dir / "Masterskaya.exe").exists()
        # No /DIR is passed here: the updated installer must reuse the previous path.
        execute([ARTIFACTS / "update.exe", *silent])
        assert installed_version() == "0.2.0"
        assert (old_dir / "item-40.exe").is_file()
        assert not (old_dir / "Masterskaya.exe").exists()
        assert not (new_default / "item-40.exe").exists()
        assert all(hashlib.sha256(path.read_bytes()).hexdigest() == value for path, value in hashes.items())
        report = {"from": "0.1.0", "to": "0.2.0", "same_directory": True,
                  "old_executable_removed": True, "history_and_models_preserved": True}
        (ARTIFACTS / "report.json").write_text(json.dumps(report, indent=2), encoding="utf8")
        print("Upgrade 0.1.0 -> 0.2.0: PASS", flush=True)
    finally:
        # Only uninstall our dedicated test AppId from paths under the workspace.
        for folder in (old_dir, new_default):
            assert folder.resolve().is_relative_to(ARTIFACTS.resolve())
            uninstaller = folder / "unins000.exe"
            if uninstaller.is_file():
                execute([uninstaller, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])


if __name__ == "__main__":
    main()
