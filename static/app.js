/* ============================================================
   Night Shift · Rota Studio
   A zero-dependency frontend for the night-shift scheduling API.

   The interesting part of this app is not the form: it is the
   model of the backend's own rules (point weights + the rest
   window) that lets the UI predict infeasible rotas *before*
   asking for one, and audit whatever comes back.
   ============================================================ */

const STORE_KEY = 'nightshift.studio.v1';
const RUNS_KEY = 'nightshift.studio.runs.v1';
const PERF_KEY = 'nightshift.studio.perf.v1';

const EFFORTS = [
  { find: 50,   label: 'Draft',      blurb: 'A single quick pass — good for sanity-checking the setup.' },
  { find: 150,  label: 'Quick',      blurb: 'Fast turnaround, usually a decent rota.' },
  { find: 400,  label: 'Balanced',   blurb: 'The sweet spot for most departments.' },
  { find: 1200, label: 'Thorough',   blurb: 'Searches hard for an even points split. Takes longer.' },
  { find: 3000, label: 'Exhaustive', blurb: 'Best fairness the engine can find. Expect a wait.' },
];

const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const DOW_SHORT = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December'];

/* ─────────────────────────── date helpers ─────────────────────────── */
/* Everything is a local 'YYYY-MM-DD' string; Dates are only used for
   arithmetic and are always built at local midnight to dodge TZ drift. */

const dateOf = (iso) => new Date(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10));
const isoOf = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const addDays = (iso, n) => { const d = dateOf(iso); d.setDate(d.getDate() + n); return isoOf(d); };
const dowOf = (iso) => dateOf(iso).getDay();
const isWeekend = (iso) => { const w = dowOf(iso); return w === 0 || w === 6; };
const prettyDate = (iso) => { const d = dateOf(iso); return `${DOW[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()].slice(0, 3)}`; };
const daysBetween = (a, b) => Math.round((dateOf(b) - dateOf(a)) / 86400000);

function eachDay(start, end) {
  const out = [];
  if (!start || !end || dateOf(end) < dateOf(start)) return out;
  let cur = start;
  for (let guard = 0; guard < 800 && dateOf(cur) <= dateOf(end); guard++) {
    out.push(cur);
    cur = addDays(cur, 1);
  }
  return out;
}

/** Point weight the backend assigns to a night. Holiday > Sunday = 2, Sat = 1.5. */
function weightOf(iso, holidays) {
  if (holidays.has(iso)) return 2;
  const w = dowOf(iso);
  if (w === 6) return 1.5;
  if (w === 0) return 2;
  return 1;
}

/* ─────────────────────────── misc helpers ─────────────────────────── */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function el(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === false || v === null || v === undefined) continue;
    if (k === 'class') node.className = v;
    else if (k === 'style') node.style.cssText = v;
    else if (k === 'html') node.innerHTML = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else if (k === 'dataset') Object.assign(node.dataset, v);
    else node.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    node.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

const icon = (id, cls = '') => {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  if (cls) svg.setAttribute('class', cls);
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', `#${id}`);
  svg.append(use);
  return svg;
};

const initials = (name) => name.replace(/(dr\.?|prof\.?|mr\.?|ms\.?|mrs\.?)/gi, '').trim()
  .split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]).join('').toUpperCase() || '?';

/**
 * Grades get colour; individual doctors do not.
 *
 * A rota can hold twenty doctors, and no palette stays distinguishable that
 * far — the old golden-angle rainbow generated hues that collided under
 * colour-vision deficiency and carried no meaning anyway, since every chip
 * already shows the name. Colour is reserved for state (weekend, holiday,
 * shortfall, conflict) and for the doctor currently focused. Grades are a
 * genuinely categorical set, small enough to validate, so they keep hues.
 */
const GRADE_SLOTS = ['var(--cat-1)', 'var(--cat-2)', 'var(--cat-3)', 'var(--cat-4)'];

function gradeColor(grade) {
  const index = state.grades.indexOf(grade);
  // Past the validated slots, fall back to ink rather than inventing a hue.
  return index >= 0 && index < GRADE_SLOTS.length ? GRADE_SLOTS[index] : 'var(--text-faint)';
}

/** Initials tiles read as identity without needing a unique colour each. */
function avatarStyle() {
  return 'background:var(--surface-3);color:var(--text-dim)';
}

const fmt = (n, dp = 1) => {
  if (!isFinite(n)) return '—';
  const r = Math.round(n * 10 ** dp) / 10 ** dp;
  return Number.isInteger(r) ? String(r) : r.toFixed(dp);
};
const plural = (n, one, many = one + 's') => `${n} ${n === 1 ? one : many}`;

/* ─────────────────────────── state ─────────────────────────── */

const today = new Date();
const defaultStart = isoOf(new Date(today.getFullYear(), today.getMonth() + 1, 1));
const defaultEnd = isoOf(new Date(today.getFullYear(), today.getMonth() + 2, 0));

const state = {
  theme: 'dark',
  apiBase: '',
  autoSave: true,
  startDate: defaultStart,
  endDate: defaultEnd,
  doctors: [],                 // [{ name, grade }]
  graded: false,
  grades: ['Senior', 'Junior'],
  coverage: 'same',            // 'same' | 'custom'
  perNight: 2,
  perNightMap: {},             // iso -> count
  holidays: new Set(),
  unavailable: {},             // name -> Set(iso)
  effort: 2,
  availDoctor: null,
  activeTab: 'calendar',
  result: null,                // { payload, response, analysis, meta }
  runs: [],
  focusDoctor: null,
};

/* ─────────────────────────── persistence ─────────────────────────── */

function saveState() {
  if (!state.autoSave) return;
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify({
      theme: state.theme, apiBase: state.apiBase, autoSave: state.autoSave,
      startDate: state.startDate, endDate: state.endDate,
      doctors: state.doctors, graded: state.graded, grades: state.grades,
      coverage: state.coverage, perNight: state.perNight, perNightMap: state.perNightMap,
      holidays: [...state.holidays], effort: state.effort,
      unavailable: Object.fromEntries(Object.entries(state.unavailable).map(([k, v]) => [k, [...v]])),
    }));
  } catch { /* storage full or blocked — the app still works */ }
}

function loadState() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORE_KEY) || 'null');
    if (saved) {
      Object.assign(state, saved);
      state.holidays = new Set(saved.holidays || []);
      state.unavailable = Object.fromEntries(
        Object.entries(saved.unavailable || {}).map(([k, v]) => [k, new Set(v)]));
    }
    state.runs = JSON.parse(localStorage.getItem(RUNS_KEY) || '[]');
  } catch { /* corrupt payload — start fresh */ }
  if (!state.availDoctor && state.doctors[0]) state.availDoctor = state.doctors[0].name;
}

function saveRuns() {
  try { localStorage.setItem(RUNS_KEY, JSON.stringify(state.runs.slice(0, 12))); } catch { /* ignore */ }
}

/** Learn how fast this deployment actually is, so the effort estimate improves with use. */
function perfFactor() {
  const v = parseFloat(localStorage.getItem(PERF_KEY) || '');
  return isFinite(v) && v > 0 ? v : 0.0000045; // seconds per unit of work, pre-calibration
}
function recordPerf(units, seconds) {
  if (units <= 0 || seconds <= 0) return;
  const blended = perfFactor() * 0.6 + (seconds / units) * 0.4;
  try { localStorage.setItem(PERF_KEY, String(blended)); } catch { /* ignore */ }
}

/* ─────────────────────────── derived model ─────────────────────────── */

const days = () => eachDay(state.startDate, state.endDate);
const doctorNames = () => state.doctors.map((d) => d.name);

const requiredOn = (iso) => (state.coverage === 'same'
  ? Number(state.perNight) || 0
  : (state.perNightMap[iso] ?? Number(state.perNight) ?? 0));

const isOff = (name, iso) => !!state.unavailable[name]?.has(iso);
const availableOn = (iso) => state.doctors.filter((d) => !isOff(d.name, iso));

/**
 * The backend benches whoever filled the most recent
 * `roster − ceil(roster / 3)` shift slots. In practice that leaves roughly
 * `ceil(roster / 3)` doctors selectable on any given night — the single
 * most common reason a rota comes back unfillable.
 */
function restModel() {
  const n = state.doctors.length;
  if (n === 0) return { benched: 0, selectable: 0, restNights: 0 };
  const benched = Math.max(0, n - Math.ceil(n / 3));
  const selectable = Math.max(1, n - benched);
  const perNightTotal = Math.max(1, state.graded
    ? requiredOn(state.startDate) * Math.max(1, state.grades.length)
    : requiredOn(state.startDate));
  return { benched, selectable, restNights: Math.floor(benched / perNightTotal) };
}

/* ─────────────────────────── pre-flight ─────────────────────────── */

/**
 * Everything that can be known without calling the API: hard blockers,
 * soft warnings, and a projection of what the rota will look like.
 */
