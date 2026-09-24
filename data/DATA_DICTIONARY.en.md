# Catalogue data dictionary

Description of every field in `catalog_ch4_west_siberia.csv` and `catalog_ch4_west_siberia.geojson`. Types, completeness and value ranges in the tables are read directly from the published data rather than written by hand.

- **Events in the catalogue:** 122
- **Geometry type:** MultiPolygon, Polygon
- **Fields in total:** 60

## Identity and time

| Field | Unit | Type | Filled | Range / values | Description |
|---|---|---|---|---|---|
| `event_id` | — | text | 122 of 122 | 122 distinct values | Stable event identifier, format CH4-WSP-NNN. Assigned at export time in ascending order of overpass time; referenced by the paper text and figure captions. Not present in the GEE asset. _(derived, added at export time)_ |
| `datetime_utc` | UTC | text | 122 of 122 | 59 distinct values | Satellite overpass timestamp, ISO 8601. Derived from orbit_date_millis, added at export time. _(derived, added at export time)_ |
| `date_utc` | UTC | text | 122 of 122 | 55 distinct values | Calendar date of the overpass. Derived from orbit_date_millis, added at export time. _(derived, added at export time)_ |
| `year` | — | integer | 122 of 122 | 2019 … 2025 | Year of the overpass. Determines the annual catalogue asset the record comes from. |
| `month` | — | integer | 122 of 122 | 3 … 10 | Month of the overpass (3-10). Winter months are absent: XCH4 retrieval is unavailable at high latitudes under low sun and snow cover. |
| `orbit_date_millis` | ms | integer | 122 of 122 | 1552629588000 … 1758266419000 | Overpass time in Unix epoch milliseconds (UTC). The native time field in the asset. |
| `cluster_id` | — | integer | 122 of 122 | 1172526071899 … 2130303779080 | Internal pixel-cluster identifier assigned at detection time. Unique within the catalogue but not human-readable; use event_id for references. |

## Location and size

| Field | Unit | Type | Filled | Range / values | Description |
|---|---|---|---|---|---|
| `centroid_lon` | degrees east | float | 122 of 122 | 61.957 … 82.825 | Longitude of the cluster centroid, WGS 84. |
| `centroid_lat` | degrees north | float | 122 of 122 | 54.059 … 71.767 | Latitude of the cluster centroid, WGS 84. |
| `area_km2` | km^2 | float | 122 of 122 | 243.074 … 3264.018 | Area of the cluster outline as measured by Earth Engine (geometry().area()). The outline is built on the 7 km analysis grid in the equal-area projection EPSG:6931, so each pixel (field count) accounts for 48.5–48.9 km² (nominally 7 × 7 = 49 km²) and the minimum area at 5 pixels is 243 km². |
| `n_pixels` | — | integer | 122 of 122 | 5 … 67 | Number of 7 km analysis-grid pixels inside the final cluster outline; max_z, mean_z and the enhancements are computed over them. Detection requires at least 5 pixels connected by side or corner (8-connectivity). |
| `count` | — | integer | 122 of 122 | 5 … 67 | Pixel counter inherited from the aggregation stage. Equals n_pixels in every record but one (see the known limitations section). |
| `plume_axis_deg` | degrees | float | 122 of 122 | 0.561 … 180 | Orientation of the cluster major axis (0-180°), obtained by eigen-decomposition with a cosine-latitude correction. |

## Signal strength

| Field | Unit | Type | Filled | Range / values | Description |
|---|---|---|---|---|---|
| `max_z` | — | float | 122 of 122 | 0 … 85.469 | Maximum z-score across the cluster pixels — the primary quantitative measure of anomaly strength. Detection threshold is z >= 3.0. A value of 0 is a sentinel meaning 'statistic not computed', not a true zero (one record; see known limitations). |
| `mean_z` | — | float | 122 of 122 | 0 … 38.075 | Mean z-score across the cluster pixels. Same sentinel convention as max_z. |
| `max_delta` | ppb | float | 122 of 122 | 4.577 … 518.54 | Maximum XCH4 enhancement over the local annulus background across the cluster pixels. |
| `mean_delta` | ppb | float | 122 of 122 | 1.16 … 164.635 | Mean XCH4 enhancement over the local annulus background across the cluster pixels. |

