const names = [document.querySelector('#font-name-1'), document.querySelector('#font-name-2')];
const samples = [document.querySelector('#code-1'), document.querySelector('#code-2')];
const fontSizeInput = document.querySelector('#code-font-size');
const resizeHandle = document.querySelector('.resize-handle');
const loading = document.querySelector('#loading');
const rankingsBody = document.querySelector('#rankings');
const previewDialog = document.querySelector('#font-preview');
const previewTitle = document.querySelector('#preview-title');
const previewStatus = document.querySelector('#preview-status');
const previewCode = document.querySelector('#preview-code');
const previewClose = document.querySelector('#preview-close');
const voteCount = document.querySelector('#vote-count');
const toast = document.querySelector('#toast');
let currentPair = null;
let busy = true;
let lastSnippet = '';
let syncingScroll = false;
let codeFontSize = null;
let codeWindowHeight = null;
let showAllNames = false;
let previewRequest = 0;
let previewTrigger = null;
const previewFontFaces = new Map();

const minCodeWindowHeight = 140;
const maxCodeWindowHeight = 1200;

const cKeywords = new Set([
  'auto', 'break', 'case', 'const', 'continue', 'default', 'do', 'else', 'enum',
  'extern', 'for', 'goto', 'if', 'register', 'return', 'sizeof', 'static',
  'struct', 'switch', 'typedef', 'union', 'volatile', 'while', '_Alignas',
  '_Alignof', '_Atomic', '_Generic', '_Noreturn', '_Static_assert', '_Thread_local',
]);
const cTypes = new Set([
  'bool', 'char', 'double', 'float', 'int', 'long', 'short', 'signed', 'unsigned',
  'void', 'size_t', 'int8_t', 'int16_t', 'int32_t', 'int64_t', 'uint8_t',
  'uint16_t', 'uint32_t', 'uint64_t', 'Point',
]);
const cTokenPattern = /\/\/.*$|\/\*.*?\*\/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\b[A-Za-z_]\w*\b|\b(?:0[xX][0-9A-Fa-f]+|\d+(?:\.\d+)?)\w*\b|(?:>>=|<<=|==|!=|<=|>=|&&|\|\||\+\+|--|->|<<|>>|[+\-*/%=<>!&|^~?:])/g;