function preflight() {
  const items = [];
  const list = days();
  const n = state.doctors.length;
  const blockers = [];

  if (!list.length) {
    blockers.push({ tone: 'bad', title: 'The period is empty', detail: 'The end date must fall on or after the start date.' });
  } else if (list.length > 366) {
    blockers.push({ tone: 'bad', title: 'Period is longer than a year', detail: `${list.length} nights is more than the engine will handle in one pass.` });
  }
  if (n < 2) {
    blockers.push({ tone: 'bad', title: 'Add at least two doctors', detail: 'A rota needs a roster to draw from.' });
  }

  if (state.graded) {
    if (!state.grades.length) {
      blockers.push({ tone: 'bad', title: 'No grades defined', detail: 'A graded department needs at least one grade.' });
    }
    const ungraded = state.doctors.filter((d) => !d.grade || !state.grades.includes(d.grade));
    if (ungraded.length) {
      blockers.push({
        tone: 'bad',
        title: `${plural(ungraded.length, 'doctor')} without a grade`,
        detail: ungraded.map((d) => d.name).join(', '),
      });
    }
  }

  if (blockers.length) return { ok: false, items: blockers };

  const perNightTotal = state.graded
    ? requiredOn(state.startDate) * state.grades.length
    : null;

  /* ── the rest rule vs. requested headcount ── */
  const rest = restModel();
  if (state.graded) {
    for (const grade of state.grades) {
      const size = state.doctors.filter((d) => d.grade === grade).length;
      const need = requiredOn(state.startDate);
      const pool = Math.max(1, Math.ceil(size / 3));
      if (size < need) {
        items.push({
          tone: 'bad',
          title: `${grade}: only ${plural(size, 'doctor')} for ${need} per night`,
          detail: 'Every grade is staffed independently each night, so this grade can never be filled.',
        });
      } else if (need > pool) {
        items.push({
          tone: 'warn',
          title: `${grade} will run short on some nights`,
          detail: `The rest rule keeps roughly ${plural(pool, 'doctor')} of this grade selectable, but ${need} are requested. Add doctors to the grade or lower the nightly count.`,
        });
      }
    }
  } else {
    const maxNeed = Math.max(...list.map(requiredOn), 0);
    if (maxNeed > n) {
      items.push({
        tone: 'bad',
        title: `${maxNeed} doctors requested a night, only ${plural(n, 'doctor')} on the roster`,
        detail: 'No night can be filled with more doctors than exist.',
      });
    } else if (maxNeed > rest.selectable) {
      items.push({
        tone: 'warn',
        title: 'The rest rule will leave nights unfilled',
        detail: `After benching recently-worked doctors, about ${plural(rest.selectable, 'doctor is', 'doctors are')} selectable per night — you have asked for ${maxNeed}. Expect gaps, or grow the roster to ~${maxNeed * 3}.`,
      });
    }
  }

  /* ── nights where leave alone makes cover impossible ──
     Only counted when the group is big enough on paper, so a roster that is
     simply too small is reported once above rather than once per night. */
  const thin = [];
  for (const iso of list) {
    const need = requiredOn(iso);
    if (!need) continue;
    if (state.graded) {
      for (const grade of state.grades) {
        const members = state.doctors.filter((d) => d.grade === grade);
        const free = members.filter((d) => !isOff(d.name, iso)).length;
        if (members.length >= need && free < need) { thin.push(`${prettyDate(iso)} · ${grade}`); break; }
      }
    } else if (n >= need && availableOn(iso).length < need) {
      thin.push(prettyDate(iso));
    }
  }
  if (thin.length) {
    items.push({
      tone: 'bad',
      title: `${plural(thin.length, 'night')} cannot be covered`,
      detail: `Too many doctors are on leave: ${thin.slice(0, 6).join(', ')}${thin.length > 6 ? ` and ${thin.length - 6} more` : ''}.`,
    });
  }

  /* ── nights that survive the leave check but not the rest rule ──
     Benching is global, so a grade loses roughly its share of the bench.
     Leave then eats into whatever is left. */
  const tight = [];
  for (const iso of list) {
    const need = requiredOn(iso);
    if (!need) continue;
    const groups = state.graded
      ? state.grades.map((g) => ({ label: g, members: state.doctors.filter((d) => d.grade === g) }))
      : [{ label: '', members: state.doctors }];
    for (const group of groups) {
      const share = rest.benched * (group.members.length / n);
      const onLeave = group.members.filter((d) => isOff(d.name, iso)).length;
      if (group.members.length - share - onLeave < need) {
        tight.push(`${prettyDate(iso)}${group.label ? ` · ${group.label}` : ''}`);
        break;
      }
    }
  }
  if (tight.length && !thin.length) {
    items.push({
      tone: 'warn',
      title: `${plural(tight.length, 'night')} may come back short`,
      detail: `Once the rest rule benches recent workers, these nights have barely enough doctors left — leave overlaps the bench on ${tight.slice(0, 4).join(', ')}${tight.length > 4 ? ` and ${tight.length - 4} more` : ''}. The engine leaves a night unfilled rather than breaking the rest rule.`,
    });
  }

  /* ── workload projection ── */
  const totalPoints = list.reduce((sum, iso) => {
    const seats = state.graded ? requiredOn(iso) * state.grades.length : requiredOn(iso);
    return sum + weightOf(iso, state.holidays) * seats;
  }, 0);
  const seats = list.reduce((s, iso) => s + (state.graded ? requiredOn(iso) * state.grades.length : requiredOn(iso)), 0);

  items.push({
    tone: 'info',
    title: `${plural(list.length, 'night')} · ${plural(seats, 'shift')} to fill`,
    detail: `≈ ${fmt(totalPoints / Math.max(1, n))} points and ${fmt(seats / Math.max(1, n))} shifts per doctor. Each doctor rests about ${plural(rest.restNights, 'night')} between shifts.`,
  });

  if (state.graded && perNightTotal) {
    items.push({
      tone: 'info',
      title: `${perNightTotal} doctors on call each night`,
      detail: `${requiredOn(state.startDate)} per grade × ${plural(state.grades.length, 'grade')} — graded departments staff every tier separately.`,
    });
  }

  /* ── search cost ── */
  const units = EFFORTS[state.effort].find * list.length * Math.max(1, state.graded ? state.grades.length : 1) * Math.max(1, requiredOn(state.startDate));
  const secs = units * perfFactor();
  if (secs > 25) {
    items.push({ tone: 'warn', title: `This search may take ~${fmt(secs / 60)} minutes`, detail: 'Lower the search effort if you just want a draft.' });
  } else if (secs > 6) {
    items.push({ tone: 'info', title: `Estimated search time ~${fmt(secs, 0)} seconds`, detail: '' });
  }

  const blocked = items.some((i) => i.tone === 'bad');
  if (!blocked && !items.some((i) => i.tone === 'warn')) {
    items.unshift({ tone: 'ok', title: 'Looks feasible', detail: 'Every night has enough rested, available doctors.' });
  }
  return { ok: !blocked, items };
}

function renderPreflight() {
  const host = $('#preflight');
  const { ok, items } = preflight();
  host.replaceChildren(...items.map((item) => el('div', { class: `pf-item ${item.tone}` },
    icon(item.tone === 'ok' ? 'i-check' : item.tone === 'info' ? 'i-bulb' : 'i-alert'),
    el('span', {}, el('b', {}, item.title), item.detail ? el('em', {}, item.detail) : null),
  )));
  $('#generateBtn').disabled = !ok;
}

/* ─────────────────────────── config rendering ─────────────────────────── */

function renderRoster() {
  const host = $('#doctorList');
  const scroll = host.scrollTop;

  if (!state.doctors.length) {
    host.replaceChildren(el('div', { class: 'empty-note' }, 'No doctors yet — add them one by one, or paste a comma-separated list.'));
  } else {
    host.replaceChildren(...state.doctors.map((doc) => {
      const offCount = state.unavailable[doc.name]?.size || 0;
      const row = el('div', { class: `doc-row${offCount ? ' has-blackout' : ''}` },
        el('div', { class: 'avatar', style: avatarStyle() }, initials(doc.name)),
        el('div', { class: 'doc-name', title: doc.name }, doc.name),
        offCount ? el('span', { class: 'doc-badge', title: `${offCount} nights unavailable` }, `${offCount} off`) : null,
      );
      if (state.graded) {
        const sel = el('select', {
          // Keep the row itself alive so assigning grades one by one does not
          // rebuild (and re-scroll) the list under the coordinator's cursor.
          onchange: (e) => { doc.grade = e.target.value; onConfigChange({ keepRoster: true }); },
          title: 'Grade',
        }, el('option', { value: '' }, '— grade —'),
        ...state.grades.map((g) => el('option', { value: g, selected: doc.grade === g }, g)));
        row.append(sel);
      }
      row.append(el('button', {
        class: 'doc-del', title: `Remove ${doc.name}`, 'aria-label': `Remove ${doc.name}`,
        onclick: () => {
          state.doctors = state.doctors.filter((d) => d.name !== doc.name);
          delete state.unavailable[doc.name];
          if (state.availDoctor === doc.name) state.availDoctor = state.doctors[0]?.name || null;
          onConfigChange();
        },
      }, icon('i-x')));
      return row;
    }));
  }

  host.scrollTop = scroll;
  $('#rosterNote').textContent = plural(state.doctors.length, 'doctor');
  $('#gradesBlock').hidden = !state.graded;
  $('#gradedToggle').checked = state.graded;
  renderGrades();
  renderAvailDoctorSelect();
}

