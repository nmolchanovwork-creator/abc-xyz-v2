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
    utils/styling.py           — цветовая подсветка таблицы (ABC/XYZ)
    utils/recommendations.py   — готовые (заранее заготовленные) рекомендации по ABC-коду
    utils/recommendations.csv  — сама таблица готовых рекомендаций
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
from utils.visualizations import (
    plot_margin_pie, plot_abc_xyz_matrix, plot_sales_trend,
    plot_pareto, plot_turnover_by_group, plot_xyz_distribution,
)
from utils.export_helper import summary_to_excel_bytes, strategy_history_to_text
from utils.styling import style_summary_table
from utils.recommendations import merge_recommendations

st.set_page_config(page_title="ABC-XYZ анализ", layout="wide", page_icon="📊")

# ---------------------------------------------------------------------------
# ИНИЦИАЛИЗАЦИЯ SESSION_STATE
# ---------------------------------------------------------------------------
if "ai_advice_cache" not in st.session_state:
    st.session_state.ai_advice_cache = {}
if "strategy_history" not in st.session_state:
    st.session_state.strategy_history = []

# ---------------------------------------------------------------------------
# БОКОВАЯ ПАНЕЛЬ
# ---------------------------------------------------------------------------
st.sidebar.title("⚙️ Настройки")

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

if df is None or df.empty:
    st.title("📊 Интегральный ABC-XYZ анализ")
    st.info("⬅️ Загрузите файл с данными (или включите демо-режим) в боковой панели, чтобы начать анализ.")
    st.stop()

# --- ИИ-модуль ---
st.sidebar.subheader("ИИ-модуль")
provider = st.sidebar.radio("Провайдер ИИ", ["OpenAI", "Gemini"], horizontal=True)
if provider == "OpenAI":
    api_key = st.sidebar.text_input("OpenAI API-ключ", type="password")
    model = st.sidebar.selectbox("Модель OpenAI", OPENAI_MODELS)
else:
    api_key = st.sidebar.text_input("Gemini API-ключ", type="password")
    model = st.sidebar.selectbox("Модель Gemini", GEMINI_MODELS)
st.sidebar.caption("Ключ используется только в рамках текущей сессии и не сохраняется.")

# --- Настройки алгоритма ABC/XYZ ---
st.sidebar.subheader("Границы ABC (накопительно, %)")
abc_a = st.sidebar.slider("Группа A — до, %", 50, 95, 80)
abc_b = st.sidebar.slider("Группа A+B — до, %", abc_a + 1, 99, min(abc_a + 15, 99))
thr_a, thr_b = abc_a / 100, abc_b / 100

st.sidebar.subheader("Границы XYZ (коэфф. вариации, %)")
xyz_x = st.sidebar.slider("X — CV меньше, %", 1, 30, 10)
xyz_y = st.sidebar.slider("Y — CV меньше, %", xyz_x + 1, 60, max(xyz_x + 15, 25))
thr_x, thr_y = xyz_x / 100, xyz_y / 100

st.sidebar.subheader("Интегральный ABC")
use_integral = st.sidebar.checkbox(
    "Использовать интегральный вес ABC",
    help="Вместо трёх отдельных букв (по выручке, количеству и марже) считается "
         "ОДИН общий скор товара = вес_выручки×доля_выручки + вес_количества×доля_количества "
         "+ вес_маржи×доля_маржи. По этому скору товару присваивается одна буква A/B/C. "
         "Удобно, когда нужен единый приоритет товара, а не три критерия по отдельности.",
)
weights = None
if use_integral:
    st.sidebar.caption(
        "Задайте, что важнее для вашего бизнеса: если важнее объём продаж — увеличьте вес "
        "Количества; если важнее прибыльность — увеличьте вес Маржи. Сумма весов должна быть 100%."
    )
    w_rev = st.sidebar.slider("Вес Выручки, %", 0, 100, 40)
    w_qty = st.sidebar.slider("Вес Количества, %", 0, 100, 20)
    w_margin = st.sidebar.slider("Вес Маржи, %", 0, 100, 40)
    total_w = w_rev + w_qty + w_margin
    if total_w != 100:
        st.sidebar.warning(f"Сумма весов = {total_w}%, должна быть 100%. Веса будут автоматически нормализованы.")
    if total_w == 0:
        total_w = 1
    weights = {"revenue": w_rev / total_w, "qty": w_qty / total_w, "margin": w_margin / total_w}

# ---------------------------------------------------------------------------
# ГЛАВНАЯ ОБЛАСТЬ: заголовок + мини-инструкция
# ---------------------------------------------------------------------------
st.title("📊 Интегральный ABC-XYZ анализ")

