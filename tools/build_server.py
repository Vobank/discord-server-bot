"""Построить/достроить сервер без запуска основного бота (то же, что /setup). Запускает Мастер настройки.
  build_server.py              — создать недостающее и выложить панели
  build_server.py --check      — только показать, что будет создано (ничего не меняет)
  build_server.py --rules      — плюс перевыложить правила
  build_server.py --rules-only — только перевыложить правила"""
import os
import sys

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["BOT_HELPER"] = "1"  # не дублировать события основного бота
os.chdir(APP)
sys.path.insert(0, APP)
import discord  # noqa: E402

import bot as botmod  # noqa: E402
import utils  # noqa: E402


class SetupBot(botmod.Bot):
    async def on_ready(self):
        code = 0
        try:
            g = self.get_guild(botmod.GUILD_ID)
            if g is None:
                print("❌ Бот не видит сервер с GUILD_ID из .env — пригласи бота на сервер (Мастер → Подключение)")
                code = 1
            elif "--check" in sys.argv:
                from cogs.setup_server import missing_items
                items = missing_items(g)
                print(f"Сервер: {g.name}\n")
                print("✅ Всё уже на месте — бот только обновит панели." if not items else
                      "Бот создаст:\n" + "\n".join(f"  • {i}" for i in items))
                if not g.me.guild_permissions.administrator:
                    print("\n⚠️ У бота нет права «Администратор» — пригласи его заново по кнопке в Мастере.")
            elif "--rules-only" in sys.argv:
                from cogs.rules import post_rules
                ch = utils.rules_channel(g)
                if ch is None:
                    print("❌ Канала правил нет — сначала «Построить сервер»")
                    code = 1
                else:
                    await post_rules(self, ch)
                    print(f"✅ Правила опубликованы в #{ch.name}")
            else:
                if not g.me.guild_permissions.administrator:
                    print("❌ У бота нет права «Администратор» — пригласи его заново по кнопке в Мастере.")
                    code = 1
                else:
                    from cogs.setup_server import build_server
                    print(f"Сервер: {g.name}\n")
                    for line in await build_server(self, g):
                        print("  ✅", line, flush=True)
                    if "--rules" in sys.argv:
                        from cogs.rules import post_rules
                        if ch := utils.rules_channel(g):
                            await post_rules(self, ch)
                            print("  ✅ правила опубликованы", flush=True)
        except Exception:
            import traceback
            traceback.print_exc()
            code = 1
        sys.stdout.flush()
        os._exit(code)


discord.utils.setup_logging(level=40)
SetupBot().run(botmod.TOKEN, log_handler=None)