function renderGrades() {
  const host = $('#gradeChips');
  if (!host) return;
  host.replaceChildren(...state.grades.map((grade) => {
    const count = state.doctors.filter((d) => d.grade === grade).length;
    return el('span', { class: 'grade-chip' },
      el('i', { style: `background:${gradeColor(grade)}` }),
      grade,
      el('span', { class: 'cnt' }, `· ${count}`),
      el('button', {
        title: `Remove ${grade}`, 'aria-label': `Remove ${grade}`,
        onclick: () => {
          state.grades = state.grades.filter((g) => g !== grade);
          state.doctors.forEach((d) => { if (d.grade === grade) d.grade = ''; });
          onConfigChange();
        },
      }, icon('i-x')));
  }));
}

function renderAvailDoctorSelect() {
  const sel = $('#availDoctor');
  if (!state.doctors.some((d) => d.name === state.availDoctor)) {
    state.availDoctor = state.doctors[0]?.name || null;
  }
  sel.replaceChildren(...state.doctors.map((d) =>
    el('option', { value: d.name, selected: d.name === state.availDoctor }, d.name)));
  if (!state.doctors.length) sel.replaceChildren(el('option', {}, '— add doctors first —'));
}

/**
 * Compact month grid shared by the holiday picker, the availability picker
 * and the per-night coverage planner.
 */
function renderMiniCal(host, opts) {
  const list = days();
  host.replaceChildren();
  if (!list.length) {
    host.append(el('div', { class: 'empty-note' }, 'Pick a valid period first.'));
    return;
  }

  const byMonth = new Map();
  for (const iso of list) {
    const key = iso.slice(0, 7);
    if (!byMonth.has(key)) byMonth.set(key, []);
    byMonth.get(key).push(iso);
  }

  for (const [key, isos] of byMonth) {
    const first = dateOf(isos[0]);
    const grid = el('div', { class: 'mc-grid' },
      ...DOW_SHORT.map((d, i) => el('div', { class: 'mc-dow', key: i }, d)));

    for (let i = 0; i < dateOf(`${key}-01`).getDay(); i++) grid.append(el('div', { class: 'mc-day is-out' }));
    // Blank out the days of the month that precede the period's start.
    for (let d = 1; d < first.getDate(); d++) {
      grid.append(el('button', { class: 'mc-day is-outside', disabled: true, type: 'button' }, d));
    }

    for (const iso of isos) {
      const day = dateOf(iso).getDate();
      const cell = el('button', { class: 'mc-day', type: 'button', title: prettyDate(iso) }, String(day));
      if (dowOf(iso) === 6) cell.classList.add('is-sat');
      if (dowOf(iso) === 0) cell.classList.add('is-sun');
      opts.decorate(cell, iso);
      cell.addEventListener('click', (e) => opts.onClick(iso, e));
      if (opts.onWheel) cell.addEventListener('wheel', (e) => opts.onWheel(iso, e), { passive: false });
      grid.append(cell);
    }

    host.append(el('div', { class: 'mc-month' },
      el('div', { class: 'mc-title' }, `${MONTHS[first.getMonth()]} ${first.getFullYear()}`),
      grid));
  }
}

function renderHolidayCal() {
  renderMiniCal($('#holidayCal'), {
    decorate: (cell, iso) => {
      if (state.holidays.has(iso)) cell.classList.add('is-holiday');
      cell.title = `${prettyDate(iso)} · weight ${fmt(weightOf(iso, state.holidays))}`;
    },
    onClick: (iso) => {
      state.holidays.has(iso) ? state.holidays.delete(iso) : state.holidays.add(iso);
      onConfigChange();
    },
  });
  $('#holidayNote').textContent = plural(state.holidays.size, 'holiday');
}

function renderAvailCal() {
  const name = state.availDoctor;
  renderMiniCal($('#availCal'), {
    decorate: (cell, iso) => {
      if (name && isOff(name, iso)) cell.classList.add('is-off');
    },
    onClick: (iso) => {
      if (!name) return;
      const set = state.unavailable[name] || (state.unavailable[name] = new Set());
      set.has(iso) ? set.delete(iso) : set.add(iso);
      if (!set.size) delete state.unavailable[name];
      onConfigChange();
    },
  });

  const total = Object.values(state.unavailable).reduce((s, v) => s + v.size, 0);
  $('#availNote').textContent = total ? `${plural(total, 'night')} blocked` : 'no blackouts';

  const summary = $('#blackoutSummary');
  const entries = Object.entries(state.unavailable).filter(([, v]) => v.size);
  summary.replaceChildren(...entries.map(([doc, set]) =>
    el('div', { class: 'inline-actions', style: 'font-size:11.5px;color:var(--text-faint)' },
      el('b', { style: 'color:var(--text-dim);font-weight:600' }, doc),
      `${plural(set.size, 'night')} off`,
      el('button', {
        class: 'link-btn danger',
        onclick: () => { delete state.unavailable[doc]; onConfigChange(); },
      }, 'clear'))));
}

function renderCoverageCal() {
  renderMiniCal($('#coverageCal'), {
    decorate: (cell, iso) => {
      const n = requiredOn(iso);
      cell.classList.add('has-count');
      if (n === 0) cell.classList.add('cnt-0');
      if (state.holidays.has(iso)) cell.classList.add('is-holiday');
      cell.append(el('span', { class: 'cnt' }, String(n)));
      cell.title = `${prettyDate(iso)} · ${plural(n, 'doctor')} — click to add, right-click to remove`;
    },
    onClick: (iso, e) => {
      e.preventDefault();
      const cur = requiredOn(iso);
      state.perNightMap[iso] = Math.min(20, cur + 1);
      onConfigChange();
    },
    onWheel: (iso, e) => {
      e.preventDefault();
      const cur = requiredOn(iso);
      state.perNightMap[iso] = Math.max(0, Math.min(20, cur + (e.deltaY < 0 ? 1 : -1)));
      onConfigChange();
    },
  });
  // Right-click decrements.
  $('#coverageCal').oncontextmenu = (e) => {
    const btn = e.target.closest('.mc-day');
    if (!btn) return;
    e.preventDefault();
  };
}

function renderCoverage() {
  const same = state.coverage === 'same';
  $('#coverageSame').hidden = !same;
  $('#coverageCustom').hidden = same;
  $$('.seg-btn[data-coverage]').forEach((b) => b.classList.toggle('is-active', b.dataset.coverage === state.coverage));
  $('#perNight').value = state.perNight;

  const gradedHint = $('#gradedCoverageHint');
  gradedHint.hidden = !state.graded;
  if (state.graded) {
    gradedHint.innerHTML = `Applied <b>per grade</b> — with ${state.grades.length} grades that is <b>${state.perNight * state.grades.length} doctors</b> on call each night.`;
  }

  if (!same) renderCoverageCal();

  const list = days();
  const seats = list.reduce((s, iso) => s + requiredOn(iso), 0) * (state.graded ? Math.max(1, state.grades.length) : 1);
  $('#coverageNote').textContent = list.length ? `${plural(seats, 'shift')} total` : '—';
}

function renderPeriod() {
  $('#startDate').value = state.startDate;
  $('#endDate').value = state.endDate;
  const list = days();
  const weekends = list.filter(isWeekend).length;
  $('#periodNote').textContent = list.length
    ? `${plural(list.length, 'night')} · ${weekends} weekend`
    : 'invalid range';
  $('#periodNote').classList.toggle('is-warn', !list.length);
}

function renderEffort() {
  const e = EFFORTS[state.effort];
  $('#effort').value = state.effort;
  $('#effortNote').textContent = e.label;
  $('#effortHint').innerHTML = `<b>${e.find.toLocaleString()}</b> candidate rotas. ${e.blurb}`;
}

/** Single entry point after any config mutation. */
function onConfigChange({ keepRoster = false } = {}) {
  renderPeriod();
  if (keepRoster) {
    renderGrades();
    $('#rosterNote').textContent = plural(state.doctors.length, 'doctor');
  } else {
    renderRoster();
  }
  renderCoverage();
  renderHolidayCal();
  renderAvailCal();
  renderEffort();
  renderPreflight();
  saveState();
}

/* ─────────────────────────── API ─────────────────────────── */

