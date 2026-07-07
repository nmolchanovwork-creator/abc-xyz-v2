"""
Интегральный ABC-XYZ анализ товарного портфеля с ИИ-рекомендациями.

Запуск:
    streamlit run app.py

Структура проекта:
    app.py                     — главный файл, UI и навигация
    utils/data_loader.py       — загрузка файла, шаблон Excel, демо-данные
    utils/analysis.py          — математика ABC и XYZ анализа
    utils/ai_helper.py         — интеграция с OpenAI / Gemini и системный промпт
    utils/visualizations.py    — графики Plotly
    utils/export_helper.py     — экспорт сводной таблицы и истории стратегий в Excel/текст
"""

import datetime
import streamlit as st
import pandas as pd

from utils.data_loader import (
    load_from_upload, generate_demo_data, generate_template_excel,
    DataValidationError, MONTH_ORDER,
)
from utils.analysis import build_summary
from utils.ai_helper import (
    get_sku_advice, get_portfolio_strategy, AIError,
    OPENAI_MODELS, GEMINI_MODELS,
)
from utils.visualizations import plot_margin_pie, plot_abc_xyz_matrix, plot_sales_trend
from utils.export_helper import summary_to_excel_bytes, strategy_history_to_text

st.set_page_config(page_title="ABC-XYZ анализ", layout="wide", page_icon="📊")

# ---------------------------------------------------------------------------
# ИНИЦИАЛИЗАЦИЯ SESSION_STATE
# ---------------------------------------------------------------------------
if "ai_advice_cache" not in st.session_state:
    st.session_state.ai_advice_cache = {}  # {SKU: текст совета} — чтобы не дёргать API повторно
if "strategy_history" not in st.session_state:
    st.session_state.strategy_history = []  # список сгенерированных стратегий за сессию

# ---------------------------------------------------------------------------
# БОКОВАЯ ПАНЕЛЬ
# ---------------------------------------------------------------------------
st.sidebar.title("⚙️ Настройки")

# --- 1. Источник данных ---
st.sidebar.subheader("Данные")

