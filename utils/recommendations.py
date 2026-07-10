"""
Модуль стандартных (заранее заготовленных) рекомендаций по комбинациям ABC-кода.

Файл recommendations.csv содержит готовые правила по всем 27 комбинациям
трёхбуквенного ABC-кода (порядок букв: Выручка-Количество-Маржа — тот же,
что используется в utils/analysis.py), с рекомендациями по цене, скидке,
остатку, продвижению и выводу из ассортимента.
"""

import os
import streamlit as st
import pandas as pd

RECS_PATH = os.path.join(os.path.dirname(__file__), "recommendations.csv")

RECS_COLUMNS_RENAME = {"Категория": "ABC_код"}
RECS_DISPLAY_COLUMNS = ["по ЦЕНЕ", "по СКИДКЕ", "по ОСТАТКУ", "по ПРОДВИЖЕНИЮ", "по ВЫВОДУ"]


@st.cache_data(show_spinner=False)
def load_recommendations() -> pd.DataFrame:
    """Загружает таблицу готовых рекомендаций из recommendations.csv."""
    df = pd.read_csv(RECS_PATH)
    df = df.rename(columns=RECS_COLUMNS_RENAME)
    return df


def merge_recommendations(summary_df: pd.DataFrame) -> pd.DataFrame:
    """
    Присоединяет готовые рекомендации к сводной таблице по ABC_код.
    ABC_код считается всегда (даже при включённом интегральном весе — см. analysis.py),
    поэтому рекомендации доступны в любом режиме.
    """
    recs = load_recommendations()
    merged = summary_df.merge(recs, on="ABC_код", how="left")
    return merged