## Quality and likely artefacts

| Field | Unit | Type | Filled | Range / values | Description |
|---|---|---|---|---|---|
| `artifact_likely` | — | integer | 122 of 122 | 0 … 1 | 1 — the event is classified as a likely retrieval artefact, 0 — as valid. Derived from a combination of surface indicators (albedo, snow, dark underlying surface). The catalogue holds 88 valid events and 34 likely artefacts. |
| `artifact_likely_albedo_positive` | — | integer | 122 of 122 | 0 … 1 | 1 — the artefact indicator was triggered specifically by a positive albedo correlation (bright surface, likely snow influence). |
| `corr_albedo` | — | float | 122 of 122 | -0.873 … 0.95 | Pearson correlation between the z-score and surface reflectance across the cluster pixels (5.5 km scale). Reflectance is MODIS MCD43A4 v6.1, band Nadir_Reflectance_Band6 (1628–1652 nm), averaged over ±8 days around the overpass. Values near +1 indicate a bright-surface retrieval artefact, near -1 a dark or wet surface. |
| `surface_confounded_dark` | — | integer | 122 of 122 | 0 … 1 | 1 — the signal is presumed confounded by a dark underlying surface (water, wet mires). |
| `cluster_overlap_snow_fraction` | fraction | float | 122 of 122 | 0 … 1 | Fraction of the cluster area under snow (0-1): the share of MODIS MOD10A1 v6.1 pixels (NDSI_Snow_Cover, averaged over ±1 day around the overpass) above 50, at 500 m scale. |
| `event_class` | — | text | 122 of 122 | `CH4_only`, `diffuse_CH4`, `wind_ambiguous` | Event category: CH4_only — isolated methane anomaly; diffuse_CH4 — diffuse enhancement without a pronounced axis; wind_ambiguous — wind conditions do not allow an unambiguous link to a source. |
| `qa_flags` | — | text | 122 of 122 | `«»`, `zone_boundary_adjustment_applied` | Quality-control flag string. An empty string means no flags; zone_boundary_adjustment_applied means a background-zone boundary correction was applied. |
| `zone_boundary_step_ppb` | ppb | integer | 33 of 122 | 16 … 16 | Magnitude of the background step at the zone boundary where the correction was applied. Populated only for records carrying the corresponding qa_flags entry. |
| `inside_reference_clean_zone` | — | integer | 122 of 122 | 0 … 1 | 1 — the centroid falls inside a zone that independent catalogues treat as free of known sources. |
| `td0044_reclassified` | — | integer | 39 of 122 | 1 … 1 | 1 — the record was reclassified during the TD-0044 revision that introduced the directional corr_albedo rule. Populated for the 39 records rebuilt in that revision (their original algorithm_version_recorded is 3.1.4). |

## Wind conditions (ERA5)