with st.sidebar.expander("📥 Скачать шаблон Excel", expanded=False):
    st.caption("Заполните файл по этому образцу и загрузите его ниже.")
    st.download_button(
        "Скачать шаблон (.xlsx)",
        data=generate_template_excel(),
        file_name="shablon_abc_xyz.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

source = st.sidebar.radio("Источник данных", ["Загрузить файл", "Демо-данные (проверить как работает)"])

df = None
try:
    if source == "Загрузить файл":
        uploaded = st.sidebar.file_uploader("CSV или Excel файл", type=["csv", "xlsx", "xls"])
        if uploaded is not None:
            df = load_from_upload(uploaded.getvalue(), uploaded.name)
        else:
            st.sidebar.info("Загрузите файл с данными (или скачайте шаблон выше).")
    else:
        df = generate_demo_data()
        st.sidebar.caption("Используются сгенерированные демо-данные (60 SKU, 12 месяцев).")

except DataValidationError as e:
    st.sidebar.error(str(e))
except Exception as e:
    st.sidebar.error(f"Непредвиденная ошибка загрузки данных: {e}")

# Если данных нет — не показываем остальной интерфейс
if df is None or df.empty:
    st.title("📊 Интегральный ABC-XYZ анализ")
    st.info("⬅️ Загрузите файл с данными (или включите демо-режим) в боковой панели, чтобы начать анализ.")
    st.stop()

# --- 2. ИИ-модуль: выбор провайдера, ключа и модели ---
st.sidebar.subheader("ИИ-модуль")
provider = st.sidebar.radio("Провайдер ИИ", ["OpenAI", "Gemini"], horizontal=True)

if provider == "OpenAI":
    api_key = st.sidebar.text_input("OpenAI API-ключ", type="password")
    model = st.sidebar.selectbox("Модель OpenAI", OPENAI_MODELS)
else:
    api_key = st.sidebar.text_input("Gemini API-ключ", type="password")
    model = st.sidebar.selectbox("Модель Gemini", GEMINI_MODELS)

st.sidebar.caption("Ключ используется только в рамках текущей сессии и не сохраняется.")

# --- 3. Динамические фильтры ---
st.sidebar.subheader("Фильтры")
categories = sorted(df["Категория"].dropna().unique().tolist())
sale_types = sorted(df["Тип продажи"].dropna().unique().tolist())
years = sorted(df["Год"].dropna().unique().tolist())
months_present = [m for m in MONTH_ORDER if m in df["Месяц"].unique()] or sorted(df["Месяц"].unique().tolist())

f_categories = st.sidebar.multiselect("Категория", categories, default=categories)
f_sale_types = st.sidebar.multiselect("Тип продажи", sale_types, default=sale_types)
f_years = st.sidebar.multiselect("Год", years, default=years)
f_months = st.sidebar.multiselect("Месяц", months_present, default=months_present)

filtered_df = df[
    df["Категория"].isin(f_categories)
    & df["Тип продажи"].isin(f_sale_types)
    & df["Год"].isin(f_years)
    & df["Месяц"].isin(f_months)
]

if filtered_df.empty:
    st.warning("⚠️ После применения фильтров не осталось ни одной строки данных. "
               "Измените фильтры в боковой панели.")
    st.stop()

# --- 4. Настройки алгоритма ABC/XYZ ---
st.sidebar.subheader("Границы ABC (накопительно, %)")
abc_a = st.sidebar.slider("Группа A — до, %", 50, 95, 80)
abc_b = st.sidebar.slider("Группа A+B — до, %", abc_a + 1, 99, min(abc_a + 15, 99))
thr_a, thr_b = abc_a / 100, abc_b / 100

st.sidebar.subheader("Границы XYZ (коэфф. вариации, %)")
xyz_x = st.sidebar.slider("X — CV меньше, %", 1, 30, 10)
xyz_y = st.sidebar.slider("Y — CV меньше, %", xyz_x + 1, 60, max(xyz_x + 15, 25))
thr_x, thr_y = xyz_x / 100, xyz_y / 100

st.sidebar.subheader("Интегральный ABC")
use_integral = st.sidebar.checkbox("Использовать интегральный вес ABC")
weights = None
if use_integral:
    w_rev = st.sidebar.slider("Вес Выручки, %", 0, 100, 40)
    w_qty = st.sidebar.slider("Вес Количества, %", 0, 100, 20)
    w_margin = st.sidebar.slider("Вес Маржи, %", 0, 100, 40)
    total_w = w_rev + w_qty + w_margin
    if total_w != 100:
        st.sidebar.warning(f"Сумма весов = {total_w}%, должна быть 100%. "
                            f"Веса будут автоматически нормализованы.")
    if total_w == 0:
        total_w = 1  # защита от деления на 0
    weights = {"revenue": w_rev / total_w, "qty": w_qty / total_w, "margin": w_margin / total_w}

# ---------------------------------------------------------------------------
# РАСЧЁТ ABC-XYZ
# ---------------------------------------------------------------------------
summary = build_summary(filtered_df, thr_a, thr_b, thr_x, thr_y, use_integral, weights)

if summary.empty:
    st.warning("⚠️ Не удалось построить сводную таблицу — проверьте данные и фильтры.")
    st.stop()

# Добавляем колонку AI-совета из кэша (если уже запрашивался)
summary["AI Совет"] = summary["SKU"].map(st.session_state.ai_advice_cache).fillna("—")

filters_desc = (f"Категории: {f_categories}; Тип продажи: {f_sale_types}; "
                f"Год: {f_years}; Месяцы: {f_months}")

# ---------------------------------------------------------------------------
# СТРАНИЦЫ
# ---------------------------------------------------------------------------
st.title("📊 Интегральный ABC-XYZ анализ")
tab1, tab2, tab3 = st.tabs(["🗂️ Аналитика и Действия", "📈 Дашборды", "🧠 Глобальная ИИ-Стратегия"])

# --- СТРАНИЦА 1: Аналитика и Действия ---
with tab1:
    st.subheader("Сводная таблица по SKU")
    display_cols = ["SKU", "Наименование", "Категория", "Продажи шт.", "Выручка", "Маржа",
                     "Текущий_остаток", "Итоговый_статус", "AI Совет"]
    st.dataframe(summary[display_cols], use_container_width=True, height=450)

    st.download_button(
        "📥 Скачать сводную таблицу (Excel)",
        data=summary_to_excel_bytes(summary, filters_desc),
        file_name=f"abc_xyz_summary_{datetime.date.today()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    st.markdown("---")
    st.subheader("🤖 Получить AI-советы по товарам")
    col1, col2 = st.columns([1, 3])
    with col1:
        n_rows = st.number_input("Кол-во SKU для анализа (по убыванию выручки)",
                                  min_value=1, max_value=min(50, len(summary)), value=min(10, len(summary)))
    with col2:
        st.caption("Рекомендации запрашиваются только по кнопке и кэшируются в рамках сессии, "
                   "чтобы не расходовать лишние вызовы API.")

    if st.button("Получить AI-советы"):
        if not api_key:
            st.error("Введите API-ключ выбранного провайдера в боковой панели.")
        else:
            target_rows = summary.nlargest(int(n_rows), "Выручка")
            progress = st.progress(0)
            errors = []
            for i, (_, row) in enumerate(target_rows.iterrows()):
                sku = row["SKU"]
                if sku not in st.session_state.ai_advice_cache:
                    try:
                        advice = get_sku_advice(provider, api_key, model, row.to_dict())
                        st.session_state.ai_advice_cache[sku] = advice
                    except AIError as e:
                        errors.append(f"{sku}: {e}")
                        break  # прекращаем цикл при первой ошибке (например, неверный ключ)
                progress.progress((i + 1) / len(target_rows))
            if errors:
                st.error("Ошибка при получении рекомендаций:\n" + "\n".join(errors))
            else:
                st.success("Готово! Таблица обновлена.")
                st.rerun()

# --- СТРАНИЦА 2: Дашборды ---
with tab2:
    st.subheader("Визуализация портфеля")
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(plot_margin_pie(summary), use_container_width=True)
    with c2:
        st.plotly_chart(plot_abc_xyz_matrix(summary), use_container_width=True)

    st.markdown("---")
    top_n = st.slider("Количество топ-товаров для графика тренда (по выручке)", 3, 15, 5)
    top_skus = summary.nlargest(top_n, "Выручка")["SKU"].tolist()
    st.plotly_chart(plot_sales_trend(filtered_df, top_skus, MONTH_ORDER), use_container_width=True)

# --- СТРАНИЦА 3: Глобальная ИИ-Стратегия ---
with tab3:
    st.subheader("Стратегический отчёт по всему портфелю (с учётом текущих фильтров)")
    st.caption(filters_desc)

    if st.button("🚀 Сгенерировать стратегию"):
        if not api_key:
            st.error("Введите API-ключ выбранного провайдера в боковой панели.")
        else:
            try:
                with st.spinner(f"{provider} ({model}) анализирует портфель..."):
                    strategy_text = get_portfolio_strategy(provider, api_key, model, summary, filters_desc)
                st.session_state.strategy_history.append({
                    "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "provider": provider,
                    "model": model,
                    "filters_desc": filters_desc,
                    "text": strategy_text,
                })
            except AIError as e:
                st.error(str(e))

    if st.session_state.strategy_history:
        st.markdown("---")
        st.subheader("📜 История стратегий (за текущую сессию)")

        st.download_button(
            "📥 Скачать всю историю (.txt)",
            data=strategy_history_to_text(st.session_state.strategy_history),
            file_name=f"ai_strategy_history_{datetime.date.today()}.txt",
            mime="text/plain",
        )

        for i, entry in enumerate(reversed(st.session_state.strategy_history), start=1):
            idx = len(st.session_state.strategy_history) - i + 1
            with st.expander(f"Стратегия №{idx} — {entry['timestamp']} ({entry['provider']} / {entry['model']})",
                              expanded=(i == 1)):
                st.caption(f"Фильтры: {entry['filters_desc']}")
                st.markdown(entry["text"])
    else:
        st.info("Стратегии ещё не генерировались в этой сессии.")
