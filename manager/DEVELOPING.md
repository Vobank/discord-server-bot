# Панель управления: как устроена и как писать разделы

Программа — `manager.pyw` (пакет `manager/`). Одно окно: меню слева, раздел справа, внизу появляется полоса
«Есть несохранённые изменения → Отменить / Сохранить».

```
manager/
  app.py        окно, меню, уведомления, диалоги, фоновые задачи, сохранение
  theme.py      палитры, шрифты (Inter из assets/fonts), иконки Segoe Fluent Icons, стили ttk (sv_ttk)
  widgets.py    компоненты: Group/Row/Expander, Switch, Entry, Combo, Spin, ColorButton, ListEditor, InfoBar…
  state.py      данные без интерфейса: Store (черновик), .env, host.json, статус бота, команды, Discord API
  devtools.py   проверка и снимки разделов (всегда в песочнице)
  pages/
    __init__.py список разделов (ключ, название, иконка, группа, модуль)
    base.py     класс Page и привязки bind_*
    <модуль>.py раздел: класс View(Page)
```

## Раздел

```python
from .. import state
from .. import widgets as W
from ..theme import C, px
from .base import Page


class View(Page):
    description = "Одно предложение: что здесь настраивается."

    def build(self):
        W.section(self.body, "Подзаголовок", "Необязательное пояснение.")
        g = W.Group(self.body)                       # карточка со строками
        row = g.row("Название", "Пояснение мелким текстом.", "globe")   # иконка — имя из theme.ICONS
        self.bind_entry(row.right, "s:bot.server_name", 28).pack(side="left")
        row = g.row("Включено", icon="power")
        self.bind_switch(row.right, "s:modules.music").pack(side="left")

    def on_show(self):            # раздел открыли
        ...

    def on_status(self, status):  # раз в 2 с: dict из runtime/status.json или None (бот на этом ПК не запущен)
        ...
```

Название, иконка и место в меню задаются в `pages/__init__.py`, не в классе.

## Черновик и пути

Всё, что меняет настройки, пишет в черновик через `self.set(путь, значение)` или привязки `bind_*`.
Пользователь видит «Сохранить / Отменить»; запись в файлы — только по «Сохранить».

| Префикс | Где хранится | Пример |
|---|---|---|
| `s:` | settings.json (поверх settings.example.json) | `s:bot.name`, `s:channels.main.id`, `s:games` |
| `e:` | .env | `e:DISCORD_TOKEN`, `e:VK_TOKEN` |
| `h:` | host.json (этот ПК) | `h:name`, `h:priority`, `h:mode` |
| `r:` | rules.json | `r:intro`, `r:sections` |
| `x:` | особые операции | `x:banner` = `keep` / `remove` / путь к картинке |

`self.get(путь, default)` — значение из черновика, `self.saved(путь)` — сохранённое.
**Один путь привязывается ровно в одном разделе** (иначе два контрола разойдутся).
Списки и словари меняются целиком: `items = self.get("s:games", []); items.append(...); self.set("s:games", items)`.

Привязки (`pages/base.py`):

- `bind_entry(parent, path, width, kind="str"|"int"|"float"|"id"|"list", placeholder=, secret=, strip=, minimum=, maximum=)`
  - `id` — ID Discord: цифры (15–21) или пусто → `None`;
  - `list` — через запятую → список строк;
  - неверное значение подсвечивается и в черновик не попадает.
- `bind_switch(parent, path, on_toggle=None)` — «Вкл./Откл.» справа в строке.
- `bind_combo(parent, path, [(значение, подпись), …], width)`.
- `bind_spin(parent, path, frm, to, step, width)`.
- `bind_color(parent, path)`.
- `bind_text(parent, path, height, width, lines=False)` — многострочный; `lines=True` → список строк.

Для таблиц — `W.ListEditor(parent, page, path, columns, fields, to_row, to_form, from_form, new, noun=…)`:
таблица + «Добавить / Изменить / Удалить / ↑ / ↓», форма — `W.FormDialog` (поля: `text`, `int`, `float`, `secret`,
`color`, `bool`, `choice`, `multiline`). Пример — раздел «Игры и отделы».

## Компоненты (`widgets.py`)

- Раскладка:
  - `W.section(parent, title, description)` — подзаголовок группы;
  - `W.Group(parent)` → `.row(title, description, icon)` / `.block()` (произвольное содержимое);
  - `W.Expander(parent, title, description, icon, expanded)` → `.right` (переключатель в заголовке), `.row(...)`, `.block()`;
  - `W.Card(parent)` → `.content`;
  - `W.spacer(parent, h)`.
- Текст:
  - `W.label(parent, text, role, color, wrap)`;
  - роли шрифта: `caption`, `small`, `body`, `strong`, `body_large`, `subtitle`, `title`, `mono`;
  - цвета: `text`, `text2`, `text3`, `accent`, `success`, `warning`, `error`.
