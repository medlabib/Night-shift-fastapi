/* ============================================================
   Night Shift · Rota Studio
   A zero-dependency frontend for the night-shift scheduling API.

   The interesting part of this app is not the form: it is the
   model of the backend's own rules (point weights + the rest
   window) that lets the UI predict infeasible rotas *before*
   asking for one, and audit whatever comes back.
   ============================================================ */

import { api, ApiError } from '/static/api.js';
import {
  LOCALES, t, setLocale, locale, direction, intlTag,
  fmtDate, monthLabel, weekdayNames, translateDom, detectLocale, num as fmtNumber,
} from '/static/i18n.js';

const STORE_KEY = 'nightshift.studio.v1';
const RUNS_KEY = 'nightshift.studio.runs.v1';
const PERF_KEY = 'nightshift.studio.perf.v1';

const EFFORTS = [
  { find: 50, key: 'draft' }, { find: 150, key: 'quick' }, { find: 400, key: 'balanced' },
  { find: 1200, key: 'thorough' }, { find: 3000, key: 'exhaustive' },
];

// Day and month names come from Intl per locale, not from a hard-coded
// English list, so Arabic and French get their own names and ordering.
const DOW = () => weekdayNames('short');
const DOW_SHORT = () => weekdayNames('narrow');

/* ─────────────────────────── date helpers ─────────────────────────── */
/* Everything is a local 'YYYY-MM-DD' string; Dates are only used for
   arithmetic and are always built at local midnight to dodge TZ drift. */

const dateOf = (iso) => new Date(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10));
const isoOf = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const addDays = (iso, n) => { const d = dateOf(iso); d.setDate(d.getDate() + n); return isoOf(d); };
const dowOf = (iso) => dateOf(iso).getDay();
const isWeekend = (iso) => { const w = dowOf(iso); return w === 0 || w === 6; };
const prettyDate = (iso) => fmtDate(iso);
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
  return fmtNumber(Math.round(n * 10 ** dp) / 10 ** dp, dp);
};
/** Counted nouns go through the catalog so each language uses its own
    plural categories — Arabic has six, English two. */
const UNIT_KEYS = {
  night: 'unit.night', doctor: 'unit.doctor', shift: 'unit.shift', rota: 'unit.rota',
  holiday: 'rules.holidays', view: 'share.views', request: 'unit.request',
};
const plural = (n, one, many) => {
  const key = UNIT_KEYS[one];
  if (key) return t(key, { count: n });
  return `${n} ${n === 1 ? one : (many || one + 's')}`;
};

/* ─────────────────────────── state ─────────────────────────── */

const today = new Date();
const defaultStart = isoOf(new Date(today.getFullYear(), today.getMonth() + 1, 1));
const defaultEnd = isoOf(new Date(today.getFullYear(), today.getMonth() + 2, 0));

const state = {
  theme: 'dark',
  locale: 'en',
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

  // Signed in, everything lives on the server and belongs to a department.
  // Signed out, the studio stays fully usable against the public endpoint.
  session: null,
  department: null,
  departments: [],
  serverSchedules: [],
  scheduleId: null,            // the saved schedule currently open
  validation: null,
  authMode: 'login',
  // An invitation opened before signing in: held until there is an account
  // to accept it as.
  pendingInvite: null,
};

const signedIn = () => state.session !== null;

/* ─────────────────────────── persistence ─────────────────────────── */

