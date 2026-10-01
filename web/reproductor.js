'use strict';
const $ = selector => document.querySelector(selector);
const audio = $('#audio');
let songs = [], groups = [], current = null, expanded = null, version = 0, sourceVersion = 0;

function copy(template, texts) {
  const node = $(template).content.firstElementChild.cloneNode(true);
  for (const [selector, text] of Object.entries(texts)) node.querySelector(selector).textContent = text;
  return node;
}
function picture(img, url) {
  img.hidden = !url;
  img.onerror = () => { img.hidden = true; };
  if (url) img.src = url;
  else img.removeAttribute('src');
}
function time(seconds) {
  const value = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, '0')}`;
}
function notice(text = '', retry = null) {
  $('#message').textContent = text;
  $('#retry').hidden = !retry;
  $('#retry').onclick = retry;
}
function theme(night) {
  document.documentElement.dataset.theme = night ? 'night' : 'day';
  $('#theme use').setAttribute('href', night ? '#sun' : '#moon');
  $('#theme').title = $('#theme').ariaLabel = night ? 'Activar modo día' : 'Activar modo noche';
  try { localStorage.setItem('rola-theme', night ? 'night' : 'day'); } catch { /* Guardar es opcional. */ }
}
try { theme(localStorage.getItem('rola-theme') === 'night'); } catch { theme(false); }
$('#theme').onclick = () => theme(document.documentElement.dataset.theme !== 'night');
$('#mode').onclick = () => {
  const library = $('#library').hidden;
  $('#library').hidden = !library;
  document.body.dataset.view = library ? 'library' : 'player';
  $('#mode-label').textContent = library ? 'Reproductor' : 'Biblioteca';
  if (library) placeDetail();
  $(library ? '#library-title' : '#title').focus({ preventScroll: true });
  window.scrollTo({ top: 0, behavior: 'instant' });
};
function progress() {
  const duration = Number.isFinite(audio.duration) ? audio.duration : current?.duration_seconds || 0;
  $('#seek').max = duration || 1;
  $('#seek').value = audio.currentTime;
  $('#seek').disabled = !current || !Number.isFinite(audio.duration);
  $('#seek').setAttribute('aria-valuetext', `${time(audio.currentTime)} de ${time(duration)}`);
  $('#elapsed').textContent = time(audio.currentTime);
  $('#remaining').textContent = `−${time(duration - audio.currentTime)}`;
}
function controls(event) {
  if (event) document.body.dataset.playing = String(event.type === 'playing');
  $('.toggle').ariaLabel = audio.paused ? 'Reproducir' : 'Pausar';
  $('.toggle use').setAttribute('href', audio.paused ? '#play' : '#pause');
  document.querySelectorAll('.track').forEach(button => button.setAttribute('aria-current', String(button.dataset.song === current?.id)));
}
async function choose(song = current, start = true, retry = false) {
  if (!song) return;
  const request = start || song.id !== current?.id || retry ? ++version : version;
  const position = retry ? audio.currentTime : 0;
  if (song.id !== current?.id || retry || (start && audio.error)) {
    const loading = ++sourceVersion;
    audio.pause();
    audio.src = song.audio_url;
    audio.load();
    audio.onloadedmetadata = () => {
      if (loading === sourceVersion && Number.isFinite(audio.duration)) audio.currentTime = Math.min(position, audio.duration);
      audio.onloadedmetadata = null;
    };
  }
  current = song;
  $('#player').dataset.ready = 'true';
  $('#title').textContent = song.title;
  $('#artist').textContent = song.artist;
  picture($('#cover'), song.cover_url);
  $('.disc').ariaLabel = song.cover_url ? `Portada de ${song.title}` : 'CD sin portada';
  $('.toggle').disabled = false;
  $('#previous-track').disabled = $('#next-track').disabled = !songs.length;
  controls();
  progress();
  if (!start) return;
  notice();
  try { await audio.play(); }
  catch (error) {
    if (request === version && error.name !== 'AbortError') notice('No se pudo reproducir la canción.', () => choose(current, true, true));
  }
}
function next(direction) {
  if (!songs.length) return;
  if (direction < 0 && audio.currentTime > 3) audio.currentTime = 0;
  else {
    let index = songs.findIndex(song => song.id === current?.id);
    if (index < 0) index = direction > 0 ? -1 : 0;
    choose(songs[(index + direction + songs.length) % songs.length]);
  }
}
$('.toggle').onclick = () => {
  if (audio.paused) choose();
  else { ++version; audio.pause(); }
};
$('#previous-track').onclick = () => next(-1);
$('#next-track').onclick = () => next(1);
$('#seek').oninput = event => {
  if (Number.isFinite(audio.duration)) audio.currentTime = Number(event.target.value);
  progress();
};
['timeupdate', 'durationchange', 'loadedmetadata', 'emptied'].forEach(event => audio.addEventListener(event, progress));
['play', 'playing', 'pause', 'waiting', 'ended', 'emptied', 'error'].forEach(event => audio.addEventListener(event, controls));
audio.onended = () => next(1);
audio.onerror = () => {
  if (audio.error && current) notice('La canción no está disponible.', () => choose(current, true, true));
};

function placeDetail() {
  if (!expanded || $('#library').hidden) return;
  const buttons = [...$('#albums').querySelectorAll('.album')];
  const columns = getComputedStyle($('#albums')).gridTemplateColumns.split(' ').length;
  const end = Math.min(buttons.length - 1, Math.floor(buttons.indexOf(expanded) / columns) * columns + columns - 1);
  buttons[end].after($('#album-detail'));
}
function openAlbum(button = null, restoreFocus = true) {
  if (expanded) expanded.setAttribute('aria-expanded', 'false');
  if (!button || button === expanded) {
    $('#album-detail').hidden = true;
    if (restoreFocus) expanded?.focus({ preventScroll: true });
    expanded = null;
    return;
  }
  expanded = button;
  const group = groups[button.dataset.album];
  button.setAttribute('aria-expanded', 'true');
  $('#album-title').textContent = group[0].album || group[0].title;
  $('#album-artist').textContent = group[0].artist;
  $('#tracks').replaceChildren(...group.map((song, index) => {
    const row = copy('#track-template', { '.track-number': index + 1, '.track-title': song.title, '.track-length': time(song.duration_seconds) });
    row.querySelector('button').dataset.song = song.id;
    return row;
  }));
  placeDetail();
  $('#album-detail').hidden = false;
  controls();
}
$('#albums').onclick = event => {
  const album = event.target.closest('[data-album]');
  const track = event.target.closest('[data-song]');
  if (album) openAlbum(album);
  if (track) choose(songs.find(song => song.id === track.dataset.song));
};
$('#close-album').onclick = () => openAlbum();
$('#album-detail').onkeydown = event => { if (event.key === 'Escape') openAlbum(); };
window.addEventListener('resize', placeDetail);
function renderLibrary() {
  openAlbum(null, false);
  $('#library').append($('#album-detail'));
  const grouped = new Map();
  for (const song of songs) {
    const key = song.album ? JSON.stringify([song.album.toLowerCase(), song.artist.toLowerCase()]) : song.id;
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(song);
  }
  groups = [...grouped.values()];
  $('#albums').replaceChildren(...groups.map((group, index) => {
    const button = copy('#album-template', { '.album-title': group[0].album || group[0].title, '.album-artist': group[0].artist });
    button.dataset.album = index;
    picture(button.querySelector('img'), group.find(song => song.cover_url)?.cover_url);
    return button;
  }));
  $('#count').textContent = `${groups.length} discos · ${songs.length} canciones`;
}
async function loadCatalog() {
  if ($('#refresh').disabled) return;
  $('#refresh').disabled = true;
  notice('Cargando tu música…');
  try {
    const response = await fetch('/api/songs', { signal: AbortSignal.timeout(15000), cache: 'no-store' });
    if (!response.ok) throw new Error('API no disponible');
    const data = await response.json();
    const ids = new Set();
    if (!Array.isArray(data)) throw new Error('Catálogo no válido');
    for (const song of data) {
      if (!song || typeof song.id !== 'string' || !/^[a-f0-9]{24}$/.test(song.id) || ids.has(song.id) ||
          !['title', 'artist', 'album'].every(key => typeof song[key] === 'string') ||
          !Number.isFinite(song.duration_seconds) || song.duration_seconds < 0 ||
          song.audio_url !== `/api/songs/${song.id}/audio` ||
          (song.cover_url !== null && song.cover_url !== `/api/songs/${song.id}/cover`)) throw new Error('Canción no válida');
      ids.add(song.id);
    }
    songs = data;
    renderLibrary();
    choose(songs.find(song => song.id === current?.id) || current || songs[0], false);
    notice(songs.length ? '' : 'Tu biblioteca está vacía. Añade canciones a mp3/.', songs.length ? null : loadCatalog);
  } catch { notice('No se pudo cargar la biblioteca. Comprueba la conexión.', loadCatalog); }
  finally { $('#refresh').disabled = false; }
}
$('#refresh').onclick = loadCatalog;
loadCatalog();
