"""
Модуль интеграции с ИИ. Поддерживает два провайдера на выбор пользователя:
- OpenAI (Chat Completions API)
- Google Gemini (google-generativeai SDK)

У Gemini другой протокол вызова (system_instruction передаётся отдельно при создании
модели, а не как обычное сообщение) — поэтому реализованы раздельные функции вызова,
но единый системный промпт с бизнес-логикой (см. ТЗ, раздел 5).

Точечные AI-советы по SKU вызываются НЕ автоматически для каждой строки таблицы
(дорого и медленно при большом количестве SKU), а по кнопке, с ограничением числа
строк и кэшированием в session_state — см. app.py.
"""

OPENAI_MODELS = ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"]
GEMINI_MODELS = ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash", "gemini-1.5-pro"]

SYSTEM_PROMPT = """
Ты — финансовый директор (CFO) и эксперт по управленческому учёту, специализирующийся
на ABC-XYZ анализе товарного портфеля. Твои рекомендации должны строго следовать
следующей логике:

ВЛИЯНИЕ XYZ НА ЗАКУПКИ:
- X: максимальная автоматизация закупок, минимальный страховой запас.
- Y: ручной контроль, учитывать тренды продаж.
- Z: работа под заказ либо нулевой остаток, высокий риск заморозки средств.

ФИНАНСОВАЯ ЛОГИКА РЕКОМЕНДАЦИЙ:

ЦЕНООБРАЗОВАНИЕ:
- Если товар с высокой маржой (последняя буква ABC-кода = A, например CAA) —
  аккуратно повышать цену.
- Если товар с низкой маржой (последняя буква = C) — искать новых поставщиков
  для снижения себестоимости или принудительно повышать цену.

СКИДКИ:
- Группы A и B: скидки предоставлять только оптовым покупателям.
- Группа C: скидки — исключительно как экстренный инструмент высвобождения
  замороженного капитала.

ВЫВОД ИЗ АССОРТИМЕНТА (делистинг):
- Комбинации CCC, BCC, CBC — жёсткая директива на распродажу остатков и вывод
  из ассортимента, если это не якорный (стратегически важный) товар.

ОСТАТКИ:
- Оценивать гибко, с опорой на текущий остаток и скорость продаж.

Отвечай кратко, конкретно, на русском языке, в формате практической рекомендации
для менеджера по закупкам/ценообразованию.
"""


class AIError(Exception):
    """Исключение для ошибок работы с ИИ-модулем (нет ключа, ошибка API и т.п.)."""
    pass


def _call_openai(api_key: str, model: str, user_prompt: str, max_tokens: int = 500) -> str:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.4,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        raise AIError(f"Ошибка обращения к OpenAI API: {e}")


def _call_gemini(api_key: str, model: str, user_prompt: str, max_tokens: int = 500) -> str:
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model_obj = genai.GenerativeModel(model_name=model, system_instruction=SYSTEM_PROMPT)
        response = model_obj.generate_content(
            user_prompt,
            generation_config={"temperature": 0.4, "max_output_tokens": max_tokens},
        )
        if not response.candidates:
            raise AIError("Gemini не вернул ответ (возможно, сработал фильтр безопасности).")
        return response.text.strip()
    except AIError:
        raise
    except Exception as e:
        raise AIError(f"Ошибка обращения к Gemini API: {e}")


def _call_ai(provider: str, api_key: str, model: str, user_prompt: str, max_tokens: int = 500) -> str:
    if not api_key:
        raise AIError("API-ключ не введён. Введите его в боковой панели, чтобы получить AI-рекомендации.")
    if provider == "OpenAI":
        return _call_openai(api_key, model, user_prompt, max_tokens)
    elif provider == "Gemini":
        return _call_gemini(api_key, model, user_prompt, max_tokens)
    else:
        raise AIError(f"Неизвестный провайдер ИИ: {provider}")


def get_sku_advice(provider: str, api_key: str, model: str, row: dict) -> str:
    """Точечная рекомендация по одному SKU (2-4 предложения)."""
    prompt = f"""
Проанализируй товар и дай краткую рекомендацию (2-4 предложения).

SKU: {row.get('SKU')}
Наименование: {row.get('Наименование')}
Категория: {row.get('Категория')}
Итоговый статус (ABC-XYZ): {row.get('Итоговый_статус')}
Выручка за период: {row.get('Выручка', 0):.0f}
Маржа за период: {row.get('Маржа', 0):.0f}
Продажи, шт.: {row.get('Продажи шт.', 0):.0f}
Текущий остаток: {row.get('Текущий_остаток')}

Дай рекомендацию по: ценообразованию, скидкам, закупкам/остаткам,
и стоит ли рассматривать делистинг.
"""
    return _call_ai(provider, api_key, model, prompt)


def get_portfolio_strategy(provider: str, api_key: str, model: str, summary_df, filters_desc: str) -> str:
    """Развёрнутый стратегический отчёт по всему отфильтрованному портфелю."""
    status_counts = summary_df["Итоговый_статус"].value_counts().to_dict()
    total_revenue = summary_df["Выручка"].sum()
    total_margin = summary_df["Маржа"].sum()

    delisting_mask = summary_df["Итоговый_статус"].str.startswith(("CCC", "BCC", "CBC"), na=False)
    top_margin = summary_df.nlargest(5, "Маржа")[["SKU", "Наименование", "Итоговый_статус", "Маржа"]]
    delisting_candidates = summary_df[delisting_mask].head(8)[["SKU", "Наименование", "Итоговый_статус"]]

    prompt = f"""
Проанализируй товарный портфель компании и составь развёрнутый стратегический отчёт для CFO.

Применённые фильтры: {filters_desc}
Всего SKU в выборке: {len(summary_df)}
Суммарная выручка: {total_revenue:.0f}
Суммарная маржа: {total_margin:.0f}
Распределение по ABC-XYZ статусам: {status_counts}

Топ-5 товаров по марже:
{top_margin.to_string(index=False)}

Кандидаты на делистинг (статус CCC/BCC/CBC):
{delisting_candidates.to_string(index=False) if not delisting_candidates.empty else "нет кандидатов в выборке"}

Составь отчёт со следующими блоками:
1. Общая оценка состояния портфеля
2. Ключевые риски (заморозка капитала, дефицит по важным позициям)
3. Приоритетные действия по ценообразованию
4. Приоритетные действия по закупкам и остаткам
5. Рекомендации по делистингу
"""
    return _call_ai(provider, api_key, model, prompt, max_tokens=1400)