function buildPayload() {
  const list = days();
  const names = doctorNames();
  const same = state.coverage === 'same';

  const notPresent = {};
  for (const [doc, set] of Object.entries(state.unavailable)) {
    if (set.size && names.includes(doc)) notPresent[doc] = [...set].sort().join(',');
  }

  const perNightMap = {};
  if (!same) for (const iso of list) perNightMap[iso] = requiredOn(iso); // insertion order == date order

  return {
    doctor_names: names.join(','),
    start_date: state.startDate,
    end_date: state.endDate,
    same_num_doctors: same ? 'Y' : 'N',
    num_doctors: same ? Number(state.perNight) : null,
    num_doctors_per_night: same ? null : perNightMap,
    holiday_days: [...state.holidays].sort().join(','),
    find: EFFORTS[state.effort].find,
    department_is_graded: state.graded ? 'Y' : 'N',
    doctors_grades: state.graded ? Object.fromEntries(state.doctors.map((d) => [d.name, d.grade])) : null,
    // The engine iterates this collection directly: null makes it throw and
    // silently assign nobody, so a graded run must always send an object.
    shift_requirements: state.graded ? {} : null,
    grades: state.graded ? [...state.grades] : null,
    doctor_not_present: notPresent,
  };
}

async function callApi(path, options) {
  const base = state.apiBase.replace(/\/$/, '');
  return fetch(`${base}${path}`, options);
}

async function generate() {
  const { ok } = preflight();
  if (!ok) return;

  const payload = buildPayload();
  const overlay = $('#runOverlay');
  const started = performance.now();
  overlay.hidden = false;
  $('#generateBtn').disabled = true;

  const stages = [
    'Sampling candidate rotas',
    'Applying the rest rule',
    'Scoring points balance',
    'Comparing weekend fairness',
    'Picking the most even rota',
  ];
  let stage = 0;
  $('#runDetail').textContent = stages[0];
  $('#runBarFill').style.width = '12%';
  const ticker = setInterval(() => {
    stage = Math.min(stage + 1, stages.length - 1);
    $('#runDetail').textContent = stages[stage];
    $('#runBarFill').style.width = `${Math.min(92, 12 + stage * 20)}%`;
    $('#runElapsed').textContent = `${((performance.now() - started) / 1000).toFixed(1)}s`;
  }, 700);
  const clock = setInterval(() => {
    $('#runElapsed').textContent = `${((performance.now() - started) / 1000).toFixed(1)}s`;
  }, 100);

  try {
    const res = await callApi('/schedule', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!res.ok) throw new Error(await explainError(res));
    const data = await res.json();
    const elapsed = (performance.now() - started) / 1000;

    const nights = days().length;
    recordPerf(payload.find * nights * Math.max(1, state.graded ? state.grades.length : 1) * Math.max(1, state.perNight), elapsed);

    const analysis = analyse(data, payload);
    state.result = { payload, response: data, analysis, meta: { elapsed, at: Date.now() } };
    state.focusDoctor = null;

    state.runs.unshift({
      id: data.schedule_name,
      at: Date.now(),
      elapsed,
      graded: state.graded,
      doctors: doctorNames().length,
      nights,
      score: data.score,
      balance: analysis.balance,
      issues: analysis.findings.filter((f) => f.severity !== 'ok' && f.severity !== 'info').length,
      snapshot: { payload, response: data },
    });
    state.runs = state.runs.slice(0, 12);
    saveRuns();

    $('#emptyState').hidden = true;
    renderResult();
    revealResults();
    toast('ok', 'Rota generated', `${analysis.assignedCount} shifts placed in ${fmt(elapsed)}s · balance ${fmt(analysis.balance, 0)}%`);
  } catch (err) {
    toast('err', 'Could not generate a rota', err.message);
  } finally {
    clearInterval(ticker);
    clearInterval(clock);
    overlay.hidden = true;
    renderPreflight();
  }
}

/** Turn the API's terse failures into something a rota coordinator can act on. */
async function explainError(res) {
  let detail = '';
  try {
    const body = await res.json();
    detail = typeof body.detail === 'string' ? body.detail
      : Array.isArray(body.detail) ? body.detail.map((d) => `${d.loc?.join('.')}: ${d.msg}`).join('; ')
        : '';
  } catch { /* not JSON */ }

  if (res.status === 500 && !detail) {
    return 'The engine could not build a rota from these rules — usually too many doctors per night for the roster once the rest rule benches recent workers. Try fewer per night, more doctors, or fewer blackout days.';
  }
  if (res.status === 422 && !detail) return 'The engine rejected these inputs.';
  return detail || `${res.status} ${res.statusText}`;
}

async function checkApi() {
  const pill = $('#apiStatus');
  const text = $('#apiStatusText');
  try {
    const res = await callApi('/health', { method: 'GET' });
    if (res.ok) {
      const body = await res.json().catch(() => ({}));
      pill.className = 'pill is-ok';
      text.textContent = body.doctors_endpoint === false ? 'API online' : 'API online';
      return;
    }
    throw new Error(String(res.status));
  } catch {
    pill.className = 'pill is-bad';
    text.textContent = 'API unreachable';
  }
}

/* ─────────────────────────── analysis ─────────────────────────── */

/** The two response shapes (graded / ungraded) collapse into one model here. */
function normalise(response) {
  const nights = new Map(); // iso -> [{ name, points }]
  for (const [rawKey, value] of Object.entries(response.schedule || {})) {
    const iso = rawKey.slice(0, 10);
    const entries = Array.isArray(value)
      ? value.map(([name, points]) => ({ name, points }))
      : Object.entries(value).map(([name, points]) => ({ name, points }));
    nights.set(iso, entries);
  }

  const flatten = (obj) => {
    if (!obj) return {};
    const first = Object.values(obj)[0];
    if (first !== null && typeof first === 'object') {
      return Object.assign({}, ...Object.values(obj)); // grade-nested
    }
    return obj;
  };

  return {
    nights,
    points: flatten(response.points),
    shifts: flatten(response.num_shifts),
    weekendShifts: flatten(response.num_weekend_shifts),
    byGrade: response.points && typeof Object.values(response.points)[0] === 'object' ? response.points : null,
  };
}

function analyse(response, payload) {
  const model = normalise(response);
  const list = days();
  const holidays = state.holidays;
  const gradeOf = Object.fromEntries(state.doctors.map((d) => [d.name, d.grade || '']));

  const perDoctor = state.doctors.map((doc) => {
    const dates = list.filter((iso) => (model.nights.get(iso) || []).some((e) => e.name === doc.name));
    const gaps = dates.slice(1).map((iso, i) => daysBetween(dates[i], iso));
    const violations = dates.filter((iso) => isOff(doc.name, iso));
    const backToBack = gaps.filter((g) => g === 1).length;
    return {
      name: doc.name,
      grade: gradeOf[doc.name],
      dates,
      points: model.points[doc.name] ?? dates.reduce((s, iso) => s + weightOf(iso, holidays), 0),
      shifts: model.shifts[doc.name] ?? dates.length,
      weekendShifts: model.weekendShifts[doc.name] ?? dates.filter(isWeekend).length,
      holidayShifts: dates.filter((iso) => holidays.has(iso)).length,
      gaps,
      minGap: gaps.length ? Math.min(...gaps) : null,
      avgGap: gaps.length ? gaps.reduce((a, b) => a + b, 0) / gaps.length : null,
      backToBack,
      violations,
    };
  });

  /* Night-by-night coverage audit against what was actually requested. */
  const perNight = list.map((iso) => {
    const assigned = model.nights.get(iso) || [];
    const need = state.graded ? requiredOn(iso) * state.grades.length : requiredOn(iso);
    return {
      iso,
      assigned,
      need,
      short: Math.max(0, need - assigned.length),
      weight: weightOf(iso, holidays),
      grades: state.graded
        ? Object.fromEntries(state.grades.map((g) => [g, assigned.filter((a) => gradeOf[a.name] === g).length]))
        : null,
    };
  });

  const pts = perDoctor.map((d) => d.points);
  const mean = pts.reduce((a, b) => a + b, 0) / Math.max(1, pts.length);
  const sd = Math.sqrt(pts.reduce((s, p) => s + (p - mean) ** 2, 0) / Math.max(1, pts.length));
  const balance = mean > 0 ? Math.max(0, Math.min(100, 100 * (1 - sd / mean))) : 0;

  const spread = (arr) => (arr.length ? Math.max(...arr) - Math.min(...arr) : 0);

  const analysis = {
    model,
    perDoctor,
    perNight,
    assignedCount: perNight.reduce((s, n) => s + n.assigned.length, 0),
    requiredCount: perNight.reduce((s, n) => s + n.need, 0),
    balance,
    mean,
    pointsSpread: spread(pts),
    shiftSpread: spread(perDoctor.map((d) => d.shifts)),
    weekendSpread: spread(perDoctor.map((d) => d.weekendShifts)),
    score: response.score,
    name: response.schedule_name,
    graded: payload.department_is_graded === 'Y',
    findings: [],
  };
  analysis.findings = buildFindings(analysis);
  return analysis;
}

