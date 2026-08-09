/**
 * @fileoverview Design tokens — amber design language, island cards, compact.
 *
 * P-02.0d-ux2 redesign (architect 2026-06-21): amber accent (replaces blue),
 * rounded island cards (borderRadius confirmed working in GEE), compact padding,
 * fixed-height header + scrollable body. Single design language across all tabs.
 *
 * @module app/theme
 */

/* eslint-disable no-undef */

// ---------------------------------------------------------------------------
// Color palette — amber accent language
// ---------------------------------------------------------------------------

exports.COLOR = {
  panelBg:     '#F4F2EE',   // warm off-white panel bg (amber-leaning neutral)
  island:      '#FFFFFF',   // island card bg (contrast with panel)
  islandAlt:   '#FBF8F3',   // subtle alt island bg
  text:        '#1F2933',   // primary text
  textMuted:   '#6B6B6B',   // secondary / captions
  border:      '#E0DAD0',   // neutral island borders
  accent:      '#B45309',   // dark amber — selected tab, links, primary
  accentBright:'#EF9F27',   // bright amber — active toggle, important borders, icons
  accentSoft:  '#FBEBD2',   // pale amber — active fills / highlights
  success:     '#2E7D32',   // green — matched / pass
  danger:      '#C62828',   // red — strong / fail
  divider:     '#ECE6DC'    // in-island dividers
};

var C = exports.COLOR;

// ---------------------------------------------------------------------------
// Composed STYLE bundle
// ---------------------------------------------------------------------------

