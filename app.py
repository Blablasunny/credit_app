import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import re

st.set_page_config(
    page_title="Кредит-Сервис",
    page_icon="$",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# КОНСТАНТЫ КОМПЕНСИРУЮЩЕГО ПРАВИЛА
# ============================================================
MIN_LIVING_WAGE = 25_000          # прожиточный минимум на члена домохозяйства
SCORE_TIER_1 = 75                 # порог «хороший скоринг»
TOLERANCE_TIER_1 = 0.90           # допуск 90% от минимума
SCORE_TIER_2 = 85                 # порог «отличный скоринг»
TOLERANCE_TIER_2 = 0.80           # допуск 80% от минимума
BAD_HISTORY = "Просрочки > 90 дней"


# ============================================================
# ВАЛИДАЦИЯ ВВОДА
# ============================================================
def validate_application(data: dict) -> list[str]:
    errors = []

    if not re.match(r"^[А-Яа-яЁёA-Za-z\s\-]{2,100}$", data["full_name"].strip()):
        errors.append(
            "ФИО должно содержать только буквы, пробелы и дефисы (2–100 символов)."
        )

    max_experience = data["age"] - 14
    if data["employment_years"] > max_experience:
        errors.append(
            f"Стаж ({data['employment_years']} лет) не может превышать "
            f"{max_experience} лет при возрасте {data['age']}."
        )

    if data["employment_type"] == "Безработный" and data["income"] > 0:
        errors.append("Безработный не может иметь официальный доход.")

    if data["existing_payments"] > data["income"]:
        errors.append("Текущие платежи по кредитам не могут превышать доход.")

    return errors


# ============================================================
# СКОРИНГОВЫЕ ФУНКЦИИ (10 ПАРАМЕТРОВ)
# ============================================================
def score_age(age: int) -> tuple[int, str]:
    if 30 <= age <= 50:
        return 15, "Оптимальный возраст"
    if 25 <= age < 30 or 50 < age <= 60:
        return 10, "Приемлемый возраст"
    if 21 <= age < 25 or 60 < age <= 70:
        return 5, "Пограничный возраст"
    return 0, "Возраст вне допустимого диапазона"


def score_income(income: float) -> tuple[int, str]:
    if income >= 200_000:
        return 15, "Высокий доход"
    if income >= 100_000:
        return 12, "Доход выше среднего"
    if income >= 50_000:
        return 8, "Средний доход"
    if income >= 25_000:
        return 4, "Доход ниже среднего"
    return 0, "Низкий доход"


def score_employment_type(emp_type: str) -> tuple[int, str]:
    mapping = {
        "Трудовой договор (бессрочный)": (12, "Стабильное трудоустройство"),
        "Трудовой договор (срочный)": (8, "Срочный договор"),
        "ИП / Самозанятый": (6, "Собственный бизнес"),
        "Фриланс": (4, "Нестабильный доход"),
        "Безработный": (0, "Нет официального дохода"),
    }
    return mapping.get(emp_type, (0, "Неизвестно"))


def score_employment_years(years: float) -> tuple[int, str]:
    if years >= 5:
        return 10, "Длительный стаж"
    if years >= 3:
        return 8, "Хороший стаж"
    if years >= 1:
        return 5, "Средний стаж"
    return 1, "Короткий стаж"


def score_dti(dti: float) -> tuple[int, str]:
    if dti <= 0.20:
        return 15, "Низкая долговая нагрузка"
    if dti <= 0.35:
        return 11, "Умеренная нагрузка"
    if dti <= 0.50:
        return 6, "Повышенная нагрузка"
    if dti <= 0.70:
        return 2, "Высокая нагрузка"
    return 0, "Критическая нагрузка"


def score_credit_history(status: str) -> tuple[int, str]:
    mapping = {
        "Кредитов не было": (5, "Нет кредитной истории"),
        "Без просрочек": (15, "Отличная кредитная история"),
        "Просрочки до 30 дней": (9, "Небольшие просрочки"),
        "Просрочки 30–90 дней": (4, "Существенные просрочки"),
        "Просрочки > 90 дней": (0, "Плохая кредитная история"),
    }
    return mapping.get(status, (0, "Неизвестно"))


def score_loan_to_income(loan: float, income: float) -> tuple[int, str]:
    if income <= 0:
        return 0, "Нет дохода"
    ratio = loan / (income * 12)
    if ratio <= 1:
        return 8, "Сумма ниже годового дохода"
    if ratio <= 2:
        return 6, "Сумма до 2 годовых доходов"
    if ratio <= 3:
        return 4, "Сумма до 3 годовых доходов"
    if ratio <= 5:
        return 2, "Высокая сумма"
    return 0, "Сумма превышает разумные пределы"


def score_term(months: int) -> tuple[int, str]:
    if months <= 12:
        return 5, "Короткий срок"
    if months <= 36:
        return 4, "Средний срок"
    if months <= 60:
        return 3, "Длинный срок"
    return 2, "Очень длинный срок"


def score_marital(status: str) -> tuple[int, str]:
    mapping = {
        "Женат/Замужем": (5, "Стабильное семейное положение"),
        "Не женат/Не замужем": (3, "Одинок"),
        "Разведён(а)": (2, "Развод в прошлом"),
        "Вдовец/Вдова": (3, "Вдовство"),
    }
    return mapping.get(status, (0, "Неизвестно"))


def score_dependents(n: int) -> tuple[int, str]:
    if n == 0:
        return 5, "Нет иждивенцев"
    if n == 1:
        return 4, "Один иждивенец"
    if n == 2:
        return 2, "Двое иждивенцев"
    return 0, "Много иждивенцев"


# ============================================================
# РАСЧЁТ ПЛАТЕЖА
# ============================================================
def estimate_monthly_payment(principal: float, annual_rate: float, months: int) -> float:
    if months <= 0:
        return 0.0
    r = annual_rate / 100 / 12
    if r == 0:
        return principal / months
    return principal * r / (1 - (1 + r) ** (-months))


# ============================================================
# ИТОГОВЫЙ СКОРИНГ
# ============================================================
def calculate_score(data: dict) -> dict:
    details = []

    s, msg = score_age(data["age"])
    details.append(("Возраст", s, 15, msg))

    s, msg = score_income(data["income"])
    details.append(("Доход", s, 15, msg))

    s, msg = score_employment_type(data["employment_type"])
    details.append(("Тип занятости", s, 12, msg))

    s, msg = score_employment_years(data["employment_years"])
    details.append(("Стаж", s, 10, msg))

    new_monthly = estimate_monthly_payment(
        data["loan_amount"], data["rate"], data["term_months"]
    )
    total_monthly = data["existing_payments"] + new_monthly
    dti = total_monthly / data["income"] if data["income"] > 0 else 1.0

    s, msg = score_dti(dti)
    details.append(("Долговая нагрузка (DTI)", s, 15, f"{msg} (DTI={dti:.0%})"))

    s, msg = score_credit_history(data["credit_history"])
    details.append(("Кредитная история", s, 15, msg))

    s, msg = score_loan_to_income(data["loan_amount"], data["income"])
    details.append(("Сумма / годовой доход", s, 8, msg))

    s, msg = score_term(data["term_months"])
    details.append(("Срок кредита", s, 5, msg))

    s, msg = score_marital(data["marital_status"])
    details.append(("Семейное положение", s, 5, msg))

    s, msg = score_dependents(data["dependents"])
    details.append(("Иждивенцы", s, 5, msg))

    total = sum(d[1] for d in details)
    max_total = sum(d[2] for d in details)
    normalized = round(total / max_total * 100)

    # --- ПРАВИЛО ОСТАТОЧНОГО ДОХОДА (с компенсацией за высокий скоринг) ---
    household_size = 1 + data["dependents"]
    required_minimum = MIN_LIVING_WAGE * household_size
    free_income = data["income"] - total_monthly

    has_bad_history = data["credit_history"] == BAD_HISTORY

    if normalized >= SCORE_TIER_2 and not has_bad_history:
        tolerance = TOLERANCE_TIER_2
        compensation_note = (
            f"Скоринг {normalized}/100 — превосходный профиль. "
            f"Требование к остатку снижено до {tolerance:.0%} прожиточного минимума."
        )
    elif normalized >= SCORE_TIER_1 and not has_bad_history:
        tolerance = TOLERANCE_TIER_1
        compensation_note = (
            f"Скоринг {normalized}/100 — хороший профиль. "
            f"Требование к остатку снижено до {tolerance:.0%} прожиточного минимума."
        )
    else:
        tolerance = 1.0
        compensation_note = None
        if has_bad_history and normalized >= SCORE_TIER_1:
            compensation_note = (
                "Компенсирующее правило не применено: "
                "просрочки более 90 дней блокируют послабление."
            )

    effective_minimum = required_minimum * tolerance

    rejection_reason = None
    compensated = False

    if free_income < effective_minimum:
        tolerance_note = (
            f", с учётом компенсирующего правила × {tolerance:.0%}"
            if tolerance < 1.0
            else ""
        )
        rejection_reason = (
            f"Недостаточно средств после погашения кредита: остаётся "
            f"{free_income:,.0f} ₽/мес, а требуется минимум "
            f"{effective_minimum:,.0f} ₽/мес "
            f"(прожиточный минимум {MIN_LIVING_WAGE:,.0f} ₽ × "
            f"{household_size} чел. домохозяйства{tolerance_note})."
        )
    elif tolerance < 1.0 and free_income < required_minimum:
        compensated = True

    base_result = {
        "details": details,
        "total": total,
        "max_total": max_total,
        "normalized": normalized,
        "dti": dti,
        "new_monthly": new_monthly,
        "total_monthly": total_monthly,
        "rejection_reason": rejection_reason,
        "free_income": free_income,
        "required_minimum": required_minimum,
        "effective_minimum": effective_minimum,
        "tolerance": tolerance,
        "compensation_note": compensation_note,
        "compensated": compensated,
    }

    if rejection_reason:
        return {
            **base_result,
            "decision": "ОТКАЗАНО",
            "color": "red",
            "rate_add": None,
        }

    if normalized >= SCORE_TIER_1:
        decision = "ОДОБРЕН"
        color = "green"
        rate_add = 0.0
    elif normalized >= 55:
        decision = "ОДОБРЕН (повышенная ставка)"
        color = "orange"
        rate_add = 3.0
    elif normalized >= 40:
        decision = "ОДОБРЕН ЧАСТИЧНО (сокращённая сумма)"
        color = "orange"
        rate_add = 5.0
    else:
        decision = "ОТКАЗАНО"
        color = "red"
        rate_add = None

    return {
        **base_result,
        "decision": decision,
        "color": color,
        "rate_add": rate_add,
    }


# ============================================================
# СТРАНИЦА 1 — ЗАЯВКА
# ============================================================
def page_application():
    st.title("Заявка на кредит")
    st.caption("Заполните все поля, а система рассчитает скоринг.")

    with st.form("credit_form"):
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Личные данные")
            full_name = st.text_input("ФИО", placeholder="Иванов Иван Иванович")
            age = st.number_input(
                "Возраст", min_value=18, max_value=80, value=30, step=1
            )
            marital_status = st.selectbox(
                "Семейное положение",
                ["Женат/Замужем", "Не женат/Не замужем", "Разведён(а)", "Вдовец/Вдова"],
            )
            dependents = st.number_input("Количество иждивенцев", 0, 10, 0)

            st.subheader("Занятость")
            employment_type = st.selectbox(
                "Тип занятости",
                [
                    "Трудовой договор (бессрочный)",
                    "Трудовой договор (срочный)",
                    "ИП / Самозанятый",
                    "Фриланс",
                    "Безработный",
                ],
            )
            employment_years = st.number_input(
                "Стаж на текущем месте, лет", 0.0, 50.0, 2.0, step=0.5
            )
            income = st.number_input(
                "Ежемесячный доход, ₽", 0.0, 10_000_000.0, 80_000.0, step=5_000.0
            )
            existing_payments = st.number_input(
                "Текущие ежемесячные платежи по кредитам, ₽",
                0.0,
                1_000_000.0,
                0.0,
                step=1_000.0,
            )

        with col2:
            st.subheader("Параметры кредита")
            loan_amount = st.number_input(
                "Сумма кредита, руб.",
                10_000.0,
                20_000_000.0,
                500_000.0,
                step=10_000.0,
            )
            term_months = st.slider("Срок, мес.", 6, 120, 36, step=6)
            rate = st.number_input(
                "Базовая ставка, % годовых", 0.0, 50.0, 15.0, step=0.5
            )

            st.subheader("Кредитная история")
            credit_history = st.selectbox(
                "История платежей",
                [
                    "Кредитов не было",
                    "Без просрочек",
                    "Просрочки до 30 дней",
                    "Просрочки 30–90 дней",
                    "Просрочки > 90 дней",
                ],
            )

        submitted = st.form_submit_button(
            "Отправить заявку", use_container_width=True
        )

    if submitted:
        if not full_name.strip():
            st.error("Пожалуйста, укажите ФИО.")
            return
        if income <= 0:
            st.error("Доход должен быть больше нуля.")
            return

        data = {
            "full_name": full_name,
            "age": int(age),
            "marital_status": marital_status,
            "dependents": int(dependents),
            "employment_type": employment_type,
            "employment_years": float(employment_years),
            "income": float(income),
            "existing_payments": float(existing_payments),
            "loan_amount": float(loan_amount),
            "term_months": int(term_months),
            "rate": float(rate),
            "credit_history": credit_history,
        }

        errors = validate_application(data)
        if errors:
            for err in errors:
                st.error(err)
            return

        result = calculate_score(data)
        st.session_state["application"] = data
        st.session_state["result"] = result

        st.markdown("---")
        if result["decision"].startswith("ОДОБРЕН"):
            st.success(f"### Решение: {result['decision']}")
            if result.get("compensated"):
                st.info(
                    "**Применено компенсирующее правило:** остаток ниже "
                    "стандартного минимума, но одобрен благодаря высокому скорингу."
                )
        else:
            st.error(f"### Решение: {result['decision']}")
            if result.get("rejection_reason"):
                st.warning(f"**Причина:** {result['rejection_reason']}")

        c1, c2, c3 = st.columns(3)
        c1.metric("Скоринговый балл", f"{result['normalized']} / 100")
        c2.metric("DTI", f"{result['dti']:.1%}")
        c3.metric("Новый платёж/мес", f"{result['new_monthly']:,.0f} ₽")

        st.info(
            "Перейдите на страницу **«Детали расчёта»** в боковом меню "
            "для подробностей."
        )


# ============================================================
# СТРАНИЦА 2 — ДЕТАЛИ РАСЧЁТА
# ============================================================
def page_details():
    st.title("Детали расчёта и скоринг")

    if "application" not in st.session_state or "result" not in st.session_state:
        st.warning("Сначала заполните заявку на странице «Заявка».")
        return

    data = st.session_state["application"]
    result = st.session_state["result"]

    # --- Решение ---
    st.subheader("Решение по заявке")
    if result["decision"].startswith("ОДОБРЕН"):
        st.success(
            f"**{result['decision']}** — скоринговый балл "
            f"{result['normalized']}/100"
        )
    else:
        st.error(
            f"**{result['decision']}** — скоринговый балл "
            f"{result['normalized']}/100"
        )
        if result.get("rejection_reason"):
            st.warning(f"**Причина отказа:** {result['rejection_reason']}")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Скоринг", f"{result['normalized']}/100")
    col2.metric("Сырые баллы", f"{result['total']}/{result['max_total']}")
    col3.metric("DTI", f"{result['dti']:.1%}")
    col4.metric("Платёж/мес", f"{result['new_monthly']:,.0f} ₽")

    st.progress(result["normalized"] / 100)

    st.markdown("---")

    # --- Проверка остаточного дохода ---
    st.subheader("Проверка остаточного дохода")
    free_income = result.get(
        "free_income", data["income"] - result["total_monthly"]
    )
    required_minimum = result.get("required_minimum")
    effective_minimum = result.get("effective_minimum", required_minimum)
    tolerance = result.get("tolerance", 1.0)
    compensated = result.get("compensated", False)
    compensation_note = result.get("compensation_note")

    col1, col2, col3 = st.columns(3)
    col1.metric("Свободные средства/мес", f"{free_income:,.0f} ₽")
    if required_minimum is not None:
        col2.metric("Прожиточный минимум", f"{required_minimum:,.0f} ₽")
    if effective_minimum is not None and tolerance < 1.0:
        col3.metric(
            f"Требуется (×{tolerance:.0%})",
            f"{effective_minimum:,.0f} ₽",
            delta=f"−{required_minimum - effective_minimum:,.0f} ₽",
            delta_color="inverse",
        )
    elif effective_minimum is not None:
        col3.metric("Требуется", f"{effective_minimum:,.0f} ₽")

    if result.get("rejection_reason"):
        st.error(f"**Причина отказа:** {result['rejection_reason']}")
    elif compensated:
        st.info(
            f"**Одобрено с применением компенсирующего правила.** "
            f"После всех платежей остаётся {free_income:,.0f} ₽/мес — "
            f"это ниже стандартного минимума {required_minimum:,.0f} ₽/мес, "
            f"но выше пониженного порога {effective_minimum:,.0f} ₽/мес "
            f"(×{tolerance:.0%}) благодаря высокому скорингу."
        )
        if compensation_note:
            st.caption(compensation_note)
    elif effective_minimum is not None and free_income >= effective_minimum:
        st.success(
            f"После всех платежей остаётся {free_income:,.0f} ₽/мес — "
            f"это выше требуемого минимума {effective_minimum:,.0f} ₽/мес."
        )

    if compensation_note and not compensated:
        st.caption(compensation_note)

    st.markdown("---")

    # --- Детализация по параметрам ---
    st.subheader("Детализация скоринговых параметров")
    df = pd.DataFrame(
        [
            {
                "Параметр": name,
                "Балл": score,
                "Макс.": mx,
                "Вклад, %": round(score / mx * 100) if mx else 0,
                "Комментарий": comment,
            }
            for name, score, mx, comment in result["details"]
        ]
    )
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.subheader("Вклад параметров")
    chart_df = df.set_index("Параметр")[["Балл"]]
    st.bar_chart(chart_df)

    st.markdown("---")

    # --- Параметры кредита ---
    st.subheader("Параметры кредита")
    col1, col2 = st.columns(2)
    with col1:
        st.write(f"**Заёмщик:** {data['full_name']}")
        st.write(f"**Сумма кредита:** {data['loan_amount']:,.0f} ₽")
        st.write(f"**Срок:** {data['term_months']} мес.")
        st.write(f"**Базовая ставка:** {data['rate']}%")

    with col2:
        st.write(f"**Доход:** {data['income']:,.0f} ₽/мес")
        st.write(f"**Текущие платежи:** {data['existing_payments']:,.0f} ₽/мес")
        st.write(f"**Новый платёж:** {result['new_monthly']:,.0f} ₽/мес")
        st.write(f"**Суммарная нагрузка:** {result['total_monthly']:,.0f} ₽/мес")

    # --- Итоговая ставка ---
    if result["rate_add"] is not None:
        final_rate = data["rate"] + result["rate_add"]
        st.subheader("Предложение банка")
        st.write(
            f"**Итоговая ставка:** {final_rate:.2f}% годовых "
            f"(базовая {data['rate']}% + надбавка {result['rate_add']}%)"
        )
        total_payment = result["new_monthly"] * data["term_months"]
        total_interest = total_payment - data["loan_amount"]
        c1, c2, c3 = st.columns(3)
        c1.metric("Платёж/мес", f"{result['new_monthly']:,.0f} ₽")
        c2.metric("Переплата", f"{total_interest:,.0f} ₽")
        c3.metric("Всего выплат", f"{total_payment:,.0f} ₽")
    else:
        st.error("Итоговая ставка не рассчитывается — заявка отклонена.")

    st.markdown("---")
    st.caption(
        "Скоринговая модель учитывает 10 параметров: возраст, доход, тип занятости, "
        "стаж, DTI, кредитную историю, соотношение суммы к доходу, срок, "
        "семейное положение и иждивенцев. Модель демонстрационная."
    )


# ============================================================
# НАВИГАЦИЯ
# ============================================================
def main():
    st.sidebar.title("Кредит-Сервис")
    page = st.sidebar.radio("Навигация", ["Заявка", "Детали расчёта"])
    st.sidebar.markdown("---")
    st.sidebar.caption("Демо-версия. Не является финансовой рекомендацией.")

    if page == "Заявка":
        page_application()
    else:
        page_details()


if __name__ == "__main__":
    main()
