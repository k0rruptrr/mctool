# 🎮 Менеджер Minecraft Сервера (mctool)

Однофайловый Python TUI для установки и управления Minecraft серверами.

**Без зависимостей** — работает сразу после `git clone && ./mctool.py`

![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)
![Platform: Linux](https://img.shields.io/badge/platform-Linux-lightgrey.svg)

## Возможности

- 📦 **Установка** — Vanilla или **Paper** сервер с выбором версии
- ▶️ **Запуск/Остановка** — Управление через screen с корректным завершением
- 📊 **Статус** — Состояние сервера, версия, RAM в реальном времени
- 🖥️ **Консоль** — Интерактивный просмотр логов + отправка команд
- 💬 **Команды** — История команд с быстрым доступом
- 🔄 **Смена версии** — С автоматическим бэкапом перед сменой
- 💾 **Бэкапы** — Архивы миров с временными метками и автоочисткой
- ⚙️ **Настройки** — RAM, пути, количество бэкапов

## Быстрый старт

```bash
git clone https://github.com/youruser/phantom_mc.git
cd phantom_mc
chmod +x mctool.py
./mctool.py
```

## Требования

- **Linux** (curses встроен в Python на Linux)
- **Python 3.8+**
- **screen** — `sudo apt install screen`
- **Java 21** — `sudo apt install openjdk-21-jre-headless`

> При запуске mctool автоматически проверит наличие зависимостей

## Использование

### TUI режим
```bash
./mctool.py
```
Стрелки для навигации, Enter для выбора, Q для возврата.

### Интерактивная консоль
```
┌───────────── Server Console ─────────────┐
│ ● LIVE                 [A]uto-scroll: ON │
├──────────────────────────────────────────┤
│ [02:07:32] Player joined the game        │
│ [02:07:35] <Player> hello                │
├──────────────────────────────────────────┤
│ > say hello world_                       │
└──────────────────────────────────────────┘
```
- **Enter** — отправить команду
- **↑↓** — история команд
- **Page Up/Down** — скролл логов
- **Esc** — выход

### CLI режим
```bash
./mctool.py --start      # Запустить сервер
./mctool.py --stop       # Остановить (graceful)
./mctool.py --status     # Статус в JSON
./mctool.py --backup     # Создать бэкап
./mctool.py -c "say hi"  # Отправить команду
```

## Типы серверов

| Тип | Описание |
|-----|----------|
| **Vanilla** | Официальный сервер от Mojang |
| **Paper** | Оптимизированный форк с поддержкой плагинов |

## Конфигурация

Настройки хранятся в `~/minecraft/.mctool.json`:
```json
{
  "server_dir": "/home/user/minecraft",
  "ram_gb": 16,
  "current_version": "1.21.4",
  "server_type": "paper",
  "auto_backup": true,
  "max_backups": 5
}
```

## Тестирование

```bash
python -m unittest test_mctool -v
```

## Лицензия

MIT
