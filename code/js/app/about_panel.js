/**
 * @fileoverview About panel — merges help, methodology, figures, attribution.
 *
 * Replaces standalone figures_panel.js + attribution.js. Contains 4 cards:
 *
 *   1. About / How к use   — что это и как пользоваться
 *   2. Methodology         — Path E v3.1.5 + DNA v2.4 §1.4 validation
 *   3. Paper figures       — fig1-fig4 thumbnails (or placeholders) + Zenodo
 *   4. References          — Schuit + MARS citations + licenses
 *
 * @module app/about_panel
 */

/* eslint-disable no-undef */

var theme              = require('users/ntcomz18_sand/plumescan:app/theme');
var reference_registry = require('users/ntcomz18_sand/plumescan:app/reference_registry');
var gas_registry       = require('users/ntcomz18_sand/plumescan:app/gas_registry');

// ---------------------------------------------------------------------------
// Figure metadata (was figures_panel.js FIGURES)
// ---------------------------------------------------------------------------

var FIGURES = [
  {
    id: 'fig1',
    title: 'Detection method',
    caption: 'Eight processing steps from TROPOMI L3 XCH4 to the event catalogue.',
    full_url: 'https://storage.googleapis.com/ruplumescan-figures/fig1_pipeline_300dpi.svg',
    status: 'pending'
  },
  {
    id: 'fig2',
    title: 'Catalogue map (2019-2025)',
    caption: 'All 122 events against the Schuit et al. (2023) and UNEP IMEO MARS catalogues.',
    full_url: 'https://storage.googleapis.com/ruplumescan-figures/fig2_catalog_map_300dpi.svg',
    status: 'pending'
  },
  {
    id: 'fig3',
    title: 'Detections per year',
    caption: 'Yearly event counts, split into valid events and likely artefacts.',
    full_url: 'https://storage.googleapis.com/ruplumescan-figures/fig3_per_year_counts_300dpi.svg',
    status: 'pending'
  },
  {
    id: 'fig4',
    title: 'Match curves',
    caption: 'Matched fraction against matching radius, with the random expectation.',
    full_url: 'https://storage.googleapis.com/ruplumescan-figures/fig4_match_curves_300dpi.svg',
    status: 'pending'
  }
];

var ZENODO = {
  doi: '10.5281/zenodo.PLACEHOLDER',
  url: 'https://zenodo.org/record/PLACEHOLDER',
  title: 'RuPlumeScan — methane plume catalogue, West Siberian Plain (2019-2025)',
  license: 'CC BY 4.0 (catalog) + per-reference attribution',
  status: 'pending'
};

exports.FIGURES = FIGURES;
exports.ZENODO  = ZENODO;
exports.getZenodoUrl = function() { return ZENODO.status === 'deposited' ? ZENODO.url : null; };

// ---------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------