function buildFindings(a) {
  const out = [];

  const violators = a.perDoctor.filter((d) => d.violations.length);
  const blackoutCount = Object.values(state.unavailable).reduce((s, v) => s + v.size, 0);
  if (violators.length) {
    out.push({
      severity: 'bad',
      title: 'Leave conflicts',
      body: 'The engine placed doctors on nights you marked unavailable. It drops blackout dates it cannot honour rather than failing, so these need a manual swap.',
      chips: violators.flatMap((d) => d.violations.map((iso) => `${d.name} · ${prettyDate(iso)}`)),
    });
  } else if (blackoutCount) {
    out.push({
      severity: 'ok',
      title: 'Every leave request was honoured',
      body: `All ${plural(blackoutCount, 'blocked night')} across the roster are respected — nobody is rostered while they are away.`,
      chips: [],
    });
  }

  const emptyNights = a.perNight.filter((n) => n.need > 0 && n.assigned.length === 0);
  const shortNights = a.perNight.filter((n) => n.short > 0 && n.assigned.length > 0);
  if (emptyNights.length) {
    out.push({
      severity: 'bad',
      title: `${plural(emptyNights.length, 'night')} with nobody on call`,
      body: 'The rest rule left no eligible doctor for these nights. Grow the roster, reduce the nightly headcount, or free up leave around these dates.',
      chips: emptyNights.map((n) => prettyDate(n.iso)),
    });
  }
  if (shortNights.length) {
    out.push({
      severity: 'warn',
      title: `${plural(shortNights.length, 'night')} understaffed`,
      body: 'Fewer doctors were placed than you asked for on these nights.',
      chips: shortNights.map((n) => `${prettyDate(n.iso)} · ${n.assigned.length}/${n.need}`),
    });
  }
  if (!emptyNights.length && !shortNights.length) {
    out.push({
      severity: 'ok',
      title: 'Every night is fully staffed',
      body: `All ${plural(a.requiredCount, 'requested shift')} were filled across ${plural(a.perNight.length, 'night')}.`,
      chips: [],
    });
  }

  const b2b = a.perDoctor.filter((d) => d.backToBack > 0);
  if (b2b.length) {
    out.push({
      severity: 'warn',
      title: 'Back-to-back nights',
      body: 'These doctors work two consecutive nights at least once. Legal in most rotas, but worth a look.',
      chips: b2b.map((d) => `${d.name} ×${d.backToBack}`),
    });
  }

  const idle = a.perDoctor.filter((d) => d.shifts === 0);
  if (idle.length) {
    out.push({
      severity: 'warn',
      title: `${plural(idle.length, 'doctor')} never rostered`,
      body: 'They carry no shifts at all — usually a sign of heavy leave or a grade with more doctors than seats.',
      chips: idle.map((d) => d.name),
    });
  }

  if (a.graded) {
    const gaps = [];
    for (const night of a.perNight) {
      for (const [grade, count] of Object.entries(night.grades || {})) {
        if (count === 0 && night.need > 0) gaps.push(`${prettyDate(night.iso)} · ${grade}`);
      }
    }
    if (gaps.length) {
      out.push({
        severity: 'warn',
        title: 'Grade coverage gaps',
        body: 'Some nights have no doctor from a given grade on call.',
        chips: gaps.slice(0, 40),
      });
    }
  }

  if (a.pointsSpread <= 1) {
    out.push({
      severity: 'ok',
      title: `Points are within ${fmt(a.pointsSpread)} of each other`,
      body: `Every doctor carries between ${fmt(Math.min(...a.perDoctor.map((d) => d.points)))} and ${fmt(Math.max(...a.perDoctor.map((d) => d.points)))} points. That is as even as this period allows in practice.`,
      chips: [],
    });
  } else if (a.pointsSpread > 3) {
    out.push({
      severity: 'warn',
      title: `Points spread of ${fmt(a.pointsSpread)}`,
      body: 'The heaviest and lightest loads differ noticeably. Raising the search effort usually closes the gap.',
      chips: [],
    });
  }

  if (a.weekendSpread > 1) {
    out.push({
      severity: 'warn',
      title: `Weekend load differs by ${plural(a.weekendSpread, 'shift')}`,
      body: 'Weekends carry the heaviest weights, so an uneven weekend split is what people notice first.',
      chips: [],
    });
  }

  const tightest = a.perDoctor.filter((d) => d.minGap !== null).sort((x, y) => x.minGap - y.minGap)[0];
  out.push({
    severity: 'info',
    title: 'How this rota was scored',
    body: `The engine searched ${(state.result?.payload.find ?? EFFORTS[state.effort].find).toLocaleString()} random rotas, kept those with the flattest points split, then broke ties on shift count, weekend count and the evenness of the spacing between each doctor's nights. Its final score is ${fmt(a.score, 2)} — lower is better.${tightest ? ` The tightest turnaround belongs to ${tightest.name}, ${plural(tightest.minGap, 'night')} between shifts.` : ''}`,
    chips: [],
  });

  return out;
}

/* ─────────────────────────── result rendering ─────────────────────────── */

function renderResult() {
  if (!state.result) return;
  renderCalendarPane();
  renderFairnessPane();
  renderInsightsPane();
  renderExportPane();
  renderHistoryPane();

  const issues = state.result.analysis.findings.filter((f) => f.severity === 'bad' || f.severity === 'warn').length;
  const badge = $('#insightBadge');
  badge.hidden = issues === 0;
  badge.textContent = issues;
  badge.classList.toggle('is-bad', state.result.analysis.findings.some((f) => f.severity === 'bad'));

  showTab(state.activeTab);
}

function resultHeader(actions = []) {
  const { analysis, meta } = state.result;
  return el('div', { class: 'result-head' },
    el('div', { class: 'result-title' },
      el('h2', {}, `${prettyDate(state.startDate)} → ${prettyDate(state.endDate)}`),
      el('span', { class: 'sub' }, `${analysis.name} · ${fmt(meta.elapsed)}s`)),
    actions.length ? el('div', { class: 'result-actions' }, ...actions) : null);
}

function statStrip() {
  const a = state.result.analysis;
  const coverage = a.requiredCount ? (a.assignedCount / a.requiredCount) * 100 : 100;
  const stat = (k, v, d, tone = '') => el('div', { class: `stat ${tone}` },
    el('div', { class: 'k' }, k), el('div', { class: 'v' }, v), el('div', { class: 'd' }, d));

  return el('div', { class: 'stat-strip' },
    stat('Balance', `${fmt(a.balance, 0)}%`, 'evenness of the points split',
      a.balance >= 92 ? 'tone-ok' : a.balance >= 80 ? '' : 'tone-warn'),
    stat('Coverage', `${fmt(coverage, 0)}%`, `${a.assignedCount} of ${a.requiredCount} shifts filled`,
      coverage >= 100 ? 'tone-ok' : coverage >= 90 ? 'tone-warn' : 'tone-bad'),
    stat('Points spread', fmt(a.pointsSpread), 'heaviest minus lightest',
      a.pointsSpread <= 1 ? 'tone-ok' : a.pointsSpread <= 3 ? 'tone-warn' : 'tone-bad'),
    stat('Weekend spread', fmt(a.weekendSpread, 0), 'weekend shifts, max − min',
      a.weekendSpread <= 1 ? 'tone-ok' : 'tone-warn'),
    stat('Engine score', fmt(a.score, 2), 'lower is fairer'),
  );
}