function tokenClass(token, index, source) {
  if (token.startsWith('//') || token.startsWith('/*')) return 'comment';
  if (token.startsWith('"') || token.startsWith("'")) return 'str';
  if (cKeywords.has(token)) return 'kw';
  if (cTypes.has(token)) return 'type';
  if (/^(?:0[xX][0-9A-Fa-f]+|\d)/.test(token)) return 'num';
  if (/^[+\-*/%=<>!&|^~?:]/.test(token)) return 'op';
  if (/^[A-Za-z_]\w*$/.test(token) && /^\s*\(/.test(source.slice(index + token.length))) return 'fn';
  return '';
}

function colorizeC(text) {
  const fragment = document.createDocumentFragment();
  if (/^\s*#/.test(text)) {
    const directive = document.createElement('span');
    directive.className = 'pp';
    directive.textContent = text;
    fragment.append(directive);
    return fragment;
  }
  let cursor = 0;
  for (const match of text.matchAll(cTokenPattern)) {
    if (match.index > cursor) fragment.append(document.createTextNode(text.slice(cursor, match.index)));
    const className = tokenClass(match[0], match.index, text);
    if (className) {
      const token = document.createElement('span');
      token.className = className;
      token.textContent = match[0];
      fragment.append(token);
    } else {
      fragment.append(document.createTextNode(match[0]));
    }
    cursor = match.index + match[0].length;
  }
  if (cursor < text.length) fragment.append(document.createTextNode(text.slice(cursor)));
  return fragment;
}

function renderSnippet(source) {
  const fragment = document.createDocumentFragment();
  source.replace(/\s+$/, '').split('\n').forEach((text, index) => {
    const line = document.createElement('span');
    line.className = 'line';
    const number = document.createElement('span');
    number.className = 'ln';
    number.textContent = String(index + 1);
    const content = document.createElement('span');
    content.className = 'code-text';
    content.append(text ? colorizeC(text) : document.createTextNode(' '));
    line.append(number, content);
    fragment.append(line);
  });
  return fragment;
}

function synchronizeScroll(source, target) {
  if (syncingScroll) return;
  syncingScroll = true;
  const sourceVerticalRange = source.scrollHeight - source.clientHeight;
  const targetVerticalRange = target.scrollHeight - target.clientHeight;
  const sourceHorizontalRange = source.scrollWidth - source.clientWidth;
  const targetHorizontalRange = target.scrollWidth - target.clientWidth;
  target.scrollTop = sourceVerticalRange > 0
    ? (source.scrollTop / sourceVerticalRange) * targetVerticalRange
    : 0;
  target.scrollLeft = sourceHorizontalRange > 0
    ? (source.scrollLeft / sourceHorizontalRange) * targetHorizontalRange
    : 0;
  requestAnimationFrame(() => { syncingScroll = false; });
}

function setCodeFontSize(size, syncInput = true) {
  const previousSize = codeFontSize ?? parseFloat(getComputedStyle(samples[0]).fontSize);
  const scrollPositions = samples.map(sample => sample.scrollTop / previousSize);
  codeFontSize = Math.min(72, Math.max(8, size));
  samples.forEach((sample, index) => {
    sample.style.fontSize = `${codeFontSize}px`;
    sample.scrollTop = scrollPositions[index] * codeFontSize;
  });
  if (syncInput) fontSizeInput.value = String(codeFontSize);
}

function resizeCode(delta) {
  setCodeFontSize((codeFontSize ?? parseFloat(getComputedStyle(samples[0]).fontSize)) + delta);
  showToast(`Code size: ${codeFontSize}px`);
}

fontSizeInput.value = String(parseFloat(getComputedStyle(samples[0]).fontSize));
fontSizeInput.addEventListener('input', () => {
  if (fontSizeInput.validity.valid && Number.isFinite(fontSizeInput.valueAsNumber)) {
    setCodeFontSize(fontSizeInput.valueAsNumber, false);
  }
});
fontSizeInput.addEventListener('change', () => {
  if (Number.isFinite(fontSizeInput.valueAsNumber)) {
    setCodeFontSize(fontSizeInput.valueAsNumber);
  } else {
    fontSizeInput.value = String(codeFontSize ?? parseFloat(getComputedStyle(samples[0]).fontSize));
  }
});

function setCodeWindowHeight(height) {
  codeWindowHeight = Math.round(Math.min(maxCodeWindowHeight, Math.max(minCodeWindowHeight, height)));
  samples.forEach(sample => {
    sample.style.maxHeight = 'none';
    sample.style.height = `${codeWindowHeight}px`;
  });
  resizeHandle.setAttribute('aria-valuenow', String(codeWindowHeight));
}

function ensureCodeWindowHeight() {
  if (codeWindowHeight === null) {
    setCodeWindowHeight(Math.max(...samples.map(sample => sample.getBoundingClientRect().height)));
  }
}

let resizeDrag = null;
resizeHandle.addEventListener('pointerdown', event => {
  if (event.button !== 0) return;
  event.preventDefault();
  ensureCodeWindowHeight();
  resizeHandle.focus();
  resizeDrag = { pointerId: event.pointerId, y: event.clientY, height: codeWindowHeight };
  resizeHandle.setPointerCapture(event.pointerId);
});
resizeHandle.addEventListener('pointermove', event => {
  if (resizeDrag?.pointerId === event.pointerId) setCodeWindowHeight(resizeDrag.height + event.clientY - resizeDrag.y);
});
resizeHandle.addEventListener('pointerup', event => {
  if (resizeDrag?.pointerId === event.pointerId) resizeDrag = null;
});
resizeHandle.addEventListener('pointercancel', event => {
  if (resizeDrag?.pointerId === event.pointerId) resizeDrag = null;
});
resizeHandle.addEventListener('keydown', event => {
  if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return;
  event.preventDefault();
  ensureCodeWindowHeight();
  setCodeWindowHeight(codeWindowHeight + (event.key === 'ArrowDown' ? 20 : -20));
});

samples[0].addEventListener('scroll', () => synchronizeScroll(samples[0], samples[1]), { passive: true });
samples[1].addEventListener('scroll', () => synchronizeScroll(samples[1], samples[0]), { passive: true });

async function refreshSnippet() {
  const response = await fetch(`/snippet.c?t=${Date.now()}`, { cache: 'no-store' });
  if (!response.ok) throw new Error('Could not load snippet.c');
  const source = await response.text();
  if (source === lastSnippet) return;
  lastSnippet = source;
  samples.forEach(sample => sample.replaceChildren(renderSnippet(source)));
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.add('show');
  window.setTimeout(() => toast.classList.remove('show'), 3000);
}

function setLoading(isLoading) {
  busy = isLoading;
  loading.classList.toggle('show', isLoading);
}

function renderRanking(state) {
  voteCount.textContent = state.totalVotes.toLocaleString();
  rankingsBody.replaceChildren(...state.ranking.map(row => {
    const tr = document.createElement('tr');
    if (!row.comparisons) tr.className = 'unseen';
    [String(row.rank).padStart(2, '0'), row.name, Math.round(row.rating).toLocaleString(), `${row.wins}–${row.losses}`, row.comparisons.toLocaleString()].forEach((value, index) => {
      const td = document.createElement('td');
      if (index === 1) {
        const button = document.createElement('button');
        button.className = 'ranking-font';
        button.type = 'button';
        button.textContent = value;
        button.addEventListener('click', () => openFontPreview(row, button));
        td.append(button);
      } else {
        td.textContent = value;
      }
      tr.append(td);
    });
    return tr;
  }));
}

async function loadPreviewFont(font) {
  let face = previewFontFaces.get(font.id);
  if (!face) {
    face = new FontFace(`RankedPreview_${font.id}`, `url("${font.fontUrl}") format("${font.format}")`);
    previewFontFaces.set(font.id, face);
  }
  try {
    await face.load();
    document.fonts.add(face);
    return face.family;
  } catch (error) {
    previewFontFaces.delete(font.id);
    throw error;
  }
}

async function openFontPreview(row, trigger) {
  const request = ++previewRequest;
  previewTrigger = trigger;
  previewTitle.textContent = row.name;
  previewStatus.textContent = 'Preparing font preview…';
  previewStatus.hidden = false;
  previewCode.replaceChildren();
  previewCode.style.fontFamily = 'monospace';
  previewCode.style.fontSize = getComputedStyle(samples[0]).fontSize;
  previewDialog.showModal();
  try {
    const [font] = await Promise.all([
      getJSON(`/api/font/${encodeURIComponent(row.id)}`),
      refreshSnippet(),
    ]);
    const family = await loadPreviewFont(font);
    if (request !== previewRequest || !previewDialog.open) return;
    previewCode.replaceChildren(renderSnippet(lastSnippet));
    previewCode.style.fontFamily = `"${family}", monospace`;
    previewStatus.hidden = true;
  } catch (error) {
    if (request !== previewRequest || !previewDialog.open) return;
    previewStatus.textContent = `Could not prepare preview: ${error.message}`;
  }
}

previewClose.addEventListener('click', () => previewDialog.close());
previewDialog.addEventListener('click', event => {
  if (event.target !== previewDialog) return;
  const bounds = previewDialog.getBoundingClientRect();
  if (event.clientX < bounds.left || event.clientX > bounds.right ||
      event.clientY < bounds.top || event.clientY > bounds.bottom) {
    previewDialog.close();
  }
});
previewDialog.addEventListener('close', () => {
  previewRequest += 1;
  previewTrigger?.focus();
});

function setFontNamesVisible(visible) {
  showAllNames = visible;
  names.forEach((name, index) => {
    name.textContent = visible ? currentPair[index].name : 'Font name hidden';
    name.classList.toggle('revealed', visible);
  });
}

async function getJSON(url, options) {
  const response = await fetch(url, options);
  if (!response.headers.get('content-type')?.includes('application/json')) {
    if (url.startsWith('/api/font/')) {
      throw new Error(`Font preview API returned HTTP ${response.status}. Restart the server and reload the page.`);
    }
    throw new Error(`Expected JSON from ${url} (HTTP ${response.status})`);
  }
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}

async function displayPair(pair) {
  const retainedScrollTop = samples[0].scrollTop;
  currentPair = pair;
  const style = document.createElement('style');
  style.textContent = currentPair.map((font, index) =>
    `@font-face{font-family:"Contender${index}";src:url("${font.fontUrl}") format("${font.format}");font-weight:400;font-style:normal;font-display:block}`
  ).join('\n');
  document.head.querySelectorAll('style[data-font-pair]').forEach(node => node.remove());
  style.dataset.fontPair = '';
  document.head.append(style);
  await Promise.all(currentPair.map((_, index) => document.fonts.load(`16px Contender${index}`)));
  currentPair.forEach((font, index) => {
    samples[index].style.fontFamily = `Contender${index}, monospace`;
  });
  setFontNamesVisible(showAllNames);
  ensureCodeWindowHeight();
  samples.forEach(sample => {
    sample.scrollTop = retainedScrollTop;
    sample.scrollLeft = 0;
  });
}

async function nextPair() {
  setLoading(true);
  try {
    const [, data] = await Promise.all([refreshSnippet(), getJSON('/api/pair')]);
    await displayPair(data.pair);
    setLoading(false);
  } catch (error) {
    showToast(error.message);
    loading.querySelector('strong').textContent = 'Could not prepare fonts';
    loading.querySelector('small').textContent = 'Check your network connection, then reload the page.';
  }
}

async function vote(index) {
  if (busy || !currentPair) return;
  setLoading(true);
  const winner = currentPair[index];
  const loser = currentPair[index === 0 ? 1 : 0];
  try {
    const state = await getJSON('/api/vote', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        winner: winner.id,
        loser: loser.id,
        pair: currentPair.map(font => font.id),
      }),
    });
    renderRanking(state);
    showToast('Choice recorded');
    await nextPair();
  } catch (error) {
    setLoading(false);
    showToast(error.message);
  }
}