exports.STYLE = {
  // ── Header zone (fixed) ──
  appTitle: {
    fontSize: '22px', fontWeight: 'bold', color: C.text, margin: '4px 4px 0 4px'
  },
  appSubtitle: {
    fontSize: '13px', color: C.textMuted, margin: '0 4px 3px 4px', whiteSpace: 'pre-wrap'
  },
  // Стат-строка каталога (мгновенный контекст под подзаголовком)
  statStrip: {
    fontSize: '12px', fontWeight: 'bold', color: C.accent,
    margin: '0 4px 6px 4px', whiteSpace: 'pre-wrap'
  },

  // ── Headers / text ──
  cardH: {
    fontSize: '15px', fontWeight: 'bold', color: C.accent, margin: '0 0 6px 0'
  },
  sectionH: {
    fontSize: '16px', fontWeight: 'bold', color: C.text, margin: '0 0 8px 0'
  },
  fieldLabel: {
    fontSize: '13px', fontWeight: 'bold', color: C.text, margin: '6px 2px 2px 2px'
  },
  fieldValue: {
    fontSize: '14px', color: C.text, margin: '0 2px 4px 2px'
  },
  // Крупная величина (z-score в карточке события)
  statBig: {
    fontSize: '20px', fontWeight: 'bold', color: C.accent, margin: '0 2px 0 2px'
  },
  body: {
    fontSize: '14px', color: C.text, margin: '3px 2px', whiteSpace: 'pre-wrap'
  },
  bodyMuted: {
    fontSize: '13px', color: C.textMuted, margin: '3px 2px', whiteSpace: 'pre-wrap'
  },
  caption: {
    fontSize: '12px', color: C.textMuted, margin: '3px 2px', whiteSpace: 'pre-wrap'
  },
  link: {
    fontSize: '14px', color: C.accent, textDecoration: 'underline', margin: '3px 2px'
  },
  tableRow: {
    fontSize: '13px', color: C.text, margin: '0 2px'
  },

  // ── Status ──
  statusReady:   {fontSize: '12px', color: C.success, margin: '2px 6px'},
  statusLoading: {fontSize: '12px', color: C.accentBright, margin: '2px 6px'},
  statusError:   {fontSize: '12px', color: C.danger, margin: '2px 6px'},

  // ── Segmented tabs (amber) — same dark text both states; selected = pale
  //    amber fill + amber border + bold (no font-colour change, stays readable)
  tabActive: {
    backgroundColor: C.accentSoft, color: C.text, fontWeight: 'bold',
    padding: '7px 15px', margin: '0', fontSize: '14px',
    border: '1px solid ' + C.accent, borderRadius: '8px'
  },
  tabInactive: {
    backgroundColor: '#FFFFFF', color: C.text, fontWeight: 'normal',
    padding: '7px 15px', margin: '0', fontSize: '14px',
    border: '1px solid ' + C.border, borderRadius: '8px'
  },
  // Кнопка-ДЕЙСТВИЕ (Каталог, ▶) — толстая амбер-рамка отличает от табов
  actionBtn: {
    backgroundColor: '#FFFFFF', color: C.accent, fontWeight: 'bold',
    padding: '6px 13px', margin: '0', fontSize: '14px',
    border: '2px solid ' + C.accentBright, borderRadius: '8px'
  },
  actionBtnOn: {
    backgroundColor: C.accentBright, color: C.text, fontWeight: 'bold',
    padding: '6px 13px', margin: '0', fontSize: '14px',
    border: '2px solid ' + C.accent, borderRadius: '8px'
  },

  // ── Islands (rounded cards) ──
  island: {
    backgroundColor: C.island, border: '1px solid ' + C.border,
    borderRadius: '10px', padding: '9px', margin: '0 0 8px 0'
  },
  islandImportant: {
    backgroundColor: C.island, border: '1px solid ' + C.accentBright,
    borderRadius: '10px', padding: '9px', margin: '0 0 8px 0'
  },

  // ── Amber toggle button ──
  toggleOff: {
    backgroundColor: C.islandAlt, color: C.accent, fontWeight: 'bold',
    border: '1px solid ' + C.accentBright, borderRadius: '8px',
    padding: '7px 12px', margin: '0 0 8px 0', fontSize: '13px'
  },
  toggleOn: {
    backgroundColor: C.accentBright, color: C.text, fontWeight: 'bold',
    border: '1px solid ' + C.accent, borderRadius: '8px',
    padding: '7px 12px', margin: '0 0 8px 0', fontSize: '13px'
  },

  // ── Layout zones ──
  rightPanel: {
    width: '450px', backgroundColor: C.panelBg, padding: '10px'
  },
  headerZone: {
    backgroundColor: C.panelBg, padding: '0 0 4px 0', margin: '0'
  },
  scrollBody: {
    // Fixed-height scroll zone — content scrolls internally, header/tabs stay put.
    // px-based (GEE does not honor vh); generous so idle (compacted) rarely scrolls.
    maxHeight: '760px', padding: '0', margin: '4px 0 0 0'
  },

  // ── On-map legend overlay ──
  legendPanel: {
    position: 'bottom-right',
    backgroundColor: '#FFFFFFEE', border: '1px solid ' + C.accentBright,
    borderRadius: '10px', padding: '8px', margin: '0 8px 8px 0', width: '210px'
  }
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Create a rounded island panel с optional header.
 * @param {?string} title — island title (amber), null для headerless
 * @param {boolean=} important — amber border variant
 * @return {!ui.Panel}
 */
exports.card = function(title, important) {
  var p = ui.Panel({style: important ? exports.STYLE.islandImportant : exports.STYLE.island});
  if (title) p.add(ui.Label(title, exports.STYLE.cardH));
  return p;
};
exports.island = exports.card;  // alias

/** ES5-safe shallow style merge (GEE sandbox lacks Object.assign). */
exports.mergeStyle = function(base, extra) {
  var out = {}, k;
  for (k in base) if (base.hasOwnProperty(k)) out[k] = base[k];
  for (k in extra) if (extra.hasOwnProperty(k)) out[k] = extra[k];
  return out;
};

/** Thin horizontal divider inside an island. */
exports.divider = function() {
  return ui.Label('', {
    backgroundColor: C.divider, height: '1px', margin: '6px 2px', stretch: 'horizontal'
  });
};