with st.expander("ℹ️ Как пользоваться приложением", expanded=False):
    st.markdown("""
1. **Скачайте шаблон** Excel в боковой панели («📥 Скачать шаблон Excel») и заполните его своими данными
   (или сразу включите «Демо-данные», чтобы посмотреть, как всё работает).
2. **Загрузите файл** через боковую панель.
3. **Настройте фильтры** ниже (категория, тип продажи, год, месяц) и, при желании, границы
   ABC/XYZ и интегральный вес в боковой панели.
4. Вкладка **«Аналитика и Действия»** — сводная таблица с цветовой подсветкой групп и точечные AI-советы.
5. Вкладка **«Рекомендации»** — готовые стандартные рекомендации по каждой ABC-XYZ комбинации
   (цена / скидка / остаток / продвижение / вывод из ассортимента).
6. Вкладка **«Дашборды»** — ключевые показатели и графики для управления портфелем.
7. Вкладка **«Глобальная ИИ-Стратегия»** — развёрнутый текстовый отчёт от ИИ по всему портфелю
   (нужен API-ключ OpenAI или Gemini в боковой панели).

**Цвета в таблице:** 🟢 A (лучшая группа) · 🟡 B (средняя) · 🔴 C (слабая) — по выручке, количеству и марже отдельно.
Для XYZ (стабильность спроса) — отдельная палитра: 🔵 X (стабильный) · 🟣 Y (колеблющийся) · 🟠 Z (нестабильный).
""")

# ---------------------------------------------------------------------------
# ФИЛЬТРЫ — над таблицей, в главной области
# ---------------------------------------------------------------------------
st.subheader("Фильтры")
categories = sorted(df["Категория"].dropna().unique().tolist())
sale_types = sorted(df["Тип продажи"].dropna().unique().tolist())
years = sorted(df["Год"].dropna().unique().tolist())
months_present = [m for m in MONTH_ORDER if m in df["Месяц"].unique()] or sorted(df["Месяц"].unique().tolist())

fc1, fc2, fc3, fc4 = st.columns(4)
with fc1:
    f_categories = st.multiselect("Категория", categories, default=categories)
with fc2:
    f_sale_types = st.multiselect("Тип продажи", sale_types, default=sale_types)
with fc3:
    f_years = st.multiselect("Год", years, default=years)
with fc4:
    f_months = st.multiselect("Месяц", months_present, default=months_present)

filtered_df = df[
    df["Категория"].isin(f_categories)
    & df["Тип продажи"].isin(f_sale_types)
    & df["Год"].isin(f_years)
    & df["Месяц"].isin(f_months)
]

if filtered_df.empty:
    st.warning("⚠️ После применения фильтров не осталось ни одной строки данных. Измените фильтры выше.")
    st.stop()

# ---------------------------------------------------------------------------
# РАСЧЁТ ABC-XYZ
# ---------------------------------------------------------------------------
summary = build_summary(filtered_df, thr_a, thr_b, thr_x, thr_y, use_integral, weights)

if summary.empty:
    st.warning("⚠️ Не удалось построить сводную таблицу — проверьте данные и фильтры.")
    st.stop()

summary["AI Совет"] = summary["SKU"].map(st.session_state.ai_advice_cache).fillna("—")

filters_desc = (f"Категории: {f_categories}; Тип продажи: {f_sale_types}; "
                f"Год: {f_years}; Месяцы: {f_months}")

# Если выбрана только одна категория — не показываем колонку "Категория" в таблице (она избыточна)
show_category_col = len(f_categories) != 1

st.markdown("---")

# ---------------------------------------------------------------------------
# ВКЛАДКИ
# ---------------------------------------------------------------------------
tab1, tab2, tab3, tab4 = st.tabs([
    "🗂️ Аналитика и Действия", "📋 Рекомендации", "📈 Дашборды", "🧠 Глобальная ИИ-Стратегия",
])

# --- СТРАНИЦА 1: Аналитика и Действия ---
with tab1:
    st.subheader("Сводная таблица по SKU")

    legend = " · ".join([f"🟩 A" , "🟨 B", "🟥 C", "  |  ", "🟦 X", "🟪 Y", "🟧 Z"])
    st.caption(f"Легенда: {legend} — ABC (выручка/кол-во/маржа) и XYZ (стабильность спроса)")

    base_cols = ["SKU", "Наименование"]
    if show_category_col:
        base_cols.append("Категория")
    value_cols = ["Продажи шт.", "Выручка", "Маржа"]
    tail_cols = ["Текущий_остаток", "XYZ_код", "Итоговый_статус", "AI Совет"]
    hidden_letter_cols = ["ABC_Выручка", "ABC_Количество", "ABC_Маржа"]

    display_cols = base_cols + value_cols + tail_cols + hidden_letter_cols
    display_cols = [c for c in display_cols if c in summary.columns]
    display_df = summary[display_cols].reset_index(drop=True)

    abc_letter_map = {"Выручка": "ABC_Выручка", "Продажи шт.": "ABC_Количество", "Маржа": "ABC_Маржа"}
    styled = style_summary_table(display_df, abc_letter_map, xyz_col="XYZ_код")
    st.dataframe(styled, use_container_width=True, height=450)

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
                        break
                progress.progress((i + 1) / len(target_rows))
            if errors:
                st.error("Ошибка при получении рекомендаций:\n" + "\n".join(errors))
            else:
                st.success("Готово! Таблица обновлена.")
                st.rerun()

