# Воспроизведение результатов

[English version](REPRODUCE.en.md)

Каталог опубликован в готовом виде — для работы с ним ничего запускать не нужно. Инструкция ниже нужна тем, кто хочет пересобрать данные или проверить промежуточные шаги.

---

## 1. Работа с готовым каталогом

Ничего устанавливать не требуется.

| Файл | Формат | Чем открыть |
|---|---|---|
| [`data/catalog_ch4_west_siberia.csv`](data/catalog_ch4_west_siberia.csv) | таблица | любой табличный редактор, pandas, R |
| [`data/catalog_ch4_west_siberia.geojson`](data/catalog_ch4_west_siberia.geojson) | контуры событий, CRS84 | QGIS, ArcGIS, geopandas, leaflet |
| [`data/zapsib_boundary.geojson`](data/zapsib_boundary.geojson) | граница области интереса | то же |

Описание всех 59 полей — в [словаре](data/DATA_DICTIONARY.ru.md).

```python
import pandas as pd
df = pd.read_csv("data/catalog_ch4_west_siberia.csv")
valid = df[df.artifact_likely == 0]          # 88 достоверных событий
valid = valid[valid.max_z > 0]               # исключить запись с несчитанной z-оценкой
print(valid.max_z.describe())
```

**Интерактивная карта** (регистрация не нужна): https://nodal-thunder-481307-u1.projects.earthengine.app/view/plumech4westsib

---

## 2. Что нужно для пересборки

| Требование | Примечание |
|---|---|
| Учётная запись Google Earth Engine | бесплатная для исследовательских целей, требует одобрения заявки |
| Проект Google Cloud с подключённым Earth Engine API | указывается при инициализации |
| Python 3.10 или новее | |
| Пакет `earthengine-api` | `pip install earthengine-api` |

Аутентификация выполняется один раз:

```bash
earthengine authenticate
```

⚠️ Полная пересборка семилетнего каталога требует **порядка 400 EECU-часов**. Это не мгновенная операция и расходует вычислительную квоту проекта. Приведённые ниже шаги 3 и 4 несопоставимо дешевле — они читают уже готовые данные.

---

## 3. Повторная выгрузка каталога из Earth Engine

Годовые коллекции опубликованы с правом чтения для всех. Пути:

```
projects/nodal-thunder-481307-u1/assets/RuPlumeScan/catalog/CH4/events_2019
                                                            … events_2025
projects/nodal-thunder-481307-u1/assets/RuPlumeScan/zapsib_boundary
projects/nodal-thunder-481307-u1/assets/RuPlumeScan/refs/schuit2023_v1
projects/nodal-thunder-481307-u1/assets/RuPlumeScan/refs/imeo_mars_v1
```

Пересоздать публикуемые CSV, GeoJSON и снимок схемы:

```bash
python code/py/supplement/export_catalog.py --out data
```

Скрипт только читает: исходные коллекции не изменяются. Порядок записей детерминирован (по времени пролёта, затем по долготе), поэтому повторный запуск даёт **побайтово тот же результат** — при условии, что исходные коллекции не менялись.

Пересобрать словарь полей из фактических данных:

```bash
python code/py/supplement/build_data_dictionary.py --data data --out data
```

Скрипт завершится с ошибкой, если словарь и данные разойдутся хотя бы одним полем.

---

## 4. Построение рисунков

```bash
pip install matplotlib numpy
python code/py/figures/bake_figures.py
```

Рисунки рендерятся на стороне Earth Engine и сохраняются в разрешении 300 dpi. Подписи — в [`figures/CAPTIONS.ru.md`](figures/CAPTIONS.ru.md).

---

## 5. Данные UNEP IMEO MARS

Исходные данные MARS распространяются под лицензией **CC BY-NC-SA 4.0**, запрещающей коммерческое использование и требующей тех же условий для производных. Поэтому они **не включены** в этот репозиторий.

Чтобы получить их самостоятельно:

1. Откройте https://methanedata.unep.org
2. Раздел выгрузки данных → архив CSV
3. Сверьте контрольные суммы SHA-256 с [`data/MARS_MANIFEST.json`](data/MARS_MANIFEST.json)

Версия, использованная в работе, получена **15.05.2026**. Каталог событий содержит только результат сверки — двоичный признак `matched_mars_150km`, что не является распространением исходных данных.

---

## 6. Приложение Earth Engine

Исходный код интерактивной карты — в [`code/js/app/`](code/js/app/). Приложение работает только на чтение: каталог не изменяется.

Чтобы запустить свою копию, скопируйте модули в собственный репозиторий Earth Engine и замените в путях `require()` идентификатор репозитория на свой. Точка входа — `main.js`.

---

## 7. Проверка целостности

Полная проверка одной командой — 20 утверждений: заявленные числа, единообразие правила отнесения к артефактам по всем годам, соблюдение порогов детекции и очерченная область влияния известного дефекта.

```bash
python code/py/supplement/verify_catalog.py --data data
```

Доступ к Earth Engine не требуется — проверяется опубликованный CSV. Код возврата 0 означает, что расхождений нет.

Минимальная проверка вручную:

```python
import pandas as pd
df = pd.read_csv("data/catalog_ch4_west_siberia.csv")

assert len(df) == 122
assert df.event_id.nunique() == 122
assert (df.artifact_likely == 0).sum() == 88
assert (df.artifact_likely == 1).sum() == 34
assert df.matched_schuit_150km.sum() == 7
assert df.matched_mars_150km.sum() == 53
assert round(df.max_z.max(), 2) == 85.47
assert df.nearest_source_type.str.startswith("viirs_flare").sum() == 96
print("Все проверки пройдены")
```
