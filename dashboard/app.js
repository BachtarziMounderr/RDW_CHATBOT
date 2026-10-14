const state = { data: null, track: 'all', search: '' };
const byId = (id) => document.getElementById(id);

function escapeText(value) {
  return String(value ?? '');
}

function formatDate(value, withTime = false) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('fr-FR', {
    day: '2-digit', month: 'short', year: 'numeric',
    ...(withTime ? { hour: '2-digit', minute: '2-digit' } : {})
  }).format(date);
}

function setText(id, value) { byId(id).textContent = escapeText(value); }

function renderMetrics() {
  const { metrics, faq_candidates: faq } = state.data;
  setText('metric-total', metrics.total);
  setText('metric-week', metrics.last_7_days);
  setText('metric-today', metrics.today);
  setText('metric-open', metrics.open_questions);
  setText('faq-count', faq);
  setText('distribution-total', metrics.total);
  setText('filter-all', metrics.total);
  state.data.distribution.forEach((item) => setText(`filter-${item.key}`, item.count));
}

function renderDistribution() {
  const container = byId('distribution-bars');
  container.replaceChildren();
  const maximum = Math.max(1, ...state.data.distribution.map((item) => item.count));
  state.data.distribution.forEach((item) => {
    const row = document.createElement('div');
    row.className = 'bar-row';
    row.dataset.track = item.key;
    const label = document.createElement('div');
    label.className = 'bar-label';
    const name = document.createElement('span');
    const count = document.createElement('span');
    name.textContent = item.label;
    count.textContent = String(item.count);
    label.append(name, count);
    const track = document.createElement('div');
    track.className = 'bar-track';
    const fill = document.createElement('div');
    fill.className = 'bar-fill';
    fill.style.width = `${(item.count / maximum) * 100}%`;
    track.append(fill);
    row.append(label, track);
    container.append(row);
  });
}

function filteredRecords() {
  const needle = state.search.trim().toLocaleLowerCase('fr');
  return state.data.records.filter((record) => {
    if (state.track !== 'all' && record.track !== state.track) return false;
    if (!needle) return true;
    const haystack = [record.name, record.phone, record.summary, ...record.facts.map((fact) => fact.value)].join(' ').toLocaleLowerCase('fr');
    return haystack.includes(needle);
  });
}

function showLead(record) {
  const dialog = byId('lead-dialog');
  const badge = byId('dialog-track');
  badge.textContent = record.track_label;
  badge.dataset.track = record.track;
  setText('dialog-title', record.name);
  const phone = byId('dialog-phone');
  phone.textContent = record.phone || 'Non renseigné';
  phone.href = record.phone ? `tel:${record.phone}` : '#';
  setText('dialog-date', `Consentement enregistré le ${formatDate(record.consent_at, true)}`);
  setText('dialog-summary', record.summary);
  const funnel = byId('dialog-funnel');
  funnel.replaceChildren();
  const funnelValues = [
    ['Origine', record.lead_source === 'canal_gratuit' ? 'Canal Telegram gratuit' : 'Accès direct'],
    ['Orientation', record.funnel_route === 'consultation' ? 'Consultation RDW' : record.funnel_route],
    ['Statut', record.offer_status === 'consultation_requested' ? 'Demande enregistrée' : record.offer_status]
  ];
  funnelValues.forEach(([label, value]) => {
    const wrapper = document.createElement('div');
    const term = document.createElement('dt');
    const detail = document.createElement('dd');
    term.textContent = label; detail.textContent = value;
    wrapper.append(term, detail); funnel.append(wrapper);
  });
  const facts = byId('dialog-facts');
  facts.replaceChildren();
  record.facts.forEach((fact) => {
    const wrapper = document.createElement('div');
    const term = document.createElement('dt');
    const detail = document.createElement('dd');
    term.textContent = fact.label;
    detail.textContent = fact.value;
    wrapper.append(term, detail);
    facts.append(wrapper);
  });
  if (!record.facts.length) {
    const wrapper = document.createElement('div');
    const detail = document.createElement('dd');
    detail.textContent = 'Aucune précision enregistrée.';
    wrapper.append(detail);
    facts.append(wrapper);
  }
  const questions = byId('dialog-questions');
  questions.replaceChildren();
  record.questions.forEach((question) => {
    const item = document.createElement('li');
    item.textContent = question;
    questions.append(item);
  });
  byId('questions-section').hidden = record.questions.length === 0;
  dialog.showModal();
}

function renderRows() {
  const body = byId('lead-rows');
  body.replaceChildren();
  const records = filteredRecords();
  byId('empty-state').hidden = records.length !== 0;
  records.forEach((record) => {
    const row = document.createElement('tr');
    row.tabIndex = 0;
    const client = document.createElement('td');
    const name = document.createElement('span');
    name.className = 'client-name'; name.textContent = record.name;
    const phone = document.createElement('span');
    phone.className = 'client-phone'; phone.textContent = record.phone;
    client.append(name, phone);
    const project = document.createElement('td');
    const badge = document.createElement('span');
    badge.className = 'track-badge'; badge.dataset.track = record.track; badge.textContent = record.track_label;
    project.append(badge);
    const clues = document.createElement('td');
    clues.className = 'clues';
    clues.textContent = record.facts.slice(0, 3).map((fact) => fact.value).join(' · ') || 'Projet résumé disponible';
    const date = document.createElement('td');
    date.className = 'date-cell'; date.textContent = formatDate(record.updated_at);
    const action = document.createElement('td');
    action.className = 'row-action'; action.textContent = '›';
    row.append(client, project, clues, date, action);
    row.addEventListener('click', () => showLead(record));
    row.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') showLead(record); });
    body.append(row);
  });
}

async function loadData() {
  const button = byId('refresh-button');
  button.disabled = true;
  setText('sync-label', 'Actualisation…');
  byId('sync-label').classList.remove('online');
  try {
    const response = await fetch('/api/dashboard', { cache: 'no-store' });
    if (!response.ok) throw new Error('Données indisponibles');
    state.data = await response.json();
    renderMetrics();
    renderDistribution();
    renderRows();
    setText('sync-label', `Base synchronisée · ${formatDate(state.data.generated_at, true)}`);
    byId('sync-label').classList.add('online');
  } catch (_error) {
    setText('sync-label', 'Base indisponible — relancez le bot');
  } finally {
    button.disabled = false;
  }
}

byId('refresh-button').addEventListener('click', loadData);
byId('search-input').addEventListener('input', (event) => { state.search = event.target.value; if (state.data) renderRows(); });
byId('track-filters').addEventListener('click', (event) => {
  const button = event.target.closest('[data-track]');
  if (!button) return;
  state.track = button.dataset.track;
  document.querySelectorAll('.filter').forEach((item) => item.classList.toggle('active', item === button));
  if (state.data) renderRows();
});
byId('dialog-close').addEventListener('click', () => byId('lead-dialog').close());
byId('lead-dialog').addEventListener('click', (event) => { if (event.target === byId('lead-dialog')) byId('lead-dialog').close(); });
loadData();
