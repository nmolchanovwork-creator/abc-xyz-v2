"""
Модуль расчёта ABC и XYZ анализа.

ВАЖНОЕ УТОЧНЕНИЕ ПОРЯДКА БУКВ (не было явно зафиксировано в исходном ТЗ):
Комбинированный 3-буквенный ABC-код строится в порядке:
  1-я буква — по Выручке
  2-я буква — по Количеству (Продажи шт.)
  3-я буква — по Марже
Пример: "CAA" = C по выручке, A по количеству, A по марже.
"""

import pandas as pd
import numpy as np


def _abc_letter_by_cumulative(series: pd.Series, thr_a: float, thr_b: float) -> pd.Series:
    """
    Присваивает букву A/B/C по накопленной доле показателя (метод Парето).
    thr_a — верхняя граница накопленной доли для группы A (доля, 0..1)
    thr_b — верхняя граница накопленной доли для группы A+B (доля, 0..1)
    """
    total = series.sum()
    if total <= 0:
        return pd.Series(["C"] * len(series), index=series.index)

    sorted_idx = series.sort_values(ascending=False).index
    cum = series.loc[sorted_idx].cumsum() / total

    letters = pd.Series(index=sorted_idx, dtype=object)
    letters[cum <= thr_a] = "A"
    letters[(cum > thr_a) & (cum <= thr_b)] = "B"
    letters[cum > thr_b] = "C"
    return letters.reindex(series.index)


def compute_abc_three_letter(agg: pd.DataFrame, thr_a: float, thr_b: float) -> pd.DataFrame:
    """agg — DataFrame по SKU с суммами за период: Выручка, Продажи шт., Маржа."""
    out = pd.DataFrame(index=agg.index)
    out["ABC_Выручка"] = _abc_letter_by_cumulative(agg["Выручка"], thr_a, thr_b)
    out["ABC_Количество"] = _abc_letter_by_cumulative(agg["Продажи шт."], thr_a, thr_b)
    out["ABC_Маржа"] = _abc_letter_by_cumulative(agg["Маржа"], thr_a, thr_b)
    out["ABC_код"] = out["ABC_Выручка"] + out["ABC_Количество"] + out["ABC_Маржа"]
    return out


def compute_abc_integral(agg: pd.DataFrame, weights: dict, thr_a: float, thr_b: float) -> pd.Series:
    """
    Единый интегральный скор:
    score = w_revenue * доля_выручки + w_qty * доля_количества + w_margin * доля_маржи
    Веса (weights['revenue'], weights['qty'], weights['margin']) должны суммарно давать 1.0
    (проверяется/нормализуется на уровне UI).
    """
    def share(col):
        s = agg[col].clip(lower=0)
        total = s.sum()
        return s / total if total > 0 else s * 0

    score = (
        weights.get("revenue", 0) * share("Выручка")
        + weights.get("qty", 0) * share("Продажи шт.")
        + weights.get("margin", 0) * share("Маржа")
    )
    return _abc_letter_by_cumulative(score, thr_a, thr_b).rename("ABC_интегральный")


def compute_xyz(df: pd.DataFrame, thr_x: float, thr_y: float) -> pd.DataFrame:
    """
    Коэффициент вариации (CV = std / mean) по месячным продажам (шт.) на SKU,
    внутри уже отфильтрованного периода.
    thr_x, thr_y — границы в долях (например 0.10 и 0.25).
    Если по SKU только один месяц данных или средние продажи = 0 — присваивается Z
    (максимальная неопределённость / нестабильность).
    """
    monthly = df.groupby(["SKU", "Год", "Месяц"], as_index=False)["Продажи шт."].sum()
    stats = monthly.groupby("SKU")["Продажи шт."].agg(["mean", "std", "count"])
    stats["std"] = stats["std"].fillna(0)
    stats["CV"] = np.where(stats["mean"] > 0, stats["std"] / stats["mean"], np.nan)

    def letter(row):
        if row["count"] < 2 or pd.isna(row["CV"]):
            return "Z"
        if row["CV"] <= thr_x:
            return "X"
        elif row["CV"] <= thr_y:
            return "Y"
        return "Z"

    stats["XYZ_код"] = stats.apply(letter, axis=1)
    return stats[["CV", "XYZ_код"]]


def build_summary(
    df: pd.DataFrame,
    thr_a: float, thr_b: float,
    thr_x: float, thr_y: float,
    use_integral: bool = False,
    weights: dict = None,
) -> pd.DataFrame:
    """Собирает итоговую сводную таблицу по SKU с присвоенным ABC-XYZ статусом."""
    if df.empty:
        return pd.DataFrame()

    agg = df.groupby("SKU").agg(
        Наименование=("Наименование", "first"),
        Категория=("Категория", "first"),
        Продажи_шт=("Продажи шт.", "sum"),
        Выручка=("Выручка", "sum"),
        Маржа=("Маржа", "sum"),
        Себестоимость=("Себестоимость", "mean"),
        Цена=("Цена", "mean"),
        Текущий_остаток=("Текущий остаток", "last"),
    )
    agg = agg.rename(columns={"Продажи_шт": "Продажи шт."})

    abc_three = compute_abc_three_letter(agg, thr_a, thr_b)
    xyz = compute_xyz(df, thr_x, thr_y)

    summary = agg.join(abc_three).join(xyz)

    if use_integral and weights:
        integral = compute_abc_integral(agg, weights, thr_a, thr_b)
        summary = summary.join(integral)
        summary["Итоговый_статус"] = summary["ABC_интегральный"] + "-" + summary["XYZ_код"]
        summary["ABC_для_графиков"] = summary["ABC_интегральный"]
    else:
        summary["Итоговый_статус"] = summary["ABC_код"] + "-" + summary["XYZ_код"]
        summary["ABC_для_графиков"] = summary["ABC_код"]

    summary = summary.reset_index()
    return summary