exports.build = function() {
  var panel = ui.Panel({style: {margin: '0'}});

  // 1. ABOUT / HOW TO USE
  var aboutCard = theme.card('About this tool');
  aboutCard.add(ui.Label(
    'An interactive map of methane (CH₄) super-emitter detections over the West ' +
    'Siberian Plain, built from TROPOMI satellite observations.\n\n' +
    '122 detections from 2019-2025. Each is cross-checked against two independent ' +
    'satellite reference catalogues (Schuit 2023 and the UN IMEO MARS system).',
    theme.STYLE.body
  ));
  aboutCard.add(ui.Label('How to use', theme.STYLE.cardH));
  aboutCard.add(ui.Label(
    '• Filters tab — choose gas, year, source type, and zoom region; toggle the ' +
    'plain boundary and reference catalogues; read the colour & size legend.\n' +
    '• Catalog tab — browse all detections in a table; the View button jumps to a ' +
    'detection on the map.\n' +
    '• Click any marker on the map to open its details, including the reference ' +
    'cross-check.',
    theme.STYLE.body
  ));
  panel.add(aboutCard);

  // 2. METHODOLOGY
  var methodCard = theme.card('How detections are made');
  methodCard.add(ui.Label(
    'Each satellite overpass is compared against its own local background: a ' +
    'methane reading that stands well above the surrounding area is flagged as a ' +
    'candidate. Candidates are kept only when several neighbouring pixels agree ' +
    'and the signal survives checks for snow- and surface-related artefacts. ' +
    'Detection runs March-October, when the satellite’s methane retrieval is ' +
    'reliable at these latitudes.\n\n' +
    'Study area: the West Siberian Plain (its natural physical boundary, ~2.9 ' +
    'million km²). 122 detections fall inside the boundary.',
    theme.STYLE.body
  ));
  methodCard.add(theme.divider());
  methodCard.add(ui.Label('Cross-check against reference catalogues', theme.STYLE.cardH));
  methodCard.add(ui.Label(
    'A detection is "matched" when an independent reference catalogue reports a ' +
    'detection from the same year within 150 km.\n\n' +
    '• Schuit 2023 (2021): 44% of our detections matched; 47% of theirs matched.\n' +
    '• UN IMEO MARS (2023-2025): 65% of our detections matched.\n\n' +
    'Many of our detections have no reference match — most of these are gas flares. ' +
    'The reference catalogues focus on gas-field super-emitters and do not target ' +
    'flaring, so our flare detections extend their coverage rather than disagreeing ' +
    'with them.',
    theme.STYLE.body
  ));
  panel.add(methodCard);

  // 3. FIGURES + DATA DOWNLOAD
  var figuresCard = theme.card('Figures & data download');
  figuresCard.add(ui.Label(
    'High-resolution figures and the full catalogue download become available here ' +
    'once published.',
    theme.STYLE.bodyMuted
  ));

  FIGURES.forEach(function(fig) {
    figuresCard.add(ui.Label(fig.title, theme.STYLE.cardH));
    figuresCard.add(ui.Label(fig.caption, theme.STYLE.caption));
    if (fig.status === 'baked') {
      figuresCard.add(ui.Label({
        value: '→ Open full resolution',
        targetUrl: fig.full_url,
        style: theme.STYLE.link
      }));
    } else {
      figuresCard.add(ui.Label('(coming soon)',
        theme.mergeStyle(theme.STYLE.caption, {color: '#B45309'})));
    }
    figuresCard.add(theme.divider());
  });

  figuresCard.add(ui.Label('Full catalogue download', theme.STYLE.cardH));
  if (ZENODO.status === 'deposited') {
    figuresCard.add(ui.Label({
      value: '→ Download from Zenodo (DOI ' + ZENODO.doi + ')',
      targetUrl: ZENODO.url,
      style: theme.STYLE.link
    }));
  } else {
    figuresCard.add(ui.Label(
      '(coming soon) — the full catalogue will be published on Zenodo with a ' +
      'permanent DOI, under a CC BY 4.0 licence.',
      theme.mergeStyle(theme.STYLE.caption, {color: '#B45309'})));
  }
  panel.add(figuresCard);

  // 4. REFERENCES
  var refCard = theme.card('References & licenses');
  reference_registry.list().forEach(function(refId) {
    var ref = reference_registry.get(refId);
    refCard.add(ui.Label('• ' + ref.name + ' (' + ref.temporal_coverage + ')',
                          theme.STYLE.cardH));
    refCard.add(ui.Label(ref.citation_full, theme.STYLE.bodyMuted));
    refCard.add(ui.Label({
      value: 'License: ' + ref.license,
      targetUrl: ref.license_url,
      style: theme.STYLE.link
    }));
    refCard.add(theme.divider());
  });

  refCard.add(ui.Label('This tool', theme.STYLE.cardH));
  refCard.add(ui.Label(
    'Catalogue licence: CC BY 4.0. Reference catalogue licences are retained as ' +
    'published by their authors (see links above).\n\n' +
    'Reference cross-check values record a factual observation — whether one of our ' +
    'detections lies near a same-year reference detection. They describe our data, ' +
    'not the reference data, so the reference licences do not restrict reuse of this ' +
    'catalogue.',
    theme.STYLE.bodyMuted
  ));

  refCard.add(theme.divider());
  refCard.add(ui.Label('Study area', theme.STYLE.cardH));
  refCard.add(ui.Label(
    'The study area follows the natural physical boundary of the West Siberian ' +
    'Plain, not political borders. Where the plain extends across the Russia-' +
    'Kazakhstan border, those detections are included; areas outside the plain ' +
    '(Caspian, steppe, Urals) are excluded.',
    theme.STYLE.caption
  ));
  refCard.add(ui.Label(
    'The boundary was digitised manually by the author from elevation data, ' +
    'guided by published physico-geographic atlases (Atlas of Tyumen Oblast, 1971).',
    theme.STYLE.caption
  ));
  panel.add(refCard);

  return panel;
};