- Кнопки:
  - `W.button(parent, text, command, kind="default"|"accent", icon=None, tooltip=None)` — одна акцентная кнопка на группу, не больше;
  - `W.IconButton(parent, icon, command, tooltip)`;
  - `W.LinkButton(parent, text, command)`.
- Состояние:
  - `W.Dot(parent, color)`;
  - `W.Pill(parent, text, kind)` — `success`/`warning`/`error`/`info`/`neutral`;
  - `W.Meter(parent, width)` → `.set(0..100)`;
  - `W.InfoBar(parent, kind, title, message, actions, closable)`.
- Поля:
  - `W.Entry`, `W.Switch`, `W.Combo`, `W.Spin`, `W.ColorButton`;
  - `W.Table(parent, columns, height)` → `.set_rows(rows)`, `.selected()`.

Контролы сами подбирают стиль под фон (страница, карточка, вложенный блок раскрывающегося блока).
Отступы — только `px(…)` (масштаб экрана бывает 100–250 %). Цвета — только `C("…")`, без шестнадцатеричных
значений в разделах.

## Окно (`self.app`)

- Уведомления и диалоги:
  - `notify(kind, title, message="", actions=[(текст, функция)], timeout=мс)` — полоса уведомления над разделом;
  - `confirm(title, message, ok="Продолжить", danger=False) -> bool`, `message(title, text)`;
  - `prompt(title, label, initial="") -> str|None`, `form(title, fields, values) -> dict|None`.
- Задачи:
  - `run_task(title, state.tool_args("build_server.py", "--check"), description, on_done)` — команда с живым журналом;
  - `background(fn, on_done)` — `fn()` в отдельном потоке, `on_done(result, error)` — в окне.
    **Из потока к виджетам не обращаться.**
- Сохранение:
  - `ensure_saved(текст) -> bool` — перед командами, которые читают файлы (построить сервер, собрать установщик);
  - `save()`, `discard()`, `apply_changes()` (перезапуск бота и рассылка настроек на другие ПК).
- Состояние:
  - `goto(ключ)`, `status` (последний статус), `store`, `prefs` (параметры программы этого ПК, словарь);
  - `discord_info` (результат проверки ключа или нет атрибута).

`state.py`: `read_status()`, `sync_enabled()`, `send_command("restart_bot"|"backup"|"check_update"|"stop"|"take_here"|"unpin")`,
`start_supervisor()`, `publish_update(note)`, `tool_args(script, *args)`, `open_path`, `open_url`, `tail(path, n)`,
`list_backups()`, `autostart_enabled()`, `set_autostart(on, name)`, `ensure_shortcut(name)`, `check_token(token)`,
`invite_url(app_id)`, `LOGS`, `APP`, `local_version()`.

## Проверка

```
.venv\Scripts\python -m manager.devtools check <ключ>            # собрать раздел со всеми статусами бота и в обеих темах
.venv\Scripts\python -m manager.devtools snap <ключ> --theme dark --pages 3   # снимки (runtime/sandbox/snaps)
```

devtools всегда работает в песочнице (`MANAGER_SANDBOX=1`): команды боту, внешние программы, ярлыки и запись
файлов не выполняются. Настоящий `manager.pyw` и скрипты из `tools/` во время разработки не запускать —
на этом ПК работает настоящий бот.

Правки файлов — инструментами Write/Edit, не heredoc в bash: оболочка портит обратные слэши (`\n`, ``).

## Стиль (обязательно)

Программа должна выглядеть как продукт, сделанный дизайнером, а не сгенерированный.

- Никаких эмодзи в интерфейсе. Иконки — только `theme.ICONS` (Segoe Fluent Icons).
- Тексты:
  - короткие, спокойные, на «вы»: без восклицательных знаков, без «Отлично!», «Супер», «✨», «🚀»;
  - заглавная буква только в начале: «Пересылка новостей», а не «Пересылка Новостей»;
  - название строки — существительное или короткое действие: «Ключ бота», «Запускать вместе с Windows»;
  - описание — одно предложение, что это и зачем, без повторов названия;
  - кнопки — глаголы: «Сохранить», «Проверить», «Открыть папку». Не «Нажмите здесь».
  - Термины всюду одинаковые: «бот», «сервер», «канал», «роль», «компьютер» (в коротких местах «ПК»),
    «ключ бота» (не «токен» в заголовках; «токен» можно в пояснении), «функции» (модули бота).
  - Числа с единицами: «10 мин», «2 дн.», «300 сообщений».
- Одна акцентная кнопка на группу — главное действие. Опасные действия (остановить бота, удалить) — с подтверждением.
- Пустые состояния не оставлять пустыми: «Пока нет резервных копий. Они появятся после первого запуска бота».
- Ошибки — человеческим языком и с выходом: что случилось и что сделать.
