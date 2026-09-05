const choices = [document.querySelector('#choice-1'), document.querySelector('#choice-2')];
const names = [document.querySelector('#font-name-1'), document.querySelector('#font-name-2')];
const revealButtons = names;
const samples = [document.querySelector('#code-1'), document.querySelector('#code-2')];
const loading = document.querySelector('#loading');
const rankingsBody = document.querySelector('#rankings');
const voteCount = document.querySelector('#vote-count');
const toast = document.querySelector('#toast');
let currentPair = null;
let busy = true;
let lastSnippet = '';
let syncingScroll = false;
let codeFontSize = null;

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

function resizeCode(delta) {
  const oldLineHeight = parseFloat(getComputedStyle(samples[0]).lineHeight);
  const visibleLine = oldLineHeight > 0 ? samples[0].scrollTop / oldLineHeight : 0;
  if (codeFontSize === null) codeFontSize = parseFloat(getComputedStyle(samples[0]).fontSize);
  codeFontSize = Math.min(32, Math.max(8, codeFontSize + delta));
  samples.forEach(sample => { sample.style.fontSize = `${codeFontSize}px`; });
  const newLineHeight = parseFloat(getComputedStyle(samples[0]).lineHeight);
  samples.forEach(sample => { sample.scrollTop = visibleLine * newLineHeight; });
  showToast(`Code size: ${codeFontSize}px`);
}

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
  choices.forEach(choice => {
    choice.setAttribute('aria-disabled', String(isLoading));
    choice.tabIndex = isLoading ? -1 : 0;
  });
}

function renderRanking(state) {
  voteCount.textContent = state.totalVotes.toLocaleString();
  rankingsBody.replaceChildren(...state.ranking.map(row => {
    const tr = document.createElement('tr');
    if (!row.comparisons) tr.className = 'unseen';
    [String(row.rank).padStart(2, '0'), row.name, Math.round(row.rating).toLocaleString(), `${row.wins}–${row.losses}`, row.comparisons.toLocaleString()].forEach(value => {
      const td = document.createElement('td');
      td.textContent = value;
      tr.append(td);
    });
    return tr;
  }));
}

async function getJSON(url, options) {
  const response = await fetch(url, options);
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
    names[index].textContent = 'Click to Reveal Font';
    revealButtons[index].disabled = false;
    revealButtons[index].classList.remove('revealed');
    samples[index].style.fontFamily = `Contender${index}, monospace`;
  });
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
    choices[0].focus({ preventScroll: true });
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

choices.forEach((button, index) => button.addEventListener('click', () => vote(index)));
choices.forEach((choice, index) => choice.addEventListener('keydown', event => {
  if (event.target !== choice) return;
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    vote(index);
  }
}));
revealButtons.forEach((button, index) => button.addEventListener('click', event => {
  event.stopPropagation();
  if (busy || !currentPair) return;
  names[index].textContent = currentPair[index].name;
  button.disabled = true;
  button.classList.add('revealed');
}));
window.addEventListener('keydown', event => {
  if (event.repeat || busy || event.target.matches('input, textarea, select')) return;
  if (event.key === '1' || event.key === 'ArrowLeft') { event.preventDefault(); vote(0); }
  if (event.key === '2' || event.key === 'ArrowRight') { event.preventDefault(); vote(1); }
  if (event.key.toLowerCase() === 'p') { event.preventDefault(); pass(); }
  if (event.key.toLowerCase() === 'u') { event.preventDefault(); revisitPrevious(); }
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
