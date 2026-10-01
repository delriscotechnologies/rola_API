import os
from pathlib import Path

if __name__ == '__main__':
    import errno
    import socket
    import subprocess
    import sys
    from threading import Thread
    import time
    from uuid import uuid4

    base = Path(__file__).resolve().parents[1]
    state = base / '.rola'
    state.mkdir(exist_ok=True)
    ready = state / 'ready'
    active = state / 'session'
    stop = state / 'stop'

    def read(path):
        try:
            return path.read_text()
        except FileNotFoundError:
            return ''

    def acquire():
        file = (state / 'lock').open('a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return file
        except OSError as error:
            file.close()
            if error.errno not in (errno.EACCES, errno.EAGAIN):
                raise
            return None

    def run():
        args = sys.argv[1:]
        if args not in ([], ['stop']) and not (len(args) == 2 and args[0] == '--worker'):
            sys.exit('Usage: py api/servidor.py [stop]')
        file = acquire()
        if args == ['stop']:
            for _ in range(100):
                if file:
                    file.close()
                    print('[rola] Stopped.')
                    return
                token = read(active)
                if token:
                    stop.write_text(token)
                time.sleep(0.1)
                file = acquire()
            sys.exit('[rola] Still stopping. Check rola.log.')
        if not file:
            sys.exit('[rola] Already running. Stop with: py api/servidor.py stop')
        if args:
            with file:
                ready.unlink(missing_ok=True)
                active.write_text(args[1])
                if os.name == 'nt':
                    sys.stdout = sys.stderr = (base / 'rola.log').open('a', encoding='utf-8')
                import uvicorn
                sys.path.insert(0, str(base))
                server = uvicorn.Server(uvicorn.Config('api.servidor:app', host='0.0.0.0', port=8000,
                                                       access_log=False, timeout_graceful_shutdown=5))
                def monitor():
                    while not server.should_exit:
                        if read(stop) == args[1]:
                            server.should_exit = True
                            return
                        if server.started and read(ready) != args[1]:
                            temporary = state / 'ready.tmp'
                            temporary.write_text(args[1])
                            temporary.replace(ready)
                        time.sleep(0.2)
                Thread(target=monitor, daemon=True).start()
                server.run()
            return
        file.close()
        python = base / '.venv' / ('Scripts/pythonw.exe' if os.name == 'nt' else 'bin/python')
        if not python.is_file():
            sys.exit('[rola] Run setup first: py api/initial_setup/iniciar.py')
        try:
            addresses = sorted({item[4][0] for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
                                if not item[4][0].startswith('127.')})
        except socket.gaierror:
            addresses = []
        hosts = ['localhost', '127.0.0.1', socket.gethostname(), *addresses]
        hosts += [host.strip() for host in os.getenv('ROLA_HOSTS', '').split(',') if host.strip()]
        token = uuid4().hex
        options = {'creationflags': subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
        print('\n  rola / starting the music engine...', flush=True)
        with (base / 'rola.log').open('a') as log:
            process = subprocess.Popen([str(python), str(Path(__file__).resolve()), '--worker', token],
                                       cwd=base, env={**os.environ, 'ROLA_HOSTS': ','.join(hosts)},
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=log, **options)
        deadline = time.monotonic() + 30
        while read(ready) != token:
            if process.poll() is not None:
                sys.exit('[rola] Engine exited before it was ready. See rola.log.')
            if time.monotonic() >= deadline:
                sys.exit('[rola] Still starting. See rola.log; use py api/servidor.py stop to cancel.')
            time.sleep(0.1)
        print('  ON AIR\n\n  This computer  http://localhost:8000')
        for address in addresses:
            print(f'  Your network   http://{address}:8000')
        print('\n  You can close PowerShell. Open an address in your browser to listen.')
        print('  Stop with: py api/servidor.py stop\n')

    try:
        run()
    except OSError as error:
        sys.exit(f'[rola] {error}')
    sys.exit()

import hashlib
import logging
import stat as file_stat
from contextlib import asynccontextmanager
from threading import Lock

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from mutagen import MutagenError
from mutagen.mp3 import MP3
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

log = logging.getLogger("rola")
file_headers = {
    "X-Content-Type-Options": "nosniff", "Cache-Control": "no-cache",
    "Cross-Origin-Resource-Policy": "same-origin",
}
root = Path(os.getenv("ROLA_MUSIC_DIR") or Path(__file__).resolve().parents[1] / "mp3").expanduser().resolve()
library = {}
lock = Lock()


class Song(BaseModel):
    id: str
    title: str
    artist: str
    album: str
    duration_seconds: float = Field(ge=0, allow_inf_nan=False)
    audio_url: str
    cover_url: str | None


def artwork(audio):
    pictures = audio.tags.getall("APIC") if audio.tags else []
    for picture in sorted(pictures, key=lambda item: item.type != 3):
        if picture.data.startswith(b"\x89PNG\r\n\x1a\n"):
            return picture.data, "image/png"
        if picture.data.startswith(b"\xff\xd8\xff"):
            return picture.data, "image/jpeg"
    return None


def opened_path(file):
    if os.name != "nt":
        return Path(os.readlink(f"/proc/self/fd/{file.fileno()}"))
    import ctypes
    import msvcrt
    from ctypes import wintypes

    get_path = ctypes.WinDLL("kernel32", use_last_error=True).GetFinalPathNameByHandleW
    get_path.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    get_path.restype = wintypes.DWORD
    handle = msvcrt.get_osfhandle(file.fileno())
    size = get_path(handle, None, 0, 0)
    buffer = ctypes.create_unicode_buffer(size + 1)
    result = get_path(handle, buffer, len(buffer), 0)
    if not size or not result or result >= len(buffer):
        raise OSError("No se pudo validar el archivo abierto.")
    name = buffer.value
    return Path('\\\\' + name[8:] if name.startswith('\\\\?\\UNC\\') else name.removeprefix('\\\\?\\'))


def fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def open_local(path, root, expected=None):
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    file = os.fdopen(os.open(path, flags), "rb")
    try:
        info = os.fstat(file.fileno())
        destination = opened_path(file)
        if (not file_stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or not destination.is_relative_to(root) or destination != path.absolute()):
            raise OSError("Archivo fuera de la biblioteca o no regular.")
        if expected is not None and fingerprint(info) != expected:
            raise OSError("La canción cambió desde la última lectura del catálogo.")
        return file
    except BaseException:
        file.close()
        raise


class FileHandle:
    def __init__(self, file):
        self.file = file

    def __index__(self):
        return os.dup(self.file.fileno())


class AudioResponse(FileResponse):
    def __init__(self, path, expected):
        super().__init__(path, media_type="audio/mpeg", filename=path.name,
                         content_disposition_type="inline", headers=file_headers)
        self.expected = expected

    async def __call__(self, scope, receive, send):
        try:
            file = await run_in_threadpool(open_local, self.path, root, self.expected)
        except OSError:
            raise HTTPException(404, "Canción no disponible.") from None
        with file:
            self.path = FileHandle(file)
            self.stat_result = os.fstat(file.fileno())
            self.set_stat_headers(self.stat_result)

            await super().__call__({**scope, "extensions": {}}, receive, send)


def files():
    def warn(error):
        log.warning("Catálogo incompleto: %s", type(error).__name__)
        raise HTTPException(503, "No se pudo leer toda la carpeta de música.") from error

    for directory, folders, names in os.walk(root, followlinks=False, onerror=warn):
        base = Path(directory)
        folders[:] = [
            name for name in folders
            if not (base / name).is_symlink() and not (base / name).is_junction()
            and (base / name).resolve().is_relative_to(root)
        ]
        for name in names:
            candidate = base / name
            if candidate.suffix.lower() == ".mp3" and not candidate.is_symlink():
                yield candidate

def scan():
    with lock:
        if not root.is_dir() or root.resolve() != root:
            raise HTTPException(503, "La carpeta de música no está disponible.")
        current = {}
        for candidate in files():
            try:
                relative = candidate.relative_to(root).as_posix()
                song_id = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:24]
                with open_local(candidate, root) as file:
                    stamp = fingerprint(os.fstat(file.fileno()))
                    previous = library.get(song_id)
                    if previous and previous[1] == stamp:
                        current[song_id] = previous
                        continue
                    audio = MP3(file)
                    if fingerprint(os.fstat(file.fileno())) != stamp:
                        raise OSError("La canción cambió durante la lectura.")
                tags = audio.tags or {}

                def tag(key, fallback=""):
                    return str(tags.get(key, "")).strip() or fallback

                song = Song(
                    id=song_id,
                    title=tag("TIT2", candidate.stem),
                    artist=tag("TPE1", "Artista desconocido"),
                    album=tag("TALB"),
                    duration_seconds=round(audio.info.length, 3),
                    audio_url=f"/api/songs/{song_id}/audio",
                    cover_url=f"/api/songs/{song_id}/cover" if artwork(audio) else None,
                )
                current[song_id] = (candidate, stamp, song)
            except (OSError, RuntimeError, ValueError, MutagenError) as exc:
                log.warning("MP3 omitido: %r (%s: %r)", candidate.name, type(exc).__name__, str(exc))
        library.clear()
        library.update(current)
        return sorted(
            (entry[2] for entry in current.values()),
            key=lambda song: (song.artist.casefold(), song.title.casefold(), song.id),
        )

def locate(song_id):
    with lock:
        entry = library.get(song_id)
    if not entry:
        raise HTTPException(404, "Canción no disponible.")
    return entry


@asynccontextmanager
async def lifespan(app):
    await run_in_threadpool(scan)
    yield

app = FastAPI(
    title="rola API", version="0.1.0", lifespan=lifespan,
    docs_url="/docs" if os.getenv("ROLA_DOCS") == "1" else None, redoc_url=None,
    description="Tu catálogo de MP3, portadas y audio en tu red de casa.",
)

app.add_middleware(
    TrustedHostMiddleware, www_redirect=False,
    allowed_hosts=[host.strip() for host in os.getenv("ROLA_HOSTS", "localhost,127.0.0.1,[::1]").split(",")],
)

web = Path(__file__).resolve().parent.parent / "web"
headers = {
    "Content-Security-Policy": "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
    **file_headers,
    "Referrer-Policy": "no-referrer",
}
assets = {
    url: Response((web / name).read_bytes(), media_type=mime, headers=headers)
    for url, name, mime in [
        ("/", "index.html", "text/html"),
        ("/estilos.css", "estilos.css", "text/css"),
        ("/reproductor.js", "reproductor.js", "text/javascript"),
    ]
}

def website(request: Request):
    return assets[request.scope["path"]]

for url in assets:
    app.add_api_route(url, website, methods=["GET"], include_in_schema=False)

app.add_api_route("/api/songs", scan, response_model=list[Song], summary="Listar canciones")

@app.head("/api/songs/{song_id}/audio", include_in_schema=False)
@app.get("/api/songs/{song_id}/audio", response_class=FileResponse, summary="Escuchar una canción")
def audio(song_id: str):
    path, stamp, _ = locate(song_id)
    return AudioResponse(path, stamp)

@app.get("/api/songs/{song_id}/cover", summary="Obtener la portada")
def cover(song_id: str):
    path, stamp, _ = locate(song_id)
    try:
        with open_local(path, root, stamp) as file:
            picture = artwork(MP3(file))
    except (OSError, ValueError, MutagenError):
        raise HTTPException(404, "Canción no disponible.") from None
    if picture is None:
        raise HTTPException(404, "Esta canción no tiene una portada compatible.")
    data, mime = picture
    return Response(data, media_type=mime, headers=file_headers)