| Field | Unit | Type | Filled | Range / values | Description |
|---|---|---|---|---|---|
| `wind_state` | — | text | 122 of 122 | `aligned`, `insufficient_wind`, `misaligned` | Overall assessment of the 10 m wind: aligned — the angle between the cluster axis and the wind direction is at most 30° with a speed of at least 2 m/s; misaligned — the angle exceeds 30° at such a speed; insufficient_wind — the speed is below 2 m/s and agreement is not assessed. |
| `wind_alignment_score` | — | float | 122 of 122 | 0.001 … 0.992 | Agreement between the cluster axis and the 10 m wind direction: 1 - Δθ/90, where Δθ is the angle between them (0-90°). One means exact agreement; the 30° threshold corresponds to 0.667. It is computed even at low wind speed. |
| `wind_dir_deg` | degrees | float | 122 of 122 | 4.008 … 350.772 | Direction the 10 m wind blows from, clockwise from north. The ERA5 components are vector-averaged over ±3 h around the overpass and sampled at the cluster centroid. |
| `wind_speed` | m/s | float | 122 of 122 | 0.154 … 12.513 | Wind speed at 10 m from the components averaged over ±3 h. |
| `wind_u` | m/s | float | 122 of 122 | -7.421 … 10.345 | Zonal (west-east) wind component at 10 m, averaged over ±3 h around the overpass. |
| `wind_v` | m/s | float | 122 of 122 | -12.364 … 7.615 | Meridional (south-north) wind component at 10 m, averaged over ±3 h around the overpass. |
| `wind_u_850hPa` | m/s | float | 122 of 122 | -9.921 … 17.298 | Zonal wind component at 850 hPa (same averaging). Used only for the wind_levels_inconsistent_qa flag. |
| `wind_v_850hPa` | m/s | float | 122 of 122 | -18.263 … 14.784 | Meridional wind component at 850 hPa (same averaging). |
| `wind_consistent` | — | integer | 113 of 122 | 0 … 1 | 1 — the cluster axis agrees with the 10 m wind direction (angle at most 30°), 0 — it does not. An empty value (9 records) means the wind speed was below 2 m/s and agreement was not assessed. Matches wind_state (aligned — 1, misaligned — 0); unrelated to the 850 hPa level. |
| `wind_consistency_diff_deg` | degrees | float | 122 of 122 | 1.384 … 160.038 | Angular difference between the wind directions at 10 m and 850 hPa (0-180°). |
| `wind_levels_inconsistent_qa` | — | integer | 122 of 122 | 0 … 1 | 1 — the wind directions at 10 m and 850 hPa differ by more than 45° (43 records). A quality-control flag only: it does not affect the event category. |
| `wind_level` | — | text | 122 of 122 | `10m` | Level from which the primary wind fields were taken. Throughout the catalogue this is 10 m. |
| `wind_source` | — | text | 122 of 122 | `ERA5_HOURLY_10m` | Wind data source: ERA5 hourly reanalysis, 10 m field. |

## Nearest candidate source

| Field | Unit | Type | Filled | Range / values | Description |
|---|---|---|---|---|---|
| `nearest_source_type` | — | text | 122 of 122 | `gas_field`, `tpp_gres`, `viirs_flare_high`, `viirs_flare_low` | Category of the source assigned to the event: within 50 km of the centroid the registry object of the highest-priority category is chosen, the nearest one among equal priorities (METHODS section 4.2), so an object of another category may lie closer. gas_field — oil and gas field (oil and gas fields are not separated); viirs_flare_high and viirs_flare_low — flares from VIIRS bright night-time sources at high (radiance at least 100 nW/(cm²·sr)) and low confidence; tpp_gres — thermal power plant. |
| `nearest_source_distance_km` | km | float | 122 of 122 | 1.116 … 49.243 | Great-circle distance from the event centroid to the assigned source (see nearest_source_type). The search radius is 50 km, so all catalogue values are within 50 km. |
| `nearest_source_id` | — | text | 122 of 122 | 81 distinct values | Identifier of the assigned source in the project industrial-object registry (the registry is not part of this package, see METHODS section 4.2). One source may correspond to several events. |

## Cross-check against independent catalogues

| Field | Unit | Type | Filled | Range / values | Description |
|---|---|---|---|---|---|
| `matched_schuit_150km` | — | integer | 122 of 122 | 0 … 1 | 1 — the Schuit et al. (2023) catalogue reports a same-year detection within 150 km. Matched for 7 of 122 events. |
| `matched_mars_150km` | — | integer | 122 of 122 | 0 … 1 | 1 — the UNEP IMEO MARS catalogue reports a same-year detection within 150 km. Matched for 53 of 122 events. |
| `stage_3_match_radius_km` | km | integer | 122 of 122 | 150 … 150 | Matching radius used against the independent catalogues. Throughout the catalogue this is 150 km. |

## Record provenance