function renderCalendarPane() {
  const pane = $('#pane-calendar');
  const a = state.result.analysis;
  const gradeOf = Object.fromEntries(state.doctors.map((d) => [d.name, d.grade || '']));

  const actions = [
    el('button', { class: 'btn btn-ghost', onclick: () => window.print() }, icon('i-print'), 'Print'),
    el('button', { class: 'btn btn-primary', onclick: generate }, icon('i-spark'), 'Regenerate'),
  ];

  const filter = el('div', { class: 'doc-filter' },
    ...state.doctors.map((doc) => el('button', {
      class: `df-chip${state.focusDoctor === doc.name ? ' is-on' : ''}`,
      title: `Show only ${doc.name}'s nights`,
      onclick: () => { state.focusDoctor = state.focusDoctor === doc.name ? null : doc.name; renderCalendarPane(); },
    }, doc.name)));

  const legend = el('div', { class: 'legend' },
    el('span', { class: 'lg' }, el('span', { class: 'sw', style: 'background:var(--holiday-bg);border-color:var(--holiday)' }), 'Holiday · 2.0'),
    el('span', { class: 'lg' }, el('span', { class: 'sw', style: 'background:var(--weekend-bg)' }), 'Weekend · 1.5 / 2.0'),
    el('span', { class: 'lg' }, el('span', { class: 'sw', style: 'border-color:var(--danger)' }), 'Understaffed night'),
    el('span', { class: 'lg' }, el('span', { class: 'sw', style: 'box-shadow:inset 0 0 0 1px var(--warn)' }), 'Back-to-back night'),
  );

  const months = el('div', { class: 'months' });
  const byMonth = new Map();
  for (const night of a.perNight) {
    const key = night.iso.slice(0, 7);
    if (!byMonth.has(key)) byMonth.set(key, []);
    byMonth.get(key).push(night);
  }

  for (const [key, nights] of byMonth) {
    const first = dateOf(nights[0].iso);
    const grid = el('div', { class: 'cal-grid' },
      ...DOW.map((d) => el('div', { class: 'cal-dow' }, d)));

    for (let i = 0; i < dateOf(`${key}-01`).getDay(); i++) grid.append(el('div', { class: 'cal-cell is-blank' }));
    for (let d = 1; d < first.getDate(); d++) grid.append(el('div', { class: 'cal-cell is-blank' }));

    for (const night of nights) {
      const cell = el('div', { class: 'cal-cell' });
      if (isWeekend(night.iso)) cell.classList.add('is-weekend');
      if (dowOf(night.iso) === 0) cell.classList.add('is-sun');
      if (state.holidays.has(night.iso)) cell.classList.add('is-holiday');
      if (night.short > 0) cell.classList.add('is-short');
      if (!night.assigned.length) cell.classList.add('is-empty-night');

      cell.append(el('div', { class: 'cal-head' },
        el('span', { class: 'cal-num' }, String(dateOf(night.iso).getDate())),
        el('span', { class: 'cal-w', title: 'point weight' }, fmt(night.weight))));

      const docs = el('div', { class: 'cal-docs' });
      const sorted = [...night.assigned].sort((x, y) =>
        (gradeOf[x.name] || '').localeCompare(gradeOf[y.name] || '') || x.name.localeCompare(y.name));

      for (const entry of sorted) {
        const info = a.perDoctor.find((d) => d.name === entry.name);
        const chip = el('div', {
          class: 'cal-doc',
          title: `${entry.name}${gradeOf[entry.name] ? ` · ${gradeOf[entry.name]}` : ''} · ${fmt(entry.points)} pts`,
        }, el('span', { class: 'cd-name' }, entry.name),
          state.graded && gradeOf[entry.name]
            ? el('span', { class: 'cd-grade', style: `color:${gradeColor(gradeOf[entry.name])}` },
                gradeOf[entry.name])
            : null);

        if (isOff(entry.name, night.iso)) chip.classList.add('is-violation');
        if (info && (info.dates.includes(addDays(night.iso, 1)) || info.dates.includes(addDays(night.iso, -1)))) {
          chip.classList.add('is-b2b');
        }
        if (state.focusDoctor) chip.classList.add(state.focusDoctor === entry.name ? 'hit' : 'dim');
        docs.append(chip);
      }
      cell.append(docs);

      if (night.short > 0) {
        cell.append(el('span', { class: 'cal-flag' }, night.assigned.length ? `short ${night.short}` : 'unfilled'));
      }
      grid.append(cell);
    }

    const filled = nights.reduce((s, n) => s + n.assigned.length, 0);
    months.append(el('div', {},
      el('div', { class: 'month-title' },
        `${MONTHS[first.getMonth()]} ${first.getFullYear()}`,
        el('span', { class: 'm-meta' }, `${plural(nights.length, 'night')} · ${plural(filled, 'shift')}`)),
      grid));
  }

  pane.replaceChildren(resultHeader(actions), statStrip(), legend, filter, months);
}

/** One measure across doctors, so one hue — rank is read from length. */
function bar(label, value, max, extra = {}) {
  return el('div', { class: 'bar-row' },
    el('div', { class: 'bl' }, el('span', { title: label }, label)),
    el('div', { class: 'bar-track' },
      el('div', { class: 'bar-fill', style: `width:${max ? (value / max) * 100 : 0}%` })),
    el('div', { class: 'bar-val' }, extra.valueText ?? fmt(value),
      extra.note ? el('span', { class: 'bar-note' }, extra.note) : null));
}

function renderFairnessPane() {
  const pane = $('#pane-fairness');
  const a = state.result.analysis;

  /* Balance gauge */
  const r = 50, circ = 2 * Math.PI * r;
  const gauge = el('div', { class: 'gauge' });
  gauge.innerHTML = `
    <svg viewBox="0 0 120 120">
      <circle class="track" cx="60" cy="60" r="${r}"/>
      <circle class="val" cx="60" cy="60" r="${r}" stroke-dasharray="${circ}" stroke-dashoffset="${circ}"/>
    </svg>
    <div class="gauge-num">${fmt(a.balance, 0)}<small>balance</small></div>`;
  requestAnimationFrame(() => {
    const c = gauge.querySelector('.val');
    if (c) c.style.strokeDashoffset = String(circ * (1 - a.balance / 100));
  });

  const lightest = [...a.perDoctor].sort((x, y) => x.points - y.points)[0];
  const heaviest = [...a.perDoctor].sort((x, y) => y.points - x.points)[0];

  const overview = el('div', { class: 'panel' },
    el('h3', {}, icon('i-scale'), 'Points balance'),
    el('div', { class: 'panel-sub' }, 'Weekdays 1.0 · Saturdays 1.5 · Sundays and holidays 2.0'),
    el('div', { class: 'gauge-wrap' }, gauge,
      el('div', { class: 'gauge-legend' },
        el('div', {}, 'Average load ', el('b', {}, `${fmt(a.mean)} points`)),
        heaviest ? el('div', {}, 'Heaviest ', el('b', {}, `${heaviest.name} · ${fmt(heaviest.points)}`)) : null,
        lightest ? el('div', {}, 'Lightest ', el('b', {}, `${lightest.name} · ${fmt(lightest.points)}`)) : null,
        el('div', {}, 'Spread ', el('b', {}, fmt(a.pointsSpread)), ' points'))));

  /* Points bars */
  const maxPts = Math.max(...a.perDoctor.map((d) => d.points), 1);
  const sortedByPoints = [...a.perDoctor].sort((x, y) => y.points - x.points);
  const pointsPanel = el('div', { class: 'panel' },
    el('h3', {}, icon('i-users'), 'Load per doctor'),
    el('div', { class: 'panel-sub' }, 'Total points earned across the period'),
    el('div', { class: 'bars' }, ...sortedByPoints.map((d, i) => bar(d.name, d.points, maxPts, {
      note: i === 0 ? 'heaviest' : i === sortedByPoints.length - 1 ? 'lightest' : '',
    }))));

  /* Weekend bars */
  const maxWe = Math.max(...a.perDoctor.map((d) => d.weekendShifts), 1);
  const weekendPanel = el('div', { class: 'panel' },
    el('h3', {}, icon('i-calendar'), 'Weekend & holiday duty'),
    el('div', { class: 'panel-sub' }, 'The nights people actually count'),
    el('div', { class: 'bars' }, ...[...a.perDoctor].sort((x, y) => y.weekendShifts - x.weekendShifts).map((d) =>
      bar(d.name, d.weekendShifts, maxWe, {
        valueText: `${d.weekendShifts}${d.holidayShifts ? ` +${d.holidayShifts}h` : ''}`,
      }))));

  /* Spacing strip */
  const list = days();
  const stripPanel = el('div', { class: 'panel', style: 'grid-column:1/-1' },
    el('h3', {}, icon('i-spark'), 'Rhythm'),
    el('div', { class: 'panel-sub' }, 'One block per night. Filled = on call, dimmed = weekend, amber = holiday, hatched = booked leave, ringed = back-to-back.'),
    el('div', { class: 'strip-rows' }, ...a.perDoctor.map((d) => {
      const strip = el('div', { class: 'strip' });
      for (const iso of list) {
        const on = d.dates.includes(iso);
        const b = el('b', { title: `${prettyDate(iso)}${on ? ' · on call' : isOff(d.name, iso) ? ' · leave' : ''}` });
        if (on) {
          b.classList.add('on');
          if (state.holidays.has(iso)) b.classList.add('hol');
          else if (isWeekend(iso)) b.classList.add('we');
          if (d.dates.includes(addDays(iso, 1)) || d.dates.includes(addDays(iso, -1))) b.classList.add('b2b');
        } else if (isOff(d.name, iso)) b.classList.add('off');
        strip.append(b);
      }
      return el('div', { class: 'strip-row' },
        el('div', { class: 'sl' }, el('span', { title: d.name }, d.name)),
        strip);
    })));

  /* Table */
  const rows = a.perDoctor.map((d) => el('tr', {},
    el('td', {}, el('div', { class: 'cell-doc' },
      el('div', { class: 'avatar', style: `${avatarStyle()};width:22px;height:22px;font-size:9px` }, initials(d.name)),
      d.name)),
    state.graded
      ? el('td', {}, el('span', {
          class: 'tag',
          style: d.grade ? `color:${gradeColor(d.grade)}` : '',
        }, d.grade || '—'))
      : null,
    el('td', { class: 'num' }, String(d.shifts)),
    el('td', { class: 'num' }, String(d.weekendShifts)),
    el('td', { class: 'num' }, String(d.holidayShifts)),
    el('td', { class: 'num' }, fmt(d.points)),
    el('td', { class: 'num' }, d.minGap === null ? '—' : plural(d.minGap, 'night')),
    el('td', { class: 'num' }, d.avgGap === null ? '—' : fmt(d.avgGap)),
    el('td', {}, d.violations.length
      ? el('span', { class: 'tag bad' }, `${d.violations.length} leave clash`)
      : d.backToBack ? el('span', { class: 'tag warn' }, `${d.backToBack} back-to-back`)
        : el('span', { class: 'tag ok' }, 'clean')),
  ));

  const table = el('div', { class: 'panel', style: 'grid-column:1/-1' },
    el('h3', {}, icon('i-users'), 'Doctor by doctor'),
    el('div', { class: 'panel-sub' }, 'Gap = nights between consecutive shifts'),
    el('div', { class: 'tbl-wrap' }, el('table', { class: 'tbl' },
      el('thead', {}, el('tr', {},
        el('th', {}, 'Doctor'),
        state.graded ? el('th', {}, 'Grade') : null,
        el('th', { class: 'num' }, 'Shifts'),
        el('th', { class: 'num' }, 'Weekend'),
        el('th', { class: 'num' }, 'Holiday'),
        el('th', { class: 'num' }, 'Points'),
        el('th', { class: 'num' }, 'Min gap'),
        el('th', { class: 'num' }, 'Avg gap'),
        el('th', {}, 'Flags'))),
      el('tbody', {}, ...rows))));

  pane.replaceChildren(
    resultHeader(),
    el('div', { class: 'grid-2' }, overview, pointsPanel, weekendPanel, stripPanel, table));
}