async function pass() {
  if (busy || !currentPair) return;
  showToast('Matchup passed — rankings unchanged');
  await nextPair();
}

async function revisitPrevious() {
  if (busy) return;
  setLoading(true);
  try {
    const [, data] = await Promise.all([
      refreshSnippet(),
      getJSON('/api/undo', { method: 'POST' }),
    ]);
    renderRanking(data.state);
    await displayPair(data.pair);
    setLoading(false);
    showToast('Previous vote undone — choose again');
  } catch (error) {
    setLoading(false);
    showToast(error.message);
  }
}

window.addEventListener('keydown', event => {
  if (previewDialog.open || event.repeat || busy || event.target.matches('input, textarea, select')) return;
  if (event.key === '1' || event.key === 'ArrowLeft') { event.preventDefault(); vote(0); }
  if (event.key === '2' || event.key === 'ArrowRight') { event.preventDefault(); vote(1); }
  if (event.key.toLowerCase() === 'p') { event.preventDefault(); pass(); }
  if (event.key.toLowerCase() === 'u') { event.preventDefault(); revisitPrevious(); }
  if (event.key.toLowerCase() === 't' && currentPair) {
    event.preventDefault();
    setFontNamesVisible(!showAllNames);
  }
  if (event.key === '+' || event.key === '=') { event.preventDefault(); resizeCode(1); }
  if (event.key === '-') { event.preventDefault(); resizeCode(-1); }
});

async function start() {
  try {
    renderRanking(await getJSON('/api/state'));
    await nextPair();
  } catch (error) {
    showToast(error.message);
  }
}

start();
window.setInterval(() => refreshSnippet().catch(() => {}), 1500);