function saveState() {
  if (!state.autoSave) return;
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify({
      theme: state.theme, locale: state.locale, apiBase: state.apiBase, autoSave: state.autoSave,
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
    host.replaceChildren(el('div', { class: 'empty-note' }, t('roster.empty')));
  } else {
    host.replaceChildren(...state.doctors.map((doc) => {
      const offCount = state.unavailable[doc.name]?.size || 0;
      const row = el('div', { class: `doc-row${offCount ? ' has-blackout' : ''}` },
        el('div', { class: 'avatar', style: avatarStyle() }, initials(doc.name)),
        el('div', { class: 'doc-name', title: doc.name }, doc.name),
        offCount ? el('span', { class: 'doc-badge' }, t('roster.off', { count: offCount })) : null,
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
        class: 'doc-del', title: t('roster.remove', { name: doc.name }),
        'aria-label': t('roster.remove', { name: doc.name }),
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
  if (!state.doctors.length) sel.replaceChildren(el('option', {}, t('avail.addFirst')));
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
      ...DOW_SHORT().map((d, i) => el('div', { class: 'mc-dow', key: i }, d)));

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
      el('div', { class: 'mc-title' }, monthLabel(first.getFullYear(), first.getMonth())),
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
  $('#availNote').textContent = total
    ? t('avail.blocked', { nights: plural(total, 'night') }) : t('avail.none');

  const summary = $('#blackoutSummary');
  const entries = Object.entries(state.unavailable).filter(([, v]) => v.size);
  summary.replaceChildren(...entries.map(([doc, set]) =>
    el('div', { class: 'inline-actions', style: 'font-size:11.5px;color:var(--text-faint)' },
      el('b', { style: 'color:var(--text-dim);font-weight:600' }, doc),
      `${plural(set.size, 'night')} off`,
      el('button', {
        class: 'link-btn danger',
        onclick: () => { delete state.unavailable[doc]; onConfigChange(); },
      }, t('avail.clear')))));
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
    gradedHint.innerHTML = t('coverage.gradedNote', {
      grades: state.grades.length, total: state.perNight * state.grades.length,
    });
  }

  if (!same) renderCoverageCal();

  const list = days();
  const seats = list.reduce((s, iso) => s + requiredOn(iso), 0) * (state.graded ? Math.max(1, state.grades.length) : 1);
  $('#coverageNote').textContent = list.length
    ? t('coverage.total', { shifts: plural(seats, 'shift') }) : '—';
}

function renderPeriod() {
  $('#startDate').value = state.startDate;
  $('#endDate').value = state.endDate;
  const list = days();
  const weekends = list.filter(isWeekend).length;
  $('#periodNote').textContent = list.length
    ? t('period.summary', { nights: plural(list.length, 'night'), weekends })
    : t('period.invalid');
  $('#periodNote').classList.toggle('is-warn', !list.length);
}

function renderEffort() {
  const e = EFFORTS[state.effort];
  $('#effort').value = state.effort;
  $('#effortNote').textContent = t(`effort.${e.key}`);
  $('#effortHint').innerHTML = t('effort.hint', {
    count: e.find.toLocaleString(intlTag()), blurb: t(`effort.blurb.${e.key}`),
  });
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
  // Signed in, the rota is saved and becomes editable; signed out it is a
  // one-off answer from the public endpoint.
  if (signedIn() && state.department) return generateOnServer();

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
    toast('ok', t('toast.generated'), t('toast.generatedSub', {
      shifts: plural(analysis.assignedCount, 'shift'),
      seconds: fmt(elapsed), balance: fmt(analysis.balance, 0),
    }));
  } catch (err) {
    toast('err', t('toast.failed'), err.message);
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
      text.textContent = t('api.online');
      return;
    }
    throw new Error(String(res.status));
  } catch {
    pill.className = 'pill is-bad';
    text.textContent = t('api.offline');
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
  renderTeamPane();

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
    stat(t('stat.balance'), `${fmt(a.balance, 0)}%`, t('stat.balanceSub'),
      a.balance >= 92 ? 'tone-ok' : a.balance >= 80 ? '' : 'tone-warn'),
    stat(t('stat.coverage'), `${fmt(coverage, 0)}%`,
      t('stat.coverageSub', { assigned: a.assignedCount, required: a.requiredCount }),
      coverage >= 100 ? 'tone-ok' : coverage >= 90 ? 'tone-warn' : 'tone-bad'),
    stat(t('stat.pointsSpread'), fmt(a.pointsSpread), t('stat.pointsSpreadSub'),
      a.pointsSpread <= 1 ? 'tone-ok' : a.pointsSpread <= 3 ? 'tone-warn' : 'tone-bad'),
    stat(t('stat.weekendSpread'), fmt(a.weekendSpread, 0), t('stat.weekendSpreadSub'),
      a.weekendSpread <= 1 ? 'tone-ok' : 'tone-warn'),
    stat(t('stat.score'), fmt(a.score, 2), t('stat.scoreSub')),
  );
}

function renderCalendarPane() {
  const pane = $('#pane-calendar');
  const a = state.result.analysis;
  const gradeOf = Object.fromEntries(state.doctors.map((d) => [d.name, d.grade || '']));

  const actions = [];
  if (signedIn() && state.scheduleId) {
    actions.push(el('button', {
      class: 'btn btn-ghost',
      title: t('retuneHint'),
      onclick: async () => {
        try {
          const updated = await api.retune(state.department.id, state.scheduleId,
            { keep_locked: true, stay_close: true });
          adoptSchedule(updated);
          await refreshValidation();
          renderResult();
          toast('ok', t('toast.retuned'));
        } catch (err) { toast('err', t('toast.editRefused'), err.message); }
      },
    }, icon('i-history'), t('retune')));
  }
  actions.push(
    el('button', { class: 'btn btn-ghost', onclick: () => window.print() }, icon('i-print'), t('print')),
    el('button', { class: 'btn btn-primary', onclick: generate }, icon('i-spark'), t('regenerate')),
  );

  const filter = el('div', { class: 'doc-filter' },
    ...state.doctors.map((doc) => el('button', {
      class: `df-chip${state.focusDoctor === doc.name ? ' is-on' : ''}`,
      title: `Show only ${doc.name}'s nights`,
      onclick: () => { state.focusDoctor = state.focusDoctor === doc.name ? null : doc.name; renderCalendarPane(); },
    }, doc.name)));

  const legend = el('div', { class: 'legend' },
    el('span', { class: 'lg' }, el('span', { class: 'sw', style: 'background:var(--holiday-bg);border-color:var(--holiday)' }), t('legend.holiday')),
    el('span', { class: 'lg' }, el('span', { class: 'sw', style: 'background:var(--weekend-bg)' }), t('legend.weekend')),
    el('span', { class: 'lg' }, el('span', { class: 'sw', style: 'border-color:var(--danger)' }), t('legend.short')),
    el('span', { class: 'lg' }, el('span', { class: 'sw', style: 'box-shadow:inset 0 0 0 1px var(--warn)' }), t('legend.b2b')),
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
      ...DOW().map((d) => el('div', { class: 'cal-dow' }, d)));

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
        if (a.locked?.has(`${entry.name}|${night.iso}`)) {
          chip.classList.add('is-locked');
          chip.append(el('span', { class: 'cd-pin', title: t('menu.pinned') }, '●'));
        }
        if (signedIn() && state.scheduleId) {
          chip.classList.add('is-editable');
          chip.tabIndex = 0;
          chip.title += ' · click to swap, pin or remove';
          chip.addEventListener('click', (e) => { e.stopPropagation(); openShiftMenu(entry, night.iso, chip); });
          chip.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openShiftMenu(entry, night.iso, chip); }
          });
        }
        docs.append(chip);
      }
      cell.append(docs);

      if (night.short > 0) {
        cell.append(el('span', { class: 'cal-flag' }, night.assigned.length
          ? t('cal.shortBy', { count: night.short }) : t('cal.unfilled')));
      }
      grid.append(cell);
    }

    const filled = nights.reduce((s, n) => s + n.assigned.length, 0);
    months.append(el('div', {},
      el('div', { class: 'month-title' },
        monthLabel(first.getFullYear(), first.getMonth()),
        el('span', { class: 'm-meta' },
          t('cal.months', { nights: plural(nights.length, 'night'), shifts: plural(filled, 'shift') }))),
      grid));
  }

  pane.replaceChildren(
    ...[resultHeader(actions), statStrip(), validationBanner(), legend, filter, months]
      .filter(Boolean));
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

/**
 * What each doctor brought in from earlier months.
 *
 * Without this the pane says someone is lightly loaded and looks wrong. With
 * it, a light month reads as what it is: payback for a heavy one.
 */