function renderInsightsPane() {
  const pane = $('#pane-insights');
  const a = state.result.analysis;
  const order = { bad: 0, warn: 1, ok: 2, info: 3 };
  const findings = [...a.findings].sort((x, y) => order[x.severity] - order[y.severity]);

  pane.replaceChildren(resultHeader(), el('div', { class: 'findings' },
    ...findings.map((f) => el('div', { class: `finding sev-${f.severity}` },
      icon(f.severity === 'ok' ? 'i-check' : f.severity === 'info' ? 'i-bulb' : 'i-alert'),
      el('div', { class: 'f-body' },
        el('h4', {}, f.title),
        el('p', {}, f.body),
        f.chips?.length
          ? el('div', { class: 'f-list' }, ...f.chips.slice(0, 24).map((c) => el('span', {}, c)),
            f.chips.length > 24 ? el('span', {}, `+${f.chips.length - 24} more`) : null)
          : null)))));
}

/* ─────────────────────────── exports ─────────────────────────── */

function download(filename, text, mime = 'text/plain') {
  const url = URL.createObjectURL(new Blob([text], { type: `${mime};charset=utf-8` }));
  const a = el('a', { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const csvCell = (v) => (/[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));

function scheduleCsv() {
  const a = state.result.analysis;
  const gradeOf = Object.fromEntries(state.doctors.map((d) => [d.name, d.grade || '']));
  const rows = [['Date', 'Weekday', 'Weight', 'Doctors on call', 'Grades', 'Required', 'Assigned']];
  for (const night of a.perNight) {
    rows.push([
      night.iso, DOW[dowOf(night.iso)], fmt(night.weight),
      night.assigned.map((e) => e.name).join('; '),
      state.graded ? night.assigned.map((e) => gradeOf[e.name]).join('; ') : '',
      night.need, night.assigned.length,
    ]);
  }
  return rows.map((r) => r.map(csvCell).join(',')).join('\n');
}

function doctorCsv() {
  const a = state.result.analysis;
  const rows = [['Doctor', 'Grade', 'Shifts', 'Weekend shifts', 'Holiday shifts', 'Points', 'Min gap', 'Avg gap', 'Dates']];
  for (const d of a.perDoctor) {
    rows.push([d.name, d.grade, d.shifts, d.weekendShifts, d.holidayShifts, fmt(d.points),
      d.minGap ?? '', d.avgGap === null ? '' : fmt(d.avgGap), d.dates.join('; ')]);
  }
  return rows.map((r) => r.map(csvCell).join(',')).join('\n');
}

function icsFile() {
  const a = state.result.analysis;
  const stamp = new Date().toISOString().replace(/[-:]|\.\d{3}/g, '');
  const lines = [
    'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Night Shift Rota Studio//EN',
    'CALSCALE:GREGORIAN', 'METHOD:PUBLISH', `X-WR-CALNAME:Night shifts ${state.startDate} to ${state.endDate}`,
  ];
  let seq = 0;
  for (const night of a.perNight) {
    for (const entry of night.assigned) {
      const compact = night.iso.replace(/-/g, '');
      lines.push('BEGIN:VEVENT',
        `UID:${a.name.replace(/\s+/g, '-')}-${seq++}@night-shift`,
        `DTSTAMP:${stamp}`,
        `DTSTART;VALUE=DATE:${compact}`,
        `DTEND;VALUE=DATE:${addDays(night.iso, 1).replace(/-/g, '')}`,
        `SUMMARY:Night shift — ${entry.name}`,
        `DESCRIPTION:${fmt(entry.points)} points${state.holidays.has(night.iso) ? ' (public holiday)' : ''}`,
        'TRANSP:OPAQUE', 'END:VEVENT');
    }
  }
  lines.push('END:VCALENDAR');
  return lines.join('\r\n');
}

function highlightJson(obj) {
  return JSON.stringify(obj, null, 2)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/"([^"]+)":/g, '<span class="k">"$1"</span>:')
    .replace(/: "([^"]*)"/g, ': <span class="s">"$1"</span>')
    .replace(/: (-?\d+\.?\d*)/g, ': <span class="n">$1</span>');
}

function renderExportPane() {
  const pane = $('#pane-export');
  const { response, payload, analysis } = state.result;
  const slug = `night-shift-${state.startDate}-to-${state.endDate}`;

  const card = (iconId, title, sub, onclick) => el('button', { class: 'export-card', onclick },
    icon(iconId), el('b', {}, title), el('span', {}, sub));

  pane.replaceChildren(resultHeader(),
    el('div', { class: 'export-grid' },
      card('i-download', 'Rota as CSV', 'One row per night with everyone on call — opens in Excel or Sheets.',
        () => { download(`${slug}.csv`, scheduleCsv(), 'text/csv'); toast('ok', 'CSV downloaded'); }),
      card('i-users', 'Workload as CSV', 'Per-doctor totals: shifts, weekends, holidays, points and gaps.',
        () => { download(`${slug}-workload.csv`, doctorCsv(), 'text/csv'); toast('ok', 'Workload CSV downloaded'); }),
      card('i-calendar', 'Calendar file (.ics)', `${analysis.assignedCount} all-day events — import into Outlook, Google or Apple Calendar.`,
        () => { download(`${slug}.ics`, icsFile(), 'text/calendar'); toast('ok', 'Calendar file downloaded'); }),
      card('i-print', 'Print / PDF', 'A clean ward-noticeboard layout, no controls.', () => window.print()),
      card('i-copy', 'Copy JSON', 'The raw API response, for pasting elsewhere.',
        async () => {
          try {
            await navigator.clipboard.writeText(JSON.stringify(response, null, 2));
            toast('ok', 'Response copied to clipboard');
          } catch { toast('err', 'Clipboard blocked', 'Select the JSON below and copy manually.'); }
        }),
      card('i-spark', 'Copy request payload', 'Reproduce this exact run against the API.',
        async () => {
          try {
            await navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
            toast('ok', 'Payload copied to clipboard');
          } catch { toast('err', 'Clipboard blocked'); }
        })),
    el('div', { class: 'panel' },
      el('h3', {}, icon('i-download'), 'API response'),
      el('div', { class: 'panel-sub' }, `${analysis.name} · score ${fmt(analysis.score, 3)}`),
      el('pre', { class: 'json', html: highlightJson(response) })));
}

/* ─────────────────────────── history ─────────────────────────── */

function renderHistoryPane() {
  const pane = $('#pane-history');
  if (!state.runs.length) {
    pane.replaceChildren(el('div', { class: 'empty-note' }, 'No runs yet. Generated rotas are kept here so you can compare and restore them.'));
    return;
  }

  const best = Math.min(...state.runs.map((r) => r.score ?? Infinity));
  const rows = state.runs.map((run) => {
    const when = new Date(run.at);
    const isCurrent = state.result?.analysis.name === run.id;
    return el('div', { class: `run-row${isCurrent ? ' is-current' : ''}` },
      el('div', { class: 'run-when' }, when.toLocaleDateString(undefined, { day: 'numeric', month: 'short' }),
        el('div', {}, when.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }))),
      el('div', { class: 'run-main' },
        el('b', {}, `${plural(run.doctors, 'doctor')} · ${plural(run.nights, 'night')}${run.graded ? ' · graded' : ''}`),
        el('span', {}, `${run.id} · ${fmt(run.elapsed)}s${run.score === best ? ' · best score so far' : ''}`)),
      el('div', { class: 'run-metrics' },
        el('div', {}, el('span', {}, 'Balance'), el('b', {}, `${fmt(run.balance, 0)}%`)),
        el('div', {}, el('span', {}, 'Score'), el('b', {}, fmt(run.score, 2))),
        el('div', {}, el('span', {}, 'Issues'), el('b', { style: run.issues ? 'color:var(--warn)' : 'color:var(--ok)' }, String(run.issues)))),
      el('div', { class: 'run-actions' },
        isCurrent ? null : el('button', {
          class: 'btn btn-ghost', onclick: () => restoreRun(run),
        }, 'Open'),
        el('button', {
          class: 'btn btn-ghost', title: 'Delete',
          onclick: () => { state.runs = state.runs.filter((r) => r !== run); saveRuns(); renderHistoryPane(); },
        }, icon('i-x'))));
  });

  pane.replaceChildren(
    el('div', { class: 'result-head' },
      el('div', { class: 'result-title' },
        el('h2', {}, 'Run history'),
        el('span', { class: 'sub' }, `${plural(state.runs.length, 'rota')} kept on this device`)),
      el('div', { class: 'result-actions' },
        el('button', {
          class: 'btn btn-ghost',
          onclick: () => { state.runs = []; saveRuns(); renderHistoryPane(); },
        }, 'Clear history'))),
    el('div', { class: 'runs' }, ...rows));
}

