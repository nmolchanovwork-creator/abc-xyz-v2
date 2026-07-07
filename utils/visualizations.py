"""Модуль визуализации: графики Plotly для страницы «Дашборды»."""

import plotly.express as px
import pandas as pd

ABC_COLORS = {"A": "#2ecc71", "B": "#f1c40f", "C": "#e74c3c"}
XYZ_COLORS = {"X": "#3498db", "Y": "#9b59b6", "Z": "#e67e22"}


def plot_margin_pie(summary_df: pd.DataFrame):
    """Круговая диаграмма: распределение маржи по группам A/B/C."""
    grp = summary_df.copy()
    grp["Группа"] = grp["ABC_для_графиков"].str[0]
    data = grp.groupby("Группа", as_index=False)["Маржа"].sum()
    fig = px.pie(
        data, names="Группа", values="Маржа",
        title="Распределение маржи по ABC-группам",
        color="Группа", color_discrete_map=ABC_COLORS,
    )
    return fig


def plot_abc_xyz_matrix(summary_df: pd.DataFrame):
    """Столбчатая диаграмма: количество SKU в матрице 3x3 (ABC x XYZ)."""
    grp = summary_df.copy()
    grp["ABC_группа"] = grp["ABC_для_графиков"].str[0]
    matrix = grp.groupby(["ABC_группа", "XYZ_код"], as_index=False).size()
    matrix = matrix.rename(columns={"size": "Кол-во SKU"})
    fig = px.bar(
        matrix, x="ABC_группа", y="Кол-во SKU", color="XYZ_код",
        barmode="group", title="Матрица ABC x XYZ (количество SKU)",
        color_discrete_map=XYZ_COLORS,
        category_orders={"ABC_группа": ["A", "B", "C"], "XYZ_код": ["X", "Y", "Z"]},
    )
    return fig


def plot_sales_trend(df: pd.DataFrame, top_skus: list, month_order: list):
    """Линейный график: динамика продаж (шт.) топ-товаров по месяцам."""
    subset = df[df["SKU"].isin(top_skus)].copy()
    trend = subset.groupby(["SKU", "Месяц"], as_index=False)["Продажи шт."].sum()
    present_months = [m for m in month_order if m in trend["Месяц"].unique()]
    if present_months:
        trend["Месяц"] = pd.Categorical(trend["Месяц"], categories=present_months, ordered=True)
        trend = trend.sort_values("Месяц")
    fig = px.line(
        trend, x="Месяц", y="Продажи шт.", color="SKU", markers=True,
        title="Динамика продаж топ-товаров по месяцам",
    )
    return fig
