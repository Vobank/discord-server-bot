"""Кому выдавать какую роль — подсказки в меню «🎭 Выдать роль» и список в админ-панели.
🤖 — роль выдаёт бот сам, вручную лучше не трогать. Меняй тексты как хочешь."""
import config

AUTO = "🤖 "

STATIC = {
    config.ROLE_HEAD_ADMIN: "Правая рука владельца, полные права. Только самым проверенным",
    config.ROLE_HEAD_MOD: "Старший над модераторами: кик и бан. Опытный модератор",
    config.ROLE_STAFF: "Администратор сервера — после заявки и обзвона",
    config.ROLE_MOD: "Следит за порядком — после заявки и обзвона",
    config.ROLE_CINEMA: "Подписка на кино — люди жмут сами в " + config.CH_CINEMA_AFISHA,
    config.ROLE_FAMILY_PROBATION: f"Новичок семьи, испытательный срок {config.FAMILY_PROBATION_DAYS} дн. — бот даёт "
                                  f"при принятии. Потом → {config.ROLE_FAMILY_MEMBER}",
    config.ROLE_FAMILY_MEMBER: f"Участник семьи {config.FAMILY_NAME}",
    **dict(zip((n for n, *_ in config.FAMILY_ROLES),
               (f"Глава семьи {config.FAMILY_NAME}", "Правая рука основателя семьи", "Ответственный",
                "Главный по набору в семью, следит за HR", "Рассматривает заявки в семью, ведёт новичков"))),
    **config.ROLE_DESCRIPTIONS,  # свои подсказки из настроек (role_descriptions)
}


def info(role_name: str) -> str:
    """Кому выдавать роль. Пустая строка — описания нет."""
    if role_name in STATIC:
        return STATIC[role_name]
    for gender, _, label in config.GENDERS:
        if role_name == gender:
            return AUTO + f"Пол «{label}» — человек выбирает сам в 👋・старт"
    for need, name in config.LEVEL_ROLES.items():
        if role_name == name:
            return AUTO + f"Бот сам: {need} сообщений"
    for ach in config.ACHIEVEMENTS:
        if role_name == ach["role"]:
            return AUTO + f"Достижение: {ach['desc']}"
    for game in config.GAMES:
        if role_name == game["role"]:
            return f"Играет в {game['name']} — обычно выбирают сами в 👋・старт"
        if role_name == config.admin_role_name(game["name"]):
            return f"Активный игрок {game['name']}, следит за порядком в отделе"
    return {
        config.ROLE_BIRTHDAY: AUTO + "Бот сам — в день рождения",
        config.ROLE_BASE: AUTO + "Базовая — бот выдаёт после анкеты",
        config.ROLE_PENDING: AUTO + "Новичок без анкеты — бот сам",
        config.ROLE_GIRLS_18: AUTO + "Бот сам: девочка + 18 лет по ДР. Не выдавать вручную",
        config.ROLE_BOYS_18: AUTO + "Бот сам: мальчик + 18 лет по ДР. Не выдавать вручную",
    }.get(role_name, "")


def guide_text(role_names: list[str]) -> str:
    lines = [f"**{n}** — {d}" for n in role_names if (d := info(n))]
    return "\n".join(lines)
