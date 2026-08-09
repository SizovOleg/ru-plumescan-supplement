"""Сборка словаря полей каталога из фактической схемы + человеческих описаний.

Сливает schema_dump.json (типы, покрытие, диапазоны — снято с реальных данных)
с field_descriptions.json (пояснения RU/EN) и пишет два файла:
  - DATA_DICTIONARY.ru.md
  - DATA_DICTIONARY.en.md

Проверка полноты жёсткая: если поле есть в данных, но не описано (или наоборот),
скрипт падает. Словарь не может разойтись с данными молча.

Использование:
    python src/py/supplement/build_data_dictionary.py [--data DIR] [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

DESCRIPTIONS = Path(__file__).with_name("field_descriptions.json")

LABELS = {
    "ru": {
        "title": "Словарь полей каталога",
        "intro": (
            "Описание всех полей файлов `catalog_ch4_west_siberia.csv` и "
            "`catalog_ch4_west_siberia.geojson`. Типы, полнота заполнения и "
            "диапазоны значений в таблицах сняты непосредственно с публикуемых "
            "данных, а не записаны вручную."
        ),
        "events": "Событий в каталоге",
        "geom": "Тип геометрии",
        "fields_total": "Всего полей",
        "col_field": "Поле",
        "col_unit": "Единицы",
        "col_type": "Тип",
        "col_fill": "Заполнено",
        "col_range": "Диапазон / значения",
        "col_desc": "Описание",
        "derived_note": "производное, добавлено при экспорте",
        "dimensionless": "—",
        "of": "из",
    },
    "en": {
        "title": "Catalogue data dictionary",
        "intro": (
            "Description of every field in `catalog_ch4_west_siberia.csv` and "
            "`catalog_ch4_west_siberia.geojson`. Types, completeness and value "
            "ranges in the tables are read directly from the published data "
            "rather than written by hand."
        ),
        "events": "Events in the catalogue",
        "geom": "Geometry type",
        "fields_total": "Fields in total",
        "col_field": "Field",
        "col_unit": "Unit",
        "col_type": "Type",
        "col_fill": "Filled",
        "col_range": "Range / values",
        "col_desc": "Description",
        "derived_note": "derived, added at export time",
        "dimensionless": "—",
        "of": "of",
    },
}

TYPE_NAMES = {
    "str": {"ru": "текст", "en": "text"},
    "int": {"ru": "целое", "en": "integer"},
    "float": {"ru": "дробное", "en": "float"},
    "bool": {"ru": "логическое", "en": "boolean"},
}


def type_label(python_type: Any, lang: str) -> str:
    """Человекочитаемое имя типа; смешанные типы схлопываются в «дробное»."""
    if isinstance(python_type, list):
        # ['float', 'int'] — целые значения дробного поля, публикуем как дробное
        return TYPE_NAMES.get("float", {}).get(lang, "float")
    return TYPE_NAMES.get(python_type, {}).get(lang, str(python_type))


def fmt_num(value: Any) -> str:
    if isinstance(value, float):
        if value == int(value) and abs(value) < 1e15:
            return str(int(value))
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def range_cell(entry: Dict[str, Any], lang: str) -> str:
    if "min" in entry:
        return f"{fmt_num(entry['min'])} … {fmt_num(entry['max'])}"
    if "distinct_values" in entry:
        vals = [v if v != "" else "«»" for v in entry["distinct_values"]]
        text = ", ".join(f"`{v}`" for v in vals)
        return text if len(text) <= 300 else text[:297] + "…"
    if "distinct_count" in entry:
        n = entry["distinct_count"]
        word = "различных значений" if lang == "ru" else "distinct values"
        return f"{n} {word}"
    return ""


def escape_cell(text: str) -> str:
    """Экранировать разделитель таблицы и переносы строк."""
    return text.replace("|", "\\|").replace("\n", " ")


def build(lang: str, schema: Dict[str, Any], desc: Dict[str, Any]) -> str:
    L = LABELS[lang]
    fields = schema["fields"]
    n = schema["n_events"]
    out: List[str] = []
    out.append(f"# {L['title']}")
    out.append("")
    out.append(L["intro"])
    out.append("")
    out.append(f"- **{L['events']}:** {n}")
    out.append(f"- **{L['geom']}:** {', '.join(schema['geometry_types'])}")
    out.append(f"- **{L['fields_total']}:** {len(fields)}")
    out.append("")

    for group in desc["groups"]:
        out.append(f"## {group[lang]}")
        out.append("")
        out.append(f"| {L['col_field']} | {L['col_unit']} | {L['col_type']} | "
                   f"{L['col_fill']} | {L['col_range']} | {L['col_desc']} |")
        out.append("|---|---|---|---|---|---|")
        for name in group["fields"]:
            entry = fields[name]
            meta = desc["fields"][name]
            unit = meta.get("unit") or L["dimensionless"]
            fill = f"{entry['present']} {L['of']} {n}"
            text = meta[lang]
            if meta.get("derived"):
                text += f" _({L['derived_note']})_"
            out.append(
                f"| `{name}` | {escape_cell(unit)} | {type_label(entry['python_type'], lang)} "
                f"| {fill} | {escape_cell(range_cell(entry, lang))} | {escape_cell(text)} |"
            )
        out.append("")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="supplement/data")
    ap.add_argument("--out", default="supplement/data")
    args = ap.parse_args()

    schema = json.loads((Path(args.data) / "schema_dump.json").read_text(encoding="utf-8"))
    desc = json.loads(DESCRIPTIONS.read_text(encoding="utf-8"))

    # --- Проверка полноты: словарь и данные обязаны совпадать -------------
    in_data = set(schema["fields"])
    in_desc = set(desc["fields"])
    grouped: List[str] = []
    for g in desc["groups"]:
        grouped.extend(g["fields"])

    problems = []
    if in_data - in_desc:
        problems.append(f"поля есть в данных, но не описаны: {sorted(in_data - in_desc)}")
    if in_desc - in_data:
        problems.append(f"поля описаны, но отсутствуют в данных: {sorted(in_desc - in_data)}")
    if set(grouped) != in_desc:
        problems.append(f"поля не разложены по группам: {sorted(in_desc ^ set(grouped))}")
    if len(grouped) != len(set(grouped)):
        dupes = sorted({f for f in grouped if grouped.count(f) > 1})
        problems.append(f"поле попало в несколько групп: {dupes}")
    if problems:
        for p in problems:
            print(f"FAIL: {p}", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for lang, suffix in (("ru", "ru"), ("en", "en")):
        path = out_dir / f"DATA_DICTIONARY.{suffix}.md"
        path.write_text(build(lang, schema, desc) + "\n", encoding="utf-8")
        print(f"WROTE {path}")
    print(f"OK: {len(in_data)} fields documented, data and dictionary agree")


if __name__ == "__main__":
    main()