| Field | Unit | Type | Filled | Range / values | Description |
|---|---|---|---|---|---|
| `algorithm_version` | — | text | 122 of 122 | `3.1.4` | Version of the detection logic the event was produced by. Uniform across all 122 records: the directional form of the corr_albedo rule introduced in version 3.1.4 (TD-0044). The uniform label is stamped at export time after checking that every event carries the markers of that revision (fields artifact_likely_albedo_positive and surface_confounded_dark). The original build label of the export batch is preserved in algorithm_version_recorded. |
| `algorithm_version_recorded` | — | text | 122 of 122 | `2.3.2`, `3.1.4` | Version label written into the asset when the export batch was built: 2.3.2 for 83 records and 3.1.4 for 39. The yearly collections were rebuilt at different times, so the labels diverged even though the artefact-classification rule was applied identically to every event. The field is kept for traceability; use algorithm_version to select by processing version. |
| `config_id` | — | text | 122 of 122 | `default_combine` | Named parameter preset for the run. Throughout the catalogue this is default_combine. |
| `params_hash` | — | text | 122 of 122 | `04d66637e0305e40e7ca473e451525062769524f147cfd2648490b698688f8bf`, `19aa2a9b479246bdd0330cb38d725e695b098160d736290942f9a5f12569a2c8`, `1d909d3a2b8d4c422affaf6f4b3a8cc878fe24201803592a5c6322488bfd25ba`, `4ace2be260ce67383dfa5792df09e077534fab0f6532f2b15f8cd397e72b8485`, `5848063735cfe708308a6d70… | SHA-256 hash of the full run parameter snapshot. An identical hash guarantees identical processing conditions. |
| `run_id` | — | text | 122 of 122 | `default_combine_2019_combined_d98a789c`, `default_combine_2020_combined_4ace2be2`, `default_combine_2021_combined_1d909d3a`, `default_combine_2022_combined_04d66637`, `default_combine_2023_combined_e28cf804`, `default_combine_2024_combined_19aa2a9b`, `default_combine_2025_combined_58480637` | Run identifier, formatted <config_id>_<year>_combined_<first 8 characters of params_hash>. |
| `rna_version` | — | text | 122 of 122 | `1.2` | Version of the implementation document (RNA) describing asset structure and naming conventions. |
| `aoi_boundary` | — | text | 122 of 122 | `zapsib` | Area-of-interest boundary the record is attributed to. Throughout the catalogue this is zapsib, the physico-geographic boundary of the West Siberian Plain: manually digitised by the author from a digital elevation model, guided by boundaries in the Atlas of Tyumen Oblast (1971) and other cartographic atlases. The layer is published as data/zapsib_boundary.geojson; see METHODS section 2 for detail. |
| `build_date` | — | text | 122 of 122 | `2026-05-13`, `2026-05-14`, `2026-05-23` | Build date of the annual catalogue asset. |
| `intermediate_asset` | — | text | 122 of 122 | `projects/nodal-thunder-481307-u1/assets/RuPlumeScan/catalog/CH4/events_2019_intermediate`, `projects/nodal-thunder-481307-u1/assets/RuPlumeScan/catalog/CH4/events_2020_intermediate`, `projects/nodal-thunder-481307-u1/assets/RuPlumeScan/catalog/CH4/events_2021_intermediate`, `projects/nodal-thund… | Path to the intermediate asset the record was assembled from. Given for traceability; access to it is not required to use the catalogue. |
| `enrichment_method` | — | text | 122 of 122 | `numpy_eigh_with_cos_lat` | Method used to compute cluster geometry: eigen-decomposition with a cosine-latitude correction. |
| `enrichment_stage` | — | text | 122 of 122 | `axis_v1` | Label of the enrichment stage at which the geometry fields were added. |
| `stage_2_run_date` | UTC | text | 122 of 122 | `2026-05-14T03:57:50.383568+00:00`, `2026-05-14T22:19:44.001182+00:00`, `2026-05-23T02:59:45.045830+00:00`, `2026-05-23T02:59:55.375818+00:00`, `2026-05-23T03:00:03.495554+00:00`, `2026-05-23T03:00:11.463093+00:00`, `2026-05-23T03:00:25.260694+00:00` | Timestamp of stage 2 (geometry and wind enrichment). |
| `stage_3_run_date` | — | text | 122 of 122 | `2026-05-23` | Date of stage 3 (cross-check against independent catalogues). |
| `stage_3b_rescope_date` | — | text | 122 of 122 | `2026-06-20` | Date the catalogue was recomputed after the area of interest was redefined from a bounding box to the physico-geographic boundary of the plain. |

