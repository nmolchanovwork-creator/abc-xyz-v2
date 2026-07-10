"""Модуль визуализации: графики Plotly для страницы «Дашборды»."""

import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

ABC_COLORS = {"A": "#66bb6a", "B": "#ffca28", "C": "#ef5350"}
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


def plot_xyz_distribution(summary_df: pd.DataFrame):
    """Круговая диаграмма: сколько SKU попало в каждую XYZ-группу (стабильность спроса)."""
    data = summary_df.groupby("XYZ_код", as_index=False).size().rename(columns={"size": "Кол-во SKU"})
    fig = px.pie(
        data, names="XYZ_код", values="Кол-во SKU",
        title="Распределение SKU по стабильности спроса (XYZ)",
        color="XYZ_код", color_discrete_map=XYZ_COLORS,
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


def plot_pareto(summary_df: pd.DataFrame):
    """
    Диаграмма Парето: столбцы — выручка по SKU (отсортированы по убыванию),
    линия — накопленная доля выручки, %. Наглядно показывает концентрацию
    выручки в узкой группе SKU — ключевая идея ABC-анализа.
    """
    d = summary_df.sort_values("Выручка", ascending=False).reset_index(drop=True)
    d["Ранг"] = range(1, len(d) + 1)
    total = d["Выручка"].sum()
    d["Накопленный %"] = (d["Выручка"].cumsum() / total * 100) if total > 0 else 0

    fig = go.Figure()
    fig.add_bar(x=d["Ранг"], y=d["Выручка"], name="Выручка", marker_color="#5dade2")
    fig.add_trace(go.Scatter(
        x=d["Ранг"], y=d["Накопленный %"], name="Накопленная доля, %",
        yaxis="y2", mode="lines+markers", line=dict(color="#e74c3c"),
    ))
    fig.update_layout(
        title="Парето: концентрация выручки по SKU",
        xaxis=dict(title="Ранг SKU (по убыванию выручки)"),
        yaxis=dict(title="Выручка"),
        yaxis2=dict(title="Накопленный %", overlaying="y", side="right", range=[0, 100]),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def plot_turnover_by_group(summary_df: pd.DataFrame):
    """
    Столбчатая диаграмма: средняя оборачиваемость (Продажи шт. / Текущий остаток)
    по ABC-группам. Низкая оборачиваемость в группе A — сигнал риска дефицита
    ключевых товаров; высокая в группе C — сигнал затоваривания.
    """
    grp = summary_df.copy()
    grp["ABC_группа"] = grp["ABC_для_графиков"].str[0]
    grp["Оборачиваемость"] = grp.apply(
        lambda r: r["Продажи шт."] / r["Текущий_остаток"] if r["Текущий_остаток"] > 0 else None,
        axis=1,
    )
    data = grp.groupby("ABC_группа", as_index=False)["Оборачиваемость"].mean()
    fig = px.bar(
        data, x="ABC_группа", y="Оборачиваемость", color="ABC_группа",
        title="Средняя оборачиваемость запаса по ABC-группам (продажи / остаток)",
        color_discrete_map=ABC_COLORS,
        category_orders={"ABC_группа": ["A", "B", "C"]},
    )
    fig.update_layout(showlegend=False)
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