# --- СТРАНИЦА 2: Рекомендации (готовые стандартные правила) ---
with tab2:
    st.subheader("Готовые рекомендации по ABC-XYZ комбинации")
    st.caption(
        "Стандартные правила по цене, скидке, остатку, продвижению и выводу из ассортимента "
        "для каждой из 27 комбинаций ABC-кода (буквы — Выручка / Количество / Маржа). "
        "Правило «по ВЫВОДУ» также стоит сверять с колонкой XYZ: например, при XYZ = Z "
        "риск делистинга или заморозки капитала выше."
    )

    recs_df = merge_recommendations(summary)

    rec_base_cols = ["SKU", "Наименование"]
    if show_category_col:
        rec_base_cols.append("Категория")
    rec_display_cols = rec_base_cols + [
        "ABC_код", "XYZ_код", "Итоговый_статус",
        "по ЦЕНЕ", "по СКИДКЕ", "по ОСТАТКУ", "по ПРОДВИЖЕНИЮ", "по ВЫВОДУ",
    ]
    rec_display_cols = [c for c in rec_display_cols if c in recs_df.columns]

    abc_filter = st.multiselect(
        "Показать только ABC-группы (по первой букве кода — выручка)",
        ["A", "B", "C"], default=["A", "B", "C"],
    )
    recs_view = recs_df[recs_df["ABC_код"].str[0].isin(abc_filter)]

    st.dataframe(recs_view[rec_display_cols].reset_index(drop=True), use_container_width=True, height=450)

    st.download_button(
        "📥 Скачать таблицу с рекомендациями (CSV)",
        data=recs_view[rec_display_cols].to_csv(index=False).encode("utf-8-sig"),
        file_name=f"abc_xyz_recommendations_{datetime.date.today()}.csv",
        mime="text/csv",
    )

# --- СТРАНИЦА 3: Дашборды ---
with tab3:
    st.subheader("Ключевые показатели портфеля")

    total_revenue = summary["Выручка"].sum()
    total_margin = summary["Маржа"].sum()
    margin_rate = (total_margin / total_revenue * 100) if total_revenue > 0 else 0
    delisting_count = summary["Итоговый_статус"].str.startswith(("CCC", "BCC", "CBC"), na=False).sum()
    frozen_capital = (
        summary.loc[summary["XYZ_код"] == "Z", "Себестоимость"]
        * summary.loc[summary["XYZ_код"] == "Z", "Текущий_остаток"]
    ).sum()
    avg_turnover = (summary["Продажи шт."] / summary["Текущий_остаток"].replace(0, pd.NA)).mean()

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Суммарная выручка", f"{total_revenue:,.0f}".replace(",", " "))
    k2.metric("Суммарная маржа", f"{total_margin:,.0f}".replace(",", " "))
    k3.metric("Рентабельность по марже", f"{margin_rate:.1f}%")
    k4.metric("Всего SKU в выборке", f"{len(summary)}")

    k5, k6 = st.columns(2)
    k5.metric("SKU-кандидатов на делистинг", f"{delisting_count}",
              help="Комбинации CCC / BCC / CBC — жёсткая директива на распродажу и вывод из ассортимента.")
    k6.metric("Капитал, замороженный в неликвиде (оценка)", f"{frozen_capital:,.0f}".replace(",", " "),
              help="Себестоимость × Текущий остаток для товаров с нестабильным спросом (XYZ = Z).")

    st.markdown("---")
    st.plotly_chart(plot_pareto(summary), use_container_width=True)
    st.caption("Показывает, насколько узкая группа SKU формирует основную выручку — суть ABC-анализа.")

    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.plotly_chart(plot_margin_pie(summary), use_container_width=True)
    with c2:
        st.plotly_chart(plot_xyz_distribution(summary), use_container_width=True)
    with c3:
        st.plotly_chart(plot_abc_xyz_matrix(summary), use_container_width=True)

    st.markdown("---")
    c4, c5 = st.columns(2)
    with c4:
        st.plotly_chart(plot_turnover_by_group(summary), use_container_width=True)
        st.caption("Низкая оборачиваемость в группе A — риск дефицита ключевых товаров; "
                   "высокая в группе C — риск затоваривания.")
    with c5:
        top_n = st.slider("Топ-товаров для графика тренда (по выручке)", 3, 15, 5)
        top_skus = summary.nlargest(top_n, "Выручка")["SKU"].tolist()
        st.plotly_chart(plot_sales_trend(filtered_df, top_skus, MONTH_ORDER), use_container_width=True)

# --- СТРАНИЦА 4: Глобальная ИИ-Стратегия ---
with tab4:
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
