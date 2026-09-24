# Таблицы статьи в машиночитаемом виде

[English version](README.en.md)

Три таблицы статьи в формате CSV (UTF-8, разделитель — запятая, десятичная точка). Каждое число пересчитывается из файлов этого репозитория; исключение — число детекций MARS по годам, для которого нужна исходная выгрузка MARS (она не распространяется, см. ниже).

Все доверительные интервалы — 95%-е интервалы Вильсона с z = 1.96 (так же считают скрипты `code/py/analysis/step8b_synthetic_pod.py` и `step8f_clean_zone_false_alarms.py`):

```python
import math

def wilson(k, n, z=1.96):
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, c - h), min(1.0, c + h)
```

Команды ниже запускаются из корня репозитория.

---

## `table1_events_by_year.csv` — таблица 1 статьи

Распределение событий каталога по годам.

| Столбец | Смысл |
|---|---|
| `year` | год; строка `2019-2025` — итог |
| `events` | число событий |
| `reliable` | достоверные: `artifact_likely = 0` |
| `likely_artefacts` | вероятные артефакты: `artifact_likely = 1` |
| `z_gt_5` | события с `max_z > 5` |

Источник — [`../catalog_ch4_west_siberia.csv`](../catalog_ch4_west_siberia.csv). Все значения совпадают с таблицей 1 статьи. Запись CH4-WSP-017 с сентинелем `max_z = 0` ([README](../../README.ru.md), оговорка 6) входит в `events` и `reliable` 2020 года, но не в `z_gt_5`.

```python
import pandas as pd

df = pd.read_csv("data/catalog_ch4_west_siberia.csv")
t1 = df.groupby("year").agg(events=("event_id", "size"),
                            reliable=("artifact_likely", lambda s: int((s == 0).sum())),
                            likely_artefacts=("artifact_likely", "sum"),
                            z_gt_5=("max_z", lambda s: int((s > 5).sum())))
print(t1)
print(t1.sum())
```

---

## `table2_mars_precision_by_year.csv` — таблица 2 статьи

Сопоставление с каталогом UNEP IMEO MARS по годам.

| Столбец | Смысл |
|---|---|
| `year` | год; строка `2023-2025` — сводная оценка |
| `matched_events` | события каталога с `matched_mars_150km = 1` |
| `catalogue_events` | все события каталога за год |
| `precision_pct` | точность, % = `matched_events / catalogue_events` |
| `ci95_low_pct`, `ci95_high_pct` | 95%-й интервал Вильсона, % |
| `mars_detections_inside_plain` | детекции MARS за год с координатами внутри [`../zapsib_boundary.geojson`](../zapsib_boundary.geojson) |

Точность и интервалы совпадают с таблицей 2 статьи. За 2022 г. внутри равнины нет ни одной детекции MARS, поэтому точность не определена (пустые ячейки) и 2022 г. не входит в сводную строку.

Число детекций MARS — только агрегаты: исходные записи MARS распространяются по лицензии CC BY-NC-SA 4.0 и в этот репозиторий не включены ([README](../../README.ru.md), раздел «Доступность данных»). Считаются все записи выгрузки (`unep_methanedata_detected_plumes.csv`, получена 15.05.2026, SHA-256 — в [`../MARS_MANIFEST.json`](../MARS_MANIFEST.json)) без отбора по спутнику; год — по полю `tile_date`. Всего внутри равнины 163 детекции: 17 за 2023 г., 53 за 2024 г., 82 за 2025 г. и 11 за 2026 г. (вне периода каталога); за 2022 г. — 0.

```python
for years in ([2023], [2024], [2025], [2023, 2024, 2025]):
    s = df[df.year.isin(years)]
    print(years, wilson(int(s.matched_mars_150km.sum()), len(s)))

# число детекций MARS внутри равнины (нужна выгрузка MARS, см. REPRODUCE.ru.md, раздел 5)
import json
from shapely.geometry import Point, shape

plain = shape(json.load(open("data/zapsib_boundary.geojson", encoding="utf-8"))["features"][0]["geometry"])
mars = pd.read_csv("unep_methanedata_detected_plumes.csv")
inside = mars[[plain.contains(Point(x, y)) for x, y in zip(mars.lon, mars.lat)]]
print(pd.to_datetime(inside.tile_date, errors="coerce").dt.year.value_counts().sort_index())
```

---

## `table3_detection_probabilities.csv` — таблица 3 статьи

Вероятности обнаружения, пропуска и ложного срабатывания. Методика проверок — [METHODS, раздел 8](../../METHODS.ru.md).

| `row_id` | Строка таблицы 3 | k / n |
|---|---|---|
| `detection_all` | вероятность обнаружения, все синтетические инъекции 1–10 т/ч | 10 / 30 |
| `detection_coverage_ge_200` | то же при достаточном покрытии: ≥ 200 валидных пикселей L3 в диске 15 км | 10 / 17 |
| `detection_coverage_ge_200_flux_gt_6` | то же при потоке выше 6 т/ч | 8 / 8 |
| `miss_all` | вероятность пропуска | 20 / 30 |
| `false_alarm_all_trials` | частота срабатываний детектора над заповедниками, все испытания | 84 / 1064 |
| `false_alarm_excluding_degenerate` | то же без двух вырожденных колец | 82 / 1062 |

Столбцы: `k`, `n` — числитель и знаменатель; `estimate` — доля k/n; `ci95_low`, `ci95_high` — интервал Вильсона; `article_value` — значение в таблице 3 статьи; `source_file` — файл в `data/`, из которого взяты k и n.

**Частота ложных срабатываний.** В статье указано 0.077 с основанием «84 из 1064 пролётов». Однако 84/1064 = 0.0789 [0.0642; 0.0967], а 0.077 соответствует 82/1062 = 0.0772 [0.0626; 0.0948] — той же выборке без двух испытаний с вырожденным кольцом (MAD ≈ 0). У этих двух испытаний максимальная z-оценка — 165.8 и 8898.3, следующее значение — 29.4. Поэтому в таблице две строки. Обе величины относятся к альтернативной конфигурации (кольцо из чистых пикселей, без ограничения кандидатов буферами) и характеризуют стадию кандидатов, до диагностики артефактов.

Остальные строки совпадают со статьёй. Порог покрытия 200 пикселей и порог потока 6 т/ч применены при разборе результатов; в сводке файла `p_02_0e_synthetic_pod.json` их нет.

```python
pod = json.load(open("data/p_02_0e_synthetic_pod.json", encoding="utf-8"))["results"]
suff = [r for r in pod if (r.get("n_valid_px_disk") or 0) >= 200]
high = [r for r in suff if r["flux_t_h"] > 6]
print(wilson(sum(r["recovered"] for r in pod), len(pod)))        # 10 / 30
print(wilson(sum(r["recovered"] for r in suff), len(suff)))      # 10 / 17
print(wilson(sum(r["recovered"] for r in high), len(high)))      # 8 / 8
print(wilson(sum(not r["recovered"] for r in pod), len(pod)))    # 20 / 30

fa = json.load(open("data/p_02_0e_clean_zone_false_alarms.json", encoding="utf-8"))
trials = [r for c in fa["chunks"].values() for r in c["rows"]]
alarms = [r for r in trials if (r.get("n_cluster_px_in_zone") or 0) >= 1]
degenerate = [r for r in alarms if (r.get("max_z") or 0) > 100]   # два кольца с MAD ≈ 0
print(wilson(len(alarms), len(trials)))                                          # 84 / 1064
print(wilson(len(alarms) - len(degenerate), len(trials) - len(degenerate)))      # 82 / 1062
```