function restoreRun(run) {
  const { payload, response } = run.snapshot;
  state.result = {
    payload, response,
    analysis: analyse(response, payload),
    meta: { elapsed: run.elapsed, at: run.at },
  };
  state.focusDoctor = null;
  $('#emptyState').hidden = true;
  renderResult();
  toast('info', 'Rota restored', run.id);
}

/* ─────────────────────────── tabs, toasts, chrome ─────────────────────────── */

/** On a stacked (phone) layout the workspace sits below a tall config panel. */
function revealResults() {
  if (window.matchMedia('(min-width: 901px)').matches) return;
  const tabs = $('#tabs');
  if (tabs) tabs.scrollIntoView({ behavior: 'smooth', block: 'start' });
}


function showTab(tab) {
  state.activeTab = tab;
  $$('.tab').forEach((b) => b.classList.toggle('is-active', b.dataset.tab === tab));
  const hasResult = !!state.result;
  $$('.pane').forEach((p) => { p.hidden = !hasResult || p.id !== `pane-${tab}`; });
  if (!hasResult) {
    // History survives a page reload even without a current result.
    if (tab === 'history' && state.runs.length) {
      $('#emptyState').hidden = true;
      $('#pane-history').hidden = false;
      renderHistoryPane();
    } else {
      $('#emptyState').hidden = false;
    }
  }
}

function toast(kind, title, body = '') {
  const node = el('div', { class: `toast ${kind}` },
    icon(kind === 'ok' ? 'i-check' : kind === 'err' ? 'i-alert' : 'i-bulb'),
    el('div', {}, el('b', {}, title), body ? el('p', {}, body) : null));
  $('#toasts').append(node);
  setTimeout(() => {
    node.classList.add('out');
    setTimeout(() => node.remove(), 260);
  }, kind === 'err' ? 9000 : 4200);
}

function applyTheme() {
  document.documentElement.dataset.theme = state.theme;
  $('#themeBtn').replaceChildren(icon(state.theme === 'dark' ? 'i-sun' : 'i-moon'));
}

function addDoctors(raw) {
  const names = raw.split(/[,\n;]/).map((s) => s.trim()).filter(Boolean);
  let added = 0;
  for (const name of names) {
    if (state.doctors.some((d) => d.name.toLowerCase() === name.toLowerCase())) continue;
    state.doctors.push({ name, grade: state.graded ? (state.grades[0] || '') : '' });
    added++;
  }
  if (added) onConfigChange();
  return added;
}

function loadDemo() {
  state.doctors = [
    'Dr. Amara Osei', 'Dr. Bilal Haddad', 'Dr. Chen Wei', 'Dr. Dara Nolan',
    'Dr. Elias Fournier', 'Dr. Farah Rahimi', 'Dr. Gio Ferrari', 'Dr. Hana Kim',
    'Dr. Ivan Petrov', 'Dr. Júlia Costa',
  ].map((name) => ({ name, grade: '' }));
  state.graded = false;
  state.coverage = 'same';
  state.perNight = 2;
  state.perNightMap = {};
  state.effort = 2;

  const list = days();
  state.holidays = new Set(list.filter((iso) => dateOf(iso).getDate() === 15).slice(0, 1));
  state.unavailable = {
    'Dr. Chen Wei': new Set(list.slice(4, 9)),
    'Dr. Hana Kim': new Set(list.slice(18, 22)),
  };
  state.availDoctor = state.doctors[0].name;
  onConfigChange();
  toast('info', 'Demo department loaded', '10 doctors, 2 on call each night, two blocks of leave and one public holiday.');
}

/* ─────────────────────────── wiring ─────────────────────────── */

function wire() {
  $('#startDate').addEventListener('change', (e) => { state.startDate = e.target.value; onConfigChange(); });
  $('#endDate').addEventListener('change', (e) => { state.endDate = e.target.value; onConfigChange(); });

  $$('.chip-btn[data-preset]').forEach((btn) => btn.addEventListener('click', () => {
    const now = new Date();
    const m = btn.dataset.preset === 'next-month' ? now.getMonth() + 1 : now.getMonth();
    if (btn.dataset.preset === '4-weeks') {
      state.startDate = isoOf(now);
      state.endDate = addDays(state.startDate, 27);
    } else {
      state.startDate = isoOf(new Date(now.getFullYear(), m, 1));
      state.endDate = isoOf(new Date(now.getFullYear(), m + 1, 0));
    }
    state.perNightMap = {};
    onConfigChange();
  }));

  const addFromInput = () => {
    const input = $('#doctorInput');
    const added = addDoctors(input.value);
    if (added) { input.value = ''; toast('ok', `${plural(added, 'doctor')} added`); }
    input.focus();
  };
  $('#addDoctorBtn').addEventListener('click', addFromInput);
  $('#doctorInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); addFromInput(); } });
  $('#doctorInput').addEventListener('paste', (e) => {
    const text = (e.clipboardData || window.clipboardData).getData('text');
    if (text && /[,\n;]/.test(text)) { e.preventDefault(); const n = addDoctors(text); toast('ok', `${plural(n, 'doctor')} added`); }
  });

  $('#demoBtn').addEventListener('click', loadDemo);
  $('#emptyDemoBtn').addEventListener('click', loadDemo);
  $('#clearRosterBtn').addEventListener('click', () => {
    state.doctors = []; state.unavailable = {}; state.availDoctor = null; onConfigChange();
  });

  $('#gradedToggle').addEventListener('change', (e) => {
    state.graded = e.target.checked;
    if (state.graded) state.doctors.forEach((d) => { if (!d.grade) d.grade = state.grades[0] || ''; });
    onConfigChange();
  });

  const addGrade = () => {
    const input = $('#gradeInput');
    const name = input.value.trim();
    if (name && !state.grades.includes(name)) { state.grades.push(name); input.value = ''; onConfigChange(); }
  };
  $('#addGradeBtn').addEventListener('click', addGrade);
  $('#gradeInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); addGrade(); } });

  $$('.seg-btn[data-coverage]').forEach((btn) => btn.addEventListener('click', () => {
    state.coverage = btn.dataset.coverage;
    onConfigChange();
  }));
  $('#perNight').addEventListener('input', (e) => {
    state.perNight = Math.max(0, Math.min(20, Number(e.target.value) || 0));
    onConfigChange();
  });
  $$('.step-btn').forEach((btn) => btn.addEventListener('click', () => {
    state.perNight = Math.max(0, Math.min(20, Number(state.perNight) + Number(btn.dataset.delta)));
    onConfigChange();
  }));
  $$('.chip-btn[data-bulk]').forEach((btn) => btn.addEventListener('click', () => {
    const mode = btn.dataset.bulk;
    for (const iso of days()) {
      if (mode === 'all-1') state.perNightMap[iso] = 1;
      else if (mode === 'all-2') state.perNightMap[iso] = 2;
      else if (mode === 'weekend-plus' && (isWeekend(iso) || state.holidays.has(iso))) {
        state.perNightMap[iso] = requiredOn(iso) + 1;
      }
    }
    onConfigChange();
  }));

  $('#availDoctor').addEventListener('change', (e) => { state.availDoctor = e.target.value; renderAvailCal(); });
  $('#effort').addEventListener('input', (e) => { state.effort = Number(e.target.value); renderEffort(); renderPreflight(); saveState(); });
  $('#generateBtn').addEventListener('click', generate);

  $$('.tab').forEach((btn) => btn.addEventListener('click', () => showTab(btn.dataset.tab)));

  $('#themeBtn').addEventListener('click', () => {
    state.theme = state.theme === 'dark' ? 'light' : 'dark';
    applyTheme();
    saveState();
    onConfigChange();
    if (state.result) renderResult();
  });

  const modal = $('#settingsModal');
  $('#settingsBtn').addEventListener('click', () => {
    $('#apiBase').value = state.apiBase;
    $('#autoSave').checked = state.autoSave;
    modal.showModal();
  });
  modal.addEventListener('close', () => {
    if (modal.returnValue !== 'save') return;
    state.apiBase = $('#apiBase').value.trim();
    state.autoSave = $('#autoSave').checked;
    if (!state.autoSave) { try { localStorage.removeItem(STORE_KEY); } catch { /* ignore */ } }
    saveState();
    checkApi();
    toast('ok', 'Settings saved');
  });

  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); generate(); }
  });
}

/* ─────────────────────────── boot ─────────────────────────── */

loadState();
applyTheme();
wire();
onConfigChange();
showTab(state.activeTab === 'history' ? 'history' : 'calendar');
checkApi();
