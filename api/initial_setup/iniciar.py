import base64
import os
from pathlib import Path
import subprocess
import sys

base = Path(__file__).resolve().parents[2]
python = base / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
if sys.version_info < (3, 12):
    sys.exit('[rola] Python 3.12 or newer is required.')
if sys.argv[1:]:
    sys.exit('Usage: py api/initial_setup/iniciar.py')
print('\n  rola / setup\n', flush=True)
try:
    print('  [1/3] Preparing your environment...', flush=True)
    if not python.is_file():
        subprocess.run([sys.executable, '-m', 'venv', str(base / '.venv')], check=True)
    check = "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 'The existing .venv needs Python 3.12+. Remove .venv and run setup again.')"
    subprocess.run([str(python), '-I', '-c', check], check=True)
    print('  [2/3] Installing the music engine...', flush=True)
    subprocess.run([str(python), '-m', 'pip', 'install', '--quiet',
                    'fastapi==0.141.1', 'uvicorn==0.53.0', 'mutagen==1.48.1',
                    'starlette==1.7.0'], check=True)
    subprocess.run([str(python), '-m', 'pip', 'check'], check=True)
    (base / 'mp3').mkdir(exist_ok=True)
    if os.name == 'nt':
        print('  [3/3] Enabling home-network listening. Approve the Windows prompt.', flush=True)

        probe = (
            "import ctypes; b=ctypes.create_unicode_buffer(32768); "
            "n=ctypes.windll.kernel32.GetModuleFileNameW(None,b,len(b)); "
            "assert 0 < n < len(b), 'Cannot locate Python'; print(b.value)"
        )
        program = Path(subprocess.check_output([str(python), '-I', '-X', 'utf8', '-c', probe],
                                              encoding='utf-8').strip()).with_name('pythonw.exe')
        if not program.is_file():
            sys.exit('[rola] This Python installation is missing pythonw.exe.')
        program = str(program).replace("'", "''")
        rule = (
            "$ErrorActionPreference='Stop'; try { "
            "Get-NetFirewallRule -Name 'rola-LAN' -ErrorAction SilentlyContinue | Remove-NetFirewallRule; "
            "New-NetFirewallRule -Name 'rola-LAN' -DisplayName 'rola LAN' "
            "-Direction Inbound -Action Allow -Enabled True -Protocol TCP -LocalPort 8000 "
            f"-Profile Private -RemoteAddress LocalSubnet -Program '{program}' | Out-Null; exit 0 "
            "} catch { Write-Error $_; exit 1 }"
        )
        encoded = base64.b64encode(rule.encode('utf-16le')).decode('ascii')
        elevate = (
            "$ErrorActionPreference='Stop'; try { $p = Start-Process powershell.exe -Verb RunAs "
            f"-Wait -PassThru -ArgumentList '-NoProfile -NonInteractive -EncodedCommand {encoded}'; "
            "exit $p.ExitCode } catch { exit 1 }"
        )
        result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', elevate])
        if result.returncode:
            sys.exit('[rola] Engine installed; LAN permission was not granted. Run setup again to enable it.')
except (OSError, subprocess.CalledProcessError) as error:
    sys.exit(f'[rola] Setup did not finish: {error}')
print('\n  Ready. Add songs to mp3/, then run: py api/servidor.py\n')
