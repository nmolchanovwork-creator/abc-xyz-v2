"""
Модуль цветовой стилизации сводной таблицы.

ABC — тёплая "светофорная" палитра приглушённых тонов: A зелёный, B жёлтый, C красный.
XYZ — отдельная, визуально не пересекающаяся палитра холодных тонов: X синий,
Y фиолетовый, Z оранжевый — чтобы ABC и XYZ не путались между собой при взгляде на таблицу.
"""

import pandas as pd

ABC_STYLE = {
    "A": "background-color:#e6f4ea; color:#1e5631;",
    "B": "background-color:#fdf6e3; color:#8a6d1d;",
    "C": "background-color:#fbe9e7; color:#9b3a34;",
}

XYZ_STYLE = {
    "X": "background-color:#e3f2fd; color:#1a5276;",
    "Y": "background-color:#ede7f6; color:#5b2c6f;",
    "Z": "background-color:#fff3e0; color:#935116;",
}

# Цвета для легенды (используются в подписях/expander'ах)
ABC_LEGEND_COLORS = {"A": "#e6f4ea", "B": "#fdf6e3", "C": "#fbe9e7"}
XYZ_LEGEND_COLORS = {"X": "#e3f2fd", "Y": "#ede7f6", "Z": "#fff3e0"}


def style_summary_table(display_df: pd.DataFrame, abc_letter_cols: dict, xyz_col: str = "XYZ_код"):
    """
    Возвращает pandas Styler с подсветкой ячеек.

    abc_letter_cols: словарь {колонка_со_значением: колонка_с_буквой}, например
        {"Выручка": "ABC_Выручка", "Продажи шт.": "ABC_Количество", "Маржа": "ABC_Маржа"}
    Служебные колонки с буквами (значения из abc_letter_cols) скрываются из вывода,
    но используются для расчёта цвета.
    """

    def highlight(row):
        styles = pd.Series("", index=row.index)
        for value_col, letter_col in abc_letter_cols.items():
            if value_col in row.index and letter_col in row.index:
                letter = row[letter_col]
                styles[value_col] = ABC_STYLE.get(letter, "")
        if xyz_col in row.index:
            styles[xyz_col] = XYZ_STYLE.get(row[xyz_col], "")
        return styles

    styler = display_df.style.apply(highlight, axis=1)

    hidden_cols = [c for c in abc_letter_cols.values() if c in display_df.columns]
    if hidden_cols:
        styler = styler.hide(axis="columns", subset=hidden_cols)

    return styler