function carriedForwardNote() {
  const metrics = state.result?.response?.metrics;
  if (!metrics?.carry_forward) return null;

  const people = Object.values(metrics.per_doctor || {})
    .filter((d) => d.prior_points || d.new_this_period)
    .sort((x, y) => y.prior_points - x.prior_points);
  if (!people.length) return null;

  const days = state.result?.payload?.carry_forward_days || 90;
  return el('div', { class: 'panel', style: 'grid-column:1/-1' },
    el('h3', {}, icon('i-history'), t('fair.carried')),
    el('div', { class: 'panel-sub' }, t('fair.carryNote', { days })),
    el('div', { class: 'carry-rows' }, ...people.map((d) => el('div', { class: 'carry-row' },
      el('span', {}, d.name),
      el('b', {}, `${fmt(d.prior_points)} ${t('fair.points.word')}`),
      el('em', {}, d.new_this_period
        ? t('fair.newJoiner')
        : `${t('fair.cumulative')} ${fmt(d.cumulative_points)}`)))));
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
    <div class="gauge-num">${fmt(a.balance, 0)}<small>${t('fair.balanceLabel')}</small></div>`;
  requestAnimationFrame(() => {
    const c = gauge.querySelector('.val');
    if (c) c.style.strokeDashoffset = String(circ * (1 - a.balance / 100));
  });

  const lightest = [...a.perDoctor].sort((x, y) => x.points - y.points)[0];
  const heaviest = [...a.perDoctor].sort((x, y) => y.points - x.points)[0];

  const overview = el('div', { class: 'panel' },
    el('h3', {}, icon('i-scale'), t('fair.points')),
    el('div', { class: 'panel-sub' }, t('fair.pointsSub')),
    el('div', { class: 'gauge-wrap' }, gauge,
      el('div', { class: 'gauge-legend' },
        el('div', {}, `${t('fair.average')} `, el('b', {}, `${fmt(a.mean)} ${t('fair.points.word')}`)),
        heaviest ? el('div', {}, `${t('fair.heaviest')} `, el('b', {}, `${heaviest.name} · ${fmt(heaviest.points)}`)) : null,
        lightest ? el('div', {}, `${t('fair.lightest')} `, el('b', {}, `${lightest.name} · ${fmt(lightest.points)}`)) : null,
        el('div', {}, `${t('fair.spread')} `, el('b', {}, fmt(a.pointsSpread)), ` ${t('fair.points.word')}`))));

  /* Points bars */
  const maxPts = Math.max(...a.perDoctor.map((d) => d.points), 1);
  const sortedByPoints = [...a.perDoctor].sort((x, y) => y.points - x.points);
  const pointsPanel = el('div', { class: 'panel' },
    el('h3', {}, icon('i-users'), t('fair.load')),
    el('div', { class: 'panel-sub' }, t('fair.loadSub')),
    el('div', { class: 'bars' }, ...sortedByPoints.map((d, i) => bar(d.name, d.points, maxPts, {
      note: i === 0 ? t('fair.heaviest') : i === sortedByPoints.length - 1 ? t('fair.lightest') : '',
    }))));

  /* Weekend bars */
  const maxWe = Math.max(...a.perDoctor.map((d) => d.weekendShifts), 1);
  const weekendPanel = el('div', { class: 'panel' },
    el('h3', {}, icon('i-calendar'), t('fair.weekend')),
    el('div', { class: 'panel-sub' }, t('fair.weekendSub')),
    el('div', { class: 'bars' }, ...[...a.perDoctor].sort((x, y) => y.weekendShifts - x.weekendShifts).map((d) =>
      bar(d.name, d.weekendShifts, maxWe, {
        valueText: `${d.weekendShifts}${d.holidayShifts ? ` +${d.holidayShifts}h` : ''}`,
      }))));

  /* Spacing strip */
  const list = days();
  const stripPanel = el('div', { class: 'panel', style: 'grid-column:1/-1' },
    el('h3', {}, icon('i-spark'), t('fair.rhythm')),
    el('div', { class: 'panel-sub' }, t('fair.rhythmSub')),
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
      ? el('span', { class: 'tag bad' }, t('flag.leaveClash', { count: d.violations.length }))
      : d.backToBack ? el('span', { class: 'tag warn' }, t('flag.b2b', { count: d.backToBack }))
        : el('span', { class: 'tag ok' }, t('flag.clean'))),
  ));

  const table = el('div', { class: 'panel', style: 'grid-column:1/-1' },
    el('h3', {}, icon('i-users'), t('fair.table')),
    el('div', { class: 'panel-sub' }, t('fair.tableSub')),
    el('div', { class: 'tbl-wrap' }, el('table', { class: 'tbl' },
      el('thead', {}, el('tr', {},
        el('th', {}, t('th.doctor')),
        state.graded ? el('th', {}, t('th.grade')) : null,
        el('th', { class: 'num' }, t('th.shifts')),
        el('th', { class: 'num' }, t('th.weekend')),
        el('th', { class: 'num' }, t('th.holiday')),
        el('th', { class: 'num' }, t('th.pointsCol')),
        el('th', { class: 'num' }, t('th.minGap')),
        el('th', { class: 'num' }, t('th.avgGap')),
        el('th', {}, t('th.flags')))),
      el('tbody', {}, ...rows))));

  pane.replaceChildren(
    resultHeader(),
    el('div', { class: 'grid-2' },
      overview, pointsPanel, weekendPanel, carriedForwardNote(), stripPanel, table));
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
      night.iso, DOW()[dowOf(night.iso)], fmt(night.weight),
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
      card('i-download', t('export.csv'), 'One row per night with everyone on call — opens in Excel or Sheets.',
        () => { download(`${slug}.csv`, scheduleCsv(), 'text/csv'); toast('ok', t('toast.downloaded')); }),
      card('i-users', t('export.workload'), 'Per-doctor totals: shifts, weekends, holidays, points and gaps.',
        () => { download(`${slug}-workload.csv`, doctorCsv(), 'text/csv'); toast('ok', t('toast.downloaded')); }),
      card('i-calendar', 'Calendar file (.ics)', `${analysis.assignedCount} all-day events — import into Outlook, Google or Apple Calendar.`,
        () => { download(`${slug}.ics`, icsFile(), 'text/calendar'); toast('ok', t('toast.downloaded')); }),
      card('i-print', t('export.print'), 'A clean ward-noticeboard layout, no controls.', () => window.print()),
      card('i-copy', t('export.json'), 'The raw API response, for pasting elsewhere.',
        async () => {
          try {
            await navigator.clipboard.writeText(JSON.stringify(response, null, 2));
            toast('ok', t('toast.copied'));
          } catch { toast('err', t('toast.clipboardBlocked')); }
        }),
      ...(signedIn() && state.scheduleId ? [
        card('i-print', t('export.pdfDiary'), 'One row per night, A4 portrait. Rendered on the server.',
          () => window.open(`${api.pdfUrl(state.department.id, state.scheduleId, 'vertical')}&lang=${locale()}`, '_blank')),
        card('i-users', t('export.pdfWall'), 'Doctors as columns, A4 landscape.',
          () => window.open(`${api.pdfUrl(state.department.id, state.scheduleId, 'horizontal')}&lang=${locale()}`, '_blank')),
        card('i-calendar', t('export.pdfBoard'), 'Month grid, A4 landscape.',
          () => window.open(`${api.pdfUrl(state.department.id, state.scheduleId, 'calendar')}&lang=${locale()}`, '_blank')),
        card('i-spark', t('export.share'), 'A read-only page anyone can open without an account.',
          createShareLink),
      ] : []),
      card('i-spark', t('export.payload'), 'Reproduce this exact run against the API.',
        async () => {
          try {
            await navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
            toast('ok', t('toast.copied'));
          } catch { toast('err', t('toast.clipboardBlocked')); }
        })),
    ...(signedIn() && state.scheduleId ? [el('div', { class: 'panel', id: 'sharePanel' })] : []),
    el('div', { class: 'panel' },
      el('h3', {}, icon('i-download'), t('export.response')),
      el('div', { class: 'panel-sub' }, `${analysis.name} · score ${fmt(analysis.score, 3)}`),
      el('pre', { class: 'json', html: highlightJson(response) })));

  renderSharePanel();
}

/* ─────────────────────────── history ─────────────────────────── */

function renderHistoryPane() {
  const pane = $('#pane-history');
  if (signedIn()) return renderSavedSchedules(pane);
  if (!state.runs.length) {
    pane.replaceChildren(el('div', { class: 'empty-note' }, t('history.emptyLocal')));
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
        }, t('history.open')),
        el('button', {
          class: 'btn btn-ghost', title: 'Delete',
          onclick: () => { state.runs = state.runs.filter((r) => r !== run); saveRuns(); renderHistoryPane(); },
        }, icon('i-x'))));
  });

  pane.replaceChildren(
    el('div', { class: 'result-head' },
      el('div', { class: 'result-title' },
        el('h2', {}, t('history.local')),
        el('span', { class: 'sub' }, t('history.localSub', { count: plural(state.runs.length, 'rota') }))),
      el('div', { class: 'result-actions' },
        el('button', {
          class: 'btn btn-ghost',
          onclick: () => { state.runs = []; saveRuns(); renderHistoryPane(); },
        }, t('history.clear')))),
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
  toast('info', t('toast.restored'), run.id);
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
  if (hasResult) return;

  // Two panes stand on their own: the team is about people rather than any
  // one rota, and history survives a page reload — from this device's run
  // log signed out, and from the department's saved rotas signed in.
  const hasHistory = state.runs.length || (signedIn() && state.serverSchedules.length);
  const standalone =
    (tab === 'team' && signedIn()) || (tab === 'history' && hasHistory);
  $('#emptyState').hidden = standalone;
  if (!standalone) return;

  $(`#pane-${tab}`).hidden = false;
  if (tab === 'team') renderTeamPane();
  else renderHistoryPane();
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
  toast('info', t('toast.demo'), t('toast.demoSub'));
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
    if (text && /[,\n;]/.test(text)) { e.preventDefault(); const n = addDoctors(text); toast('ok', t('roster.added', { count: plural(n, 'doctor') })); }
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
    toast('ok', t('settings.saved'));
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

/* ═══════════════════════════ signed-in mode ═══════════════════════════

   Everything below only runs with a session. The signed-out studio keeps
   working exactly as before, so the tool is usable without an account and
   an account adds persistence rather than gating entry.
   ═══════════════════════════════════════════════════════════════════ */

function applySession(payload) {
  state.session = payload?.user || null;
  state.departments = payload?.departments || [];
  if (!state.departments.some((d) => d.id === state.department?.id)) {
    state.department = state.departments[0] || null;
  }
  renderAccount();
}

function renderAccount() {
  const picker = $('#departmentPicker');
  const account = $('#accountBtn');
  const signIn = $('#signInBtn');

  if (!signedIn()) {
    signIn.hidden = false;
    account.hidden = true;
    picker.hidden = true;
    return;
  }

  signIn.hidden = true;
  account.hidden = false;
  account.textContent = state.session.name || state.session.email;
  account.title = t('auth.signOutTitle', { email: state.session.email });

  picker.hidden = state.departments.length < 2;
  picker.replaceChildren(...state.departments.map((d) =>
    el('option', { value: d.id, selected: d.id === state.department?.id }, d.name)));
}

/** Pull the department's roster into the local editor model. */
async function loadRoster() {
  if (!signedIn() || !state.department) return;
  const doctors = await api.doctors(state.department.id);
  state.doctors = doctors.map((d) => ({ id: d.id, name: d.name, grade: d.grade || '' }));
  state.unavailable = {};
  for (const d of doctors) {
    if (d.leave?.length) state.unavailable[d.name] = new Set(d.leave);
  }
  state.graded = state.doctors.some((d) => d.grade);
  if (state.graded) {
    state.grades = [...new Set(state.doctors.map((d) => d.grade).filter(Boolean))];
  }
  state.availDoctor = state.doctors[0]?.name || null;
  onConfigChange();
}

/** Mirror roster edits to the server, so the next visit sees the same team. */
async function syncRoster() {
  if (!signedIn() || !state.department) return;
  const dep = state.department.id;
  const existing = await api.doctors(dep);
  const byName = new Map(existing.map((d) => [d.name, d]));

  for (const doc of state.doctors) {
    const server = byName.get(doc.name);
    if (!server) {
      const created = await api.addDoctor(dep, { name: doc.name, grade: doc.grade || null });
      doc.id = created.id;
    } else {
      doc.id = server.id;
      if ((server.grade || '') !== (doc.grade || '')) {
        await api.updateDoctor(dep, server.id, { name: doc.name, grade: doc.grade || null });
      }
    }
    byName.delete(doc.name);
  }
  // Anyone left in the map was removed locally.
  for (const gone of byName.values()) await api.removeDoctor(dep, gone.id);

  for (const doc of state.doctors) {
    const dates = [...(state.unavailable[doc.name] || [])].sort();
    const server = existing.find((d) => d.name === doc.name);
    const before = (server?.leave || []).slice().sort();
    if (dates.join() !== before.join()) await api.setLeave(dep, doc.id, dates);
  }
}

function generatePayload() {
  const list = days();
  const same = state.coverage === 'same';
  return {
    name: `Rota ${prettyDate(state.startDate)} – ${prettyDate(state.endDate)}`,
    start_date: state.startDate,
    end_date: state.endDate,
    coverage: same ? Number(state.perNight) : Number(state.perNight),
    coverage_by_date: same ? {} : Object.fromEntries(list.map((iso) => [iso, requiredOn(iso)])),
    graded: state.graded,
    grades: state.graded ? [...state.grades] : [],
    holidays: [...state.holidays].sort(),
    min_rest_nights: 1,
  };
}

/** Turn a saved ScheduleOut into the shape the existing renderers expect. */
function adoptSchedule(schedule, elapsed = 0) {
  const nights = {};
  for (const row of schedule.assignments) {
    (nights[row.date] ||= []).push([row.doctor_name, row.points]);
  }
  const per = schedule.metrics?.per_doctor || {};
  const response = {
    schedule: nights,
    points: Object.fromEntries(Object.values(per).map((v) => [v.name, v.points])),
    num_shifts: Object.fromEntries(Object.values(per).map((v) => [v.name, v.shifts])),
    num_weekend_shifts: Object.fromEntries(
      Object.values(per).map((v) => [v.name, v.weekend_shifts])),
    schedule_name: schedule.name,
    score: schedule.metrics?.points_spread ?? 0,
    // Kept whole so panes can read what the analysis does not model —
    // carried-forward balance, for one.
    metrics: schedule.metrics || {},
  };

  state.scheduleId = schedule.id;
  state.startDate = schedule.start_date;
  state.endDate = schedule.end_date;
  state.holidays = new Set(schedule.config?.holidays || []);
  state.perNight = schedule.config?.coverage ?? state.perNight;

  const payload = { ...generatePayload(), ...(schedule.config || {}), find: 0 };
  state.result = {
    payload,
    response,
    analysis: analyse(response, { department_is_graded: schedule.config?.graded ? 'Y' : 'N' }),
    meta: { elapsed: elapsed || schedule.solve_seconds || 0, at: Date.now() },
    saved: schedule,
  };
  // Locks and shortfalls come from the server, not from re-derivation.
  state.result.analysis.locked = new Set(
    schedule.assignments.filter((a) => a.locked).map((a) => `${a.doctor_name}|${a.date}`));
  state.result.analysis.serverShortfalls = schedule.shortfalls || [];
  state.focusDoctor = null;
}

async function generateOnServer() {
  const overlay = $('#runOverlay');
  const started = performance.now();
  overlay.hidden = false;
  $('#generateBtn').disabled = true;
  $('#runDetail').textContent = 'Saving roster and solving';
  $('#runBarFill').style.width = '40%';

  try {
    await syncRoster();
    const schedule = await api.generate(state.department.id, generatePayload());
    adoptSchedule(schedule, (performance.now() - started) / 1000);
    await refreshValidation();
    await loadServerSchedules();
    $('#emptyState').hidden = true;
    renderResult();
    revealResults();
    const m = schedule.metrics || {};
    toast('ok', t('toast.saved'), t('toast.generatedSub', {
      shifts: plural(m.assigned, 'shift'),
      seconds: fmt(schedule.solve_seconds || 0), balance: fmt(m.balance, 0),
    }));
  } catch (err) {
    const reasons = err instanceof ApiError ? err.reasons : [];
    toast('err', t('toast.failed'), reasons.length ? reasons.join(' ') : err.message);
  } finally {
    overlay.hidden = true;
    renderPreflight();
  }
}

async function loadServerSchedules() {
  if (!signedIn() || !state.department) return;
  state.serverSchedules = await api.schedules(state.department.id);
  renderHistoryPane();
}

async function refreshValidation() {
  if (!signedIn() || !state.scheduleId) { state.validation = null; return; }
  try {
    state.validation = await api.validate(state.department.id, state.scheduleId);
  } catch {
    state.validation = null;
  }
}

/** Re-read the open schedule after an edit and repaint everything. */
async function refreshSchedule() {
  const schedule = await api.schedule(state.department.id, state.scheduleId);
  adoptSchedule(schedule);
  await refreshValidation();
  renderResult();
}

async function editAssignment(action, body) {
  if (!signedIn() || !state.scheduleId) return;
  try {
    await api[action](state.department.id, state.scheduleId, body);
    await refreshSchedule();
  } catch (err) {
    toast('err', t('toast.editRefused'), err.message);
  }
}

/** The menu shown when a coordinator taps someone on the calendar. */
function openShiftMenu(entry, iso, anchor) {
  if (!signedIn() || !state.scheduleId) return;
  $('#shiftMenu')?.remove();

  const doctor = state.doctors.find((d) => d.name === entry.name);
  if (!doctor) return;
  const onCall = new Set((state.result.analysis.model.nights.get(iso) || []).map((e) => e.name));
  const locked = state.result.analysis.locked?.has(`${entry.name}|${iso}`);

  const menu = el('div', { class: 'shift-menu', id: 'shiftMenu' },
    el('div', { class: 'sm-head' }, t('menu.on', { name: entry.name, date: prettyDate(iso) })),
    el('button', {
      class: 'sm-item',
      onclick: () => { closeShiftMenu(); editAssignment('unassign', { doctor_id: doctor.id, date: iso }); },
    }, t('menu.takeOff')),
    el('button', {
      class: 'sm-item',
      onclick: () => {
        closeShiftMenu();
        editAssignment('lock', { doctor_id: doctor.id, date: iso, locked: !locked });
      },
    }, locked ? t('menu.unpin') : t('menu.pin')),
    el('div', { class: 'sm-label' }, t('menu.swapWith')),
  );

  const candidates = state.doctors.filter((d) => !onCall.has(d.name));
  if (!candidates.length) {
    menu.append(el('div', { class: 'sm-empty' }, t('menu.allOn')));
  }
  for (const other of candidates.slice(0, 12)) {
    const off = isOff(other.name, iso);
    menu.append(el('button', {
      class: `sm-item${off ? ' is-warn' : ''}`,
      title: off ? `${other.name} is on leave that night` : '',
      onclick: () => {
        closeShiftMenu();
        editAssignment('swap', { date: iso, doctor_out: doctor.id, doctor_in: other.id });
      },
    }, other.name, off ? el('span', { class: 'sm-tag' }, t('menu.onLeave')) : null));
  }

  document.body.append(menu);
  const box = anchor.getBoundingClientRect();
  const width = 232;
  menu.style.left = `${Math.min(box.left, window.innerWidth - width - 12)}px`;
  menu.style.top = `${Math.min(box.bottom + 6, window.innerHeight - menu.offsetHeight - 12)}px`;
  setTimeout(() => document.addEventListener('click', closeShiftMenu, { once: true }), 0);
}

function closeShiftMenu() {
  $('#shiftMenu')?.remove();
}

/* ───────────────────────────── auth screen ───────────────────────────── */

function openAuth(mode = 'login') {
  state.authMode = mode;
  const signup = mode === 'signup';
  $('#authTitle').textContent = signup ? t('auth.signUp') : t('auth.signIn');
  $('#authSubmit').textContent = signup ? t('auth.create') : t('auth.signIn');
  $('#authNameField').hidden = !signup;
  $('#authDeptField').hidden = !signup;
  $('#authSwitchText').textContent = signup ? t('auth.haveAccount') : t('auth.noAccount');
  $('#authSwitch').textContent = signup ? t('auth.signIn') : t('auth.createOne');
  $('#authPassword').autocomplete = signup ? 'new-password' : 'current-password';
  $('#authError').hidden = true;
  $('#authModal').showModal();
  $('#authEmail').focus();
}

async function submitAuth(event) {
  event.preventDefault();
  const email = $('#authEmail').value.trim();
  const password = $('#authPassword').value;
  const error = $('#authError');
  const submit = $('#authSubmit');
  submit.disabled = true;

  try {
    const payload = state.authMode === 'signup'
      ? await api.signup({
        email, password,
        name: $('#authName').value.trim() || email.split('@')[0],
        department_name: $('#authDept').value.trim() || null,
      })
      : await api.login(email, password);

    applySession(payload);
    $('#authModal').close();

    // A roster built while signed out is worth keeping.
    const carried = state.doctors.length;
    const remote = await api.doctors(state.department.id);
    if (carried && !remote.length) {
      await syncRoster();
      toast('ok', t('auth.signedIn', { name: state.session.name }),
        t('auth.carried', { count: plural(carried, 'doctor') }));
    } else {
      await loadRoster();
      toast('ok', t('auth.signedIn', { name: state.session.name }), state.department?.name || '');
    }
    await loadServerSchedules();
    // Now there is an account, an invitation opened from an email can be
    // accepted. It takes over from the department signup just created.
    if (state.pendingInvite) {
      const token = state.pendingInvite;
      state.pendingInvite = null;
      await acceptInvitation(token);
    }
    await loadTeam();
    renderPreflight();
    if (state.locale !== 'en') api.setLocale(state.locale).catch(() => {});
  } catch (err) {
    error.textContent = err.message;
    error.hidden = false;
  } finally {
    submit.disabled = false;
  }
}

async function signOut() {
  await api.logout().catch(() => {});
  state.session = null;
  state.department = null;
  state.departments = [];
  state.serverSchedules = [];
  state.scheduleId = null;
  state.validation = null;
  await loadTeam();
  renderAccount();
  renderHistoryPane();
  renderTeamPane();
  toast('info', t('auth.signedOut'), t('auth.signedOutSub'));
}

async function bootSession() {
  api.base = state.apiBase;
  try {
    const payload = await api.session();
    applySession(payload);
    if (state.department) {
      await loadRoster();
      await loadServerSchedules();
      await loadTeam();
    }
  } catch {
    applySession(null); // not signed in: stay in local mode
  }
  await handleEmailLink();
}

/* ─────────────────── links that arrive by email ─────────────────── */

/**
 * `/join/<token>` and `/reset/<token>` are the URLs in outgoing mail. Both
 * serve this same page; what to do with the token is decided here, once the
 * session is known.
 */
async function handleEmailLink() {
  const join = window.location.pathname.match(/^\/join\/(.+)$/);
  const reset = window.location.pathname.match(/^\/reset\/(.+)$/);
  if (join) return acceptInvitation(join[1]);
  if (reset) return openResetDialog(reset[1]);
}

function clearLinkFromUrl() {
  window.history.replaceState({}, '', '/');
}

async function acceptInvitation(token) {
  if (!signedIn()) {
    // Nothing to accept an invitation *as* yet. Keep the token and pick it
    // up again once they have signed in.
    state.pendingInvite = token;
    toast('info', t('join.signIn'));
    openAuth('signup');
    return;
  }
  try {
    const department = await api.acceptInvite(token);
    toast('ok', t('join.accepted', { department: department.name }));
    state.pendingInvite = null;
    clearLinkFromUrl();
    await bootSession();
    renderAccount();
    showTab('team');
  } catch (err) {
    toast('err', t('join.failed'), err.message);
    clearLinkFromUrl();
  }
}

function openResetDialog(token) {
  const field = el('input', {
    type: 'password', class: 'inp', autocomplete: 'new-password',
    placeholder: t('reset.password'), minlength: '10',
  });
  const dialog = el('dialog', { class: 'modal' },
    el('form', {
      method: 'dialog', class: 'modal-inner',
      onsubmit: async (event) => {
        event.preventDefault();
        try {
          await api.resetPassword(token, field.value);
          toast('ok', t('reset.done'));
          dialog.close();
          clearLinkFromUrl();
          openAuth('login');
        } catch (err) {
          toast('err', t('reset.failed'), err.message);
        }
      },
    },
      el('h2', {}, t('reset.title')),
      el('label', { class: 'field' }, el('span', {}, t('reset.password')), field),
      el('div', { class: 'modal-actions' },
        el('button', { class: 'btn btn-primary', type: 'submit' }, t('reset.submit')))));

  document.body.append(dialog);
  dialog.showModal();
  field.focus();
}

function wireAuth() {
  $('#signInBtn').addEventListener('click', () => openAuth('login'));
  $('#authSwitch').addEventListener('click', () =>
    openAuth(state.authMode === 'signup' ? 'login' : 'signup'));
  $('#authCancel').addEventListener('click', () => $('#authModal').close());
  $('#authForm').addEventListener('submit', submitAuth);
  $('#accountBtn').addEventListener('click', signOut);
  $('#departmentPicker').addEventListener('change', async (e) => {
    state.department = state.departments.find((d) => d.id === e.target.value) || null;
    state.scheduleId = null;
    state.result = null;
    await loadRoster();
    await loadServerSchedules();
    await loadTeam();
    showTab(state.activeTab);
  });
}

wireAuth();
bootSession();

/** Server-side verdict on a hand-edited rota, shown where the edits happen. */
function validationBanner() {
  const v = state.validation;
  if (!signedIn() || !state.scheduleId || !v) return null;
  if (v.ok && !v.warnings.length) {
    return el('div', { class: 'pf-item ok', style: 'margin-bottom:16px' },
      icon('i-check'),
      el('span', {}, el('b', {}, t('valid.ok')), el('em', {}, t('valid.okSub'))));
  }
  const items = [...v.errors.map((t) => ['bad', t]), ...v.warnings.slice(0, 6).map((t) => ['warn', t])];
  return el('div', { style: 'display:flex;flex-direction:column;gap:7px;margin-bottom:16px' },
    ...items.map(([tone, text]) => el('div', { class: `pf-item ${tone}` },
      icon('i-alert'), el('span', {}, text))),
    v.errors.length
      ? null
      : el('div', { class: 'hint' }, t('valid.warnNote')));
}

/* ─────────────────────── saved schedules & sharing ─────────────────────── */

function savedScheduleRow(row) {
  const m = row.metrics || {};
  const current = row.id === state.scheduleId;

  const open = el('button', { class: 'btn btn-ghost' }, t('history.open'));
  open.addEventListener('click', async () => {
    const full = await api.schedule(state.department.id, row.id);
    adoptSchedule(full);
    await refreshValidation();
    $('#emptyState').hidden = true;
    renderResult();
    showTab('calendar');
  });

  const remove = el('button', { class: 'btn btn-ghost', title: t('history.delete') }, icon('i-x'));
  remove.addEventListener('click', async () => {
    await api.deleteSchedule(state.department.id, row.id);
    if (current) {
      state.scheduleId = null;
      state.result = null;
    }
    await loadServerSchedules();
    showTab('history');
  });

  const when = el('div', { class: 'run-when' },
    new Date(row.updated_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short' }));
  when.append(el('div', {}, row.status));

  const main = el('div', { class: 'run-main' },
    el('b', {}, row.name),
    el('span', {}, `${prettyDate(row.start_date)} → ${prettyDate(row.end_date)}`));

  const metrics = el('div', { class: 'run-metrics' },
    el('div', {}, el('span', {}, 'Balance'), el('b', {}, `${fmt(m.balance, 0)}%`)),
    el('div', {}, el('span', {}, 'Coverage'), el('b', {}, `${fmt(m.coverage, 0)}%`)));

  const actions = el('div', { class: 'run-actions' });
  if (!current) actions.append(open);
  actions.append(remove);

  return el('div', { class: `run-row${current ? ' is-current' : ''}` },
    when, main, metrics, actions);
}


function renderSavedSchedules(pane) {
  const rows = state.serverSchedules;
  const header = el('div', { class: 'result-head' },
    el('div', { class: 'result-title' },
      el('h2', {}, t('history.saved')),
      el('span', { class: 'sub' },
        t('history.savedSub', { count: plural(rows.length, 'rota'),
          department: state.department?.name || '' }))));

  if (!rows.length) {
    pane.replaceChildren(header, el('div', { class: 'empty-note' },
      t('history.emptyServer')));
    return;
  }

  pane.replaceChildren(header, el('div', { class: 'runs' }, ...rows.map(savedScheduleRow)));
  renderAuditTrail(pane);
}

/**
 * Who changed what.
 *
 * The events have been recorded since editing existed — they train the
 * preference model — but nothing ever showed them. Appended rather than
 * inlined so the list can arrive after the schedules are already on screen.
 */
async function renderAuditTrail(pane) {
  if (!signedIn() || !state.department) return;
  const entries = await api
    .history(state.department.id, state.scheduleId)
    .catch(() => []);

  const block = el('section', { class: 'team-block' },
    sectionHead(t('audit.title'), t('audit.sub')),
    entries.length
      ? el('div', { class: 'runs' }, ...entries.slice(0, 40).map((entry) => {
        const when = new Date(entry.created_at);
        return el('div', { class: 'run-row' },
          el('div', { class: 'run-when' },
            when.toLocaleDateString(undefined, { day: 'numeric', month: 'short' }),
            el('div', {}, when.toLocaleTimeString(undefined, {
              hour: '2-digit', minute: '2-digit',
            }))),
          el('div', { class: 'run-main' },
            el('b', {}, entry.summary),
            el('span', {}, entry.schedule_name || '')));
      }))
      : el('div', { class: 'empty-note' }, t('audit.none')));

  // The pane may have been re-rendered while this was in flight.
  if (pane.isConnected) pane.append(block);
}


async function createShareLink() {
  try {
    const share = await api.createShare(state.department.id, state.scheduleId, {
      label: 'Ward noticeboard',
    });
    try {
      await navigator.clipboard.writeText(share.url);
      toast('ok', t('share.copied'), t('share.copiedSub'));
    } catch {
      toast('ok', t('share.copied'), share.url);
    }
    await renderSharePanel(share.url);
  } catch (err) {
    toast('err', t('toast.failed'), err.message);
  }
}

async function renderSharePanel(justCreated = null) {
  const host = $('#sharePanel');
  if (!host || !signedIn() || !state.scheduleId) return;
  const links = await api.shares(state.department.id, state.scheduleId).catch(() => []);

  host.replaceChildren(
    el('h3', {}, icon('i-spark'), t('share.title')),
    el('div', { class: 'panel-sub' }, t('share.sub')),
    justCreated
      ? el('div', { class: 'share-new' },
        el('input', { type: 'text', readonly: true, value: justCreated, onclick: (e) => e.target.select() }),
        el('button', {
          class: 'btn btn-ghost',
          onclick: () => navigator.clipboard.writeText(justCreated)
            .then(() => toast('ok', t('toast.copied'))).catch(() => {}),
        }, icon('i-copy'), t('share.copy')))
      : null,
    links.length
      ? el('div', { class: 'runs' }, ...links.map((link) => el('div', { class: 'run-row' },
        el('div', { class: 'run-main' },
          el('b', {}, link.label || 'Share link'),
          el('span', {}, link.revoked_at
            ? 'revoked'
            : `${link.views} view${link.views === 1 ? '' : 's'}${link.expires_at ? ` · expires ${prettyDate(link.expires_at.slice(0, 10))}` : ''}`)),
        link.revoked_at ? null : el('button', {
          class: 'btn btn-ghost',
          onclick: async () => {
            await api.revokeShare(state.department.id, state.scheduleId, link.id);
            await renderSharePanel();
            toast('info', t('share.revoked'));
          },
        }, t('share.revoke')))))
      : el('div', { class: 'empty-note' }, t('share.none')));
}

/* ─────────────────────────── language ─────────────────────────── */

function renderLanguagePicker() {
  const picker = $('#langPicker');
  picker.replaceChildren(...Object.entries(LOCALES).map(([code, meta]) =>
    el('option', { value: code, selected: code === state.locale }, meta.label)));
}

/** Switching language re-renders everything, including the result panes. */
function applyLocale(code) {
  state.locale = setLocale(code);
  translateDom();
  renderLanguagePicker();
  renderAccount();
  onConfigChange();
  if (state.result) renderResult();
  else showTab(state.activeTab);
  saveState();
  // The interface remembers its language per device; email has no device to
  // ask, so the server is told too.
  if (signedIn()) api.setLocale(state.locale).catch(() => {});
}

function wireLanguage() {
  state.locale = setLocale(detectLocale(state.locale));
  translateDom();
  renderLanguagePicker();
  $('#langPicker').addEventListener('change', (e) => applyLocale(e.target.value));
}

wireLanguage();

/* ─────────────────────────── team ───────────────────────────
 *
 * The rest of the studio is about a rota. This pane is about the people in
 * it: who has an account, who is waiting on a decision, and — when the
 * person signed in is themselves on the roster — their own nights.
 */

const team = { inbox: null, doctors: [], members: [], me: null, feedUrl: null };

async function loadTeam() {
  if (!signedIn() || !state.department) {
    team.inbox = null;
    team.doctors = [];
    team.members = [];
    team.me = null;
    return;
  }
  const coordinator = ['coordinator', 'owner'].includes(state.department.role);
  const [doctors, members, inbox, me] = await Promise.all([
    api.doctors(state.department.id).catch(() => []),
    api.members(state.department.id).catch(() => []),
    coordinator ? api.inbox(state.department.id).catch(() => null) : Promise.resolve(null),
    api.me().catch(() => null),
  ]);
  team.doctors = doctors;
  team.members = members;
  team.inbox = inbox;
  team.me = me;
  renderInboxBadge();
}

function pendingCount() {
  if (!team.inbox) return 0;
  return (team.inbox.time_off?.length || 0) + (team.inbox.swaps?.length || 0);
}

function renderInboxBadge() {
  const badge = $('#inboxBadge');
  if (!badge) return;
  const count = pendingCount();
  badge.textContent = String(count);
  badge.hidden = count === 0;
}

function sectionHead(title, sub) {
  return el('div', { class: 'result-head' },
    el('div', { class: 'result-title' },
      el('h2', {}, title),
      sub ? el('span', { class: 'sub' }, sub) : null));
}

/** Approve or decline, then refresh — a decision changes the roster. */
async function decide(kind, id, approve) {
  try {
    if (kind === 'leave') {
      await api.decideTimeOff(state.department.id, id, { approve });
      toast(approve ? 'ok' : 'info',
        approve ? t('inbox.approved') : t('inbox.declined'),
        approve ? t('inbox.approvedLeave') : '');
    } else {
      await api.decideSwap(state.department.id, id, { approve });
      toast(approve ? 'ok' : 'info',
        approve ? t('inbox.approved') : t('inbox.declined'),
        approve ? t('inbox.approvedSwap') : '');
    }
    await loadTeam();
    if (approve) {
      await loadRoster();
      if (state.scheduleId) await refreshSchedule();
    }
    renderTeamPane();
  } catch (err) {
    toast('err', t('toast.actionFailed'), err.message);
  }
}

function inboxSection() {
  if (!team.inbox) return null;
  const items = [];

  for (const row of team.inbox.time_off || []) {
    items.push(el('div', { class: 'run-row' },
      el('div', { class: 'run-when' }, t('inbox.leave'),
        el('div', {}, prettyDate(row.start_date))),
      el('div', { class: 'run-main' },
        el('b', {}, t('inbox.asks', {
          doctor: row.doctor_name, nights: plural(row.nights, 'night'),
        })),
        el('span', {}, [
          `${prettyDate(row.start_date)} → ${prettyDate(row.end_date)}`,
          row.reason,
        ].filter(Boolean).join(' · '))),
      el('div', { class: 'run-actions' },
        el('button', {
          class: 'btn btn-primary',
          onclick: () => decide('leave', row.id, true),
        }, t('inbox.approve')),
        el('button', {
          class: 'btn btn-ghost',
          onclick: () => decide('leave', row.id, false),
        }, t('inbox.decline')))));
  }

  for (const row of team.inbox.swaps || []) {
    items.push(el('div', { class: 'run-row' },
      el('div', { class: 'run-when' }, t('inbox.swap'),
        el('div', {}, prettyDate(row.date))),
      el('div', { class: 'run-main' },
        el('b', {}, t('inbox.swapAsks', {
          from: row.from_doctor_name, to: row.to_doctor_name, date: prettyDate(row.date),
        })),
        el('span', {}, [row.schedule_name, row.message].filter(Boolean).join(' · '))),
      el('div', { class: 'run-actions' },
        el('button', {
          class: 'btn btn-primary',
          onclick: () => decide('swap', row.id, true),
        }, t('inbox.approve')),
        el('button', {
          class: 'btn btn-ghost',
          onclick: () => decide('swap', row.id, false),
        }, t('inbox.decline')))));
  }

  return el('section', { class: 'team-block' },
    sectionHead(t('inbox.title'), pendingCount() ? plural(pendingCount(), 'request') : ''),
    items.length
      ? el('div', { class: 'runs' }, ...items)
      : el('div', { class: 'empty-note' }, t('inbox.none')));
}

async function importRoster(file) {
  try {
    const result = await api.importRoster(state.department.id, file);
    toast('ok', t('roster.imported', { created: result.created, updated: result.updated }),
      result.failed ? t('roster.importFailed', { count: result.failed }) : '');
    await loadRoster();
    await loadTeam();
    renderTeamPane();
    renderRoster();
  } catch (err) {
    toast('err', t('toast.actionFailed'), err.message);
  }
}

async function toggleFeed(doctor) {
  try {
    if (doctor.has_feed) {
      await api.revokeFeed(state.department.id, doctor.id);
      team.feedUrl = null;
      toast('info', t('feed.revoked'));
    } else {
      const feed = await api.createFeed(state.department.id, doctor.id);
      team.feedUrl = { id: doctor.id, url: feed.url };
      toast('ok', t('feed.created'), t('feed.draftNote'));
    }
    await loadTeam();
    renderTeamPane();
  } catch (err) {
    toast('err', t('toast.actionFailed'), err.message);
  }
}

function doctorRow(doctor) {
  const linkedName = doctor.user_name;
  const unclaimed = team.members.filter(
    (m) => !team.doctors.some((d) => d.user_id === m.id && d.id !== doctor.id));

  const picker = el('select', {},
    el('option', { value: '' }, t('roster.pickMember')),
    ...unclaimed.map((m) => el('option', {
      value: m.id, selected: m.id === doctor.user_id,
    }, `${m.name} · ${m.email}`)));
  picker.addEventListener('change', async (e) => {
    try {
      if (e.target.value) await api.linkDoctor(state.department.id, doctor.id, e.target.value);
      else await api.unlinkDoctor(state.department.id, doctor.id);
      await loadTeam();
      renderTeamPane();
    } catch (err) {
      toast('err', t('toast.actionFailed'), err.message);
    }
  });

  const showing = team.feedUrl?.id === doctor.id ? team.feedUrl.url : null;

  return el('div', { class: 'run-row' },
    el('div', { class: 'avatar', style: avatarStyle() }, initials(doctor.name)),
    el('div', { class: 'run-main' },
      el('b', {}, doctor.name),
      el('span', {}, [
        doctor.grade,
        linkedName ? t('roster.linked', { name: linkedName }) : t('roster.unlinked'),
        doctor.has_feed ? t('feed.live') : null,
      ].filter(Boolean).join(' · ')),
      showing
        ? el('div', { class: 'share-new' },
          el('input', {
            type: 'text', readonly: true, value: showing,
            onclick: (e) => e.target.select(),
          }),
          el('button', {
            class: 'btn btn-ghost',
            onclick: () => navigator.clipboard.writeText(showing)
              .then(() => toast('ok', t('toast.copied'))).catch(() => {}),
          }, icon('i-copy'), t('share.copy')))
        : null),
    el('div', { class: 'run-actions' },
      picker,
      el('button', {
        class: 'btn btn-ghost',
        onclick: () => toggleFeed(doctor),
      }, doctor.has_feed ? t('feed.revoke') : t('feed.create'))));
}

function rosterSection() {
  const coordinator = ['coordinator', 'owner'].includes(state.department?.role);
  if (!coordinator) return null;

  const picker = el('input', {
    type: 'file', accept: '.csv,text/csv', style: 'display:none',
  });
  picker.addEventListener('change', (e) => {
    const file = e.target.files?.[0];
    if (file) importRoster(file);
    e.target.value = '';
  });

  return el('section', { class: 'team-block' },
    el('div', { class: 'result-head' },
      el('div', { class: 'result-title' },
        el('h2', {}, t('team.roster')),
        el('span', { class: 'sub' }, t('team.rosterSub'))),
      el('div', { class: 'result-actions' },
        picker,
        el('button', {
          class: 'btn btn-ghost', onclick: () => picker.click(), title: t('roster.importHint'),
        }, icon('i-plus'), t('roster.import')))),
    team.doctors.length
      ? el('div', { class: 'runs' }, ...team.doctors.map(doctorRow))
      : el('div', { class: 'empty-note' }, t('roster.empty')));
}

/* ── the signed-in doctor's own view ── */

async function askLeave(doctorId, from, to, reason) {
  try {
    await api.requestTimeOff({
      doctor_id: doctorId, start_date: from, end_date: to, reason: reason || null,
    });
    toast('ok', t('mine.requested'));
    await loadTeam();
    renderTeamPane();
  } catch (err) {
    toast('err', t('toast.actionFailed'), err.message);
  }
}

function leaveForm(doctorId) {
  const today = new Date().toISOString().slice(0, 10);
  const from = el('input', { type: 'date', min: today });
  const to = el('input', { type: 'date', min: today });
  const reason = el('input', { type: 'text', placeholder: t('mine.reason') });

  return el('div', { class: 'leave-form' },
    el('label', { class: 'field' }, el('span', {}, t('mine.leaveFrom')), from),
    el('label', { class: 'field' }, el('span', {}, t('mine.leaveTo')), to),
    el('label', { class: 'field grow' }, el('span', {}, t('mine.reason')), reason),
    el('button', {
      class: 'btn btn-primary',
      onclick: () => {
        if (!from.value || !to.value) return;
        askLeave(doctorId, from.value, to.value || from.value, reason.value.trim());
      },
    }, t('mine.send')));
}

async function askSwap(shift) {
  const others = team.doctors.filter(
    (d) => d.id !== shift.doctor_id && !shift.alongside.includes(d.name));
  if (!others.length) return;
  const choice = window.prompt(
    `${t('mine.askSwap')}\n${others.map((d, i) => `${i + 1}. ${d.name}`).join('\n')}`, '1');
  const picked = others[Number(choice) - 1];
  if (!picked) return;
  try {
    await api.proposeSwap({
      schedule_id: shift.schedule_id, date: shift.date,
      from_doctor_id: shift.doctor_id, to_doctor_id: picked.id,
    });
    toast('ok', t('mine.requested'), picked.name);
    await loadTeam();
    renderTeamPane();
  } catch (err) {
    toast('err', t('toast.actionFailed'), err.message);
  }
}

function mineSection() {
  const me = team.me;
  if (!me || !me.doctors.length) return null;
  const shifts = me.shifts || [];

  const rows = shifts.slice(0, 30).map((shift) => el('div', { class: 'run-row' },
    el('div', { class: 'run-when' }, prettyDate(shift.date),
      el('div', {}, shift.status)),
    el('div', { class: 'run-main' },
      el('b', {}, shift.schedule_name),
      el('span', {}, shift.alongside.length
        ? t('mine.alongside', { names: shift.alongside.join(', ') })
        : shift.department_name)),
    el('div', { class: 'run-actions' },
      el('button', {
        class: 'btn btn-ghost', onclick: () => askSwap(shift),
      }, t('mine.askSwap')))));

  const mine = me.doctors[0];
  const feedButton = el('button', { class: 'btn btn-ghost' }, icon('i-calendar'), t('feed.create'));
  feedButton.addEventListener('click', async () => {
    try {
      const feed = await api.myFeed(mine.id);
      team.feedUrl = { id: mine.id, url: feed.url };
      toast('ok', t('feed.created'), t('feed.draftNote'));
      renderTeamPane();
    } catch (err) {
      toast('err', t('toast.actionFailed'), err.message);
    }
  });

  const showing = team.feedUrl?.id === mine.id ? team.feedUrl.url : null;

  return el('section', { class: 'team-block' },
    el('div', { class: 'result-head' },
      el('div', { class: 'result-title' },
        el('h2', {}, t('mine.title')),
        el('span', { class: 'sub' }, shifts.length ? plural(shifts.length, 'night') : '')),
      el('div', { class: 'result-actions' }, feedButton)),
    showing
      ? el('div', { class: 'share-new' },
        el('input', {
          type: 'text', readonly: true, value: showing, onclick: (e) => e.target.select(),
        }),
        el('button', {
          class: 'btn btn-ghost',
          onclick: () => navigator.clipboard.writeText(showing)
            .then(() => toast('ok', t('toast.copied'))).catch(() => {}),
        }, icon('i-copy'), t('share.copy')))
      : null,
    rows.length
      ? el('div', { class: 'runs' }, ...rows)
      : el('div', { class: 'empty-note' }, t('mine.none')),
    el('h3', { style: 'margin:18px 0 8px' }, t('mine.askLeave')),
    leaveForm(mine.id));
}

function renderTeamPane() {
  const pane = $('#pane-team');
  if (!pane) return;
  if (!signedIn() || !state.department) {
    pane.replaceChildren(
      sectionHead(t('team.title'), t('team.sub')),
      el('div', { class: 'empty-note' }, t('team.signedOut')));
    return;
  }
  pane.replaceChildren(
    ...[inboxSection(), mineSection(), rosterSection()].filter(Boolean));
}
