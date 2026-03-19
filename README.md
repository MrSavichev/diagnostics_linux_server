# diagnostics_linux_server

Инструмент диагностики сервера Linux Debian. Собирает данные о состоянии системы, сохраняет отчёт в файл и выдаёт **рекомендации по устранению проблем** на основе найденных метрик.

## Файлы

| Файл | Назначение |
|------|-----------|
| `diagnostics.py` | Главный скрипт. Собирает метрики и формирует отчёт |
| `recommendations.py` | Движок рекомендаций. Анализирует метрики, выдаёт приоритизированные действия |
| `check_deps.sh` | Проверяет наличие всех зависимостей перед запуском |

---

## Зависимости

### Шаг 0 — проверить всё одной командой

```bash
bash check_deps.sh
```

Скрипт покажет что установлено, что отсутствует и выдаст готовую команду установки.

---

### Обязательные зависимости

Без них скрипт не запустится или не выдаст полезных данных.

| Утилита | Пакет | Зачем |
|---------|-------|-------|
| `python3` | `python3` | запуск скрипта |
| `ps`, `free`, `vmstat`, `uptime` | `procps` | процессы, память, нагрузка |
| `df`, `du`, `find`, `nproc` | `coreutils`, `findutils` | диск, файлы |
| `lscpu`, `swapon` | `util-linux` | CPU и swap |
| `ip`, `ss` | `iproute2` | сеть |
| `systemctl`, `journalctl` | `systemd` | сервисы и журналы |
| `last` | `util-linux` | последние входы |
| `lsb_release` | `lsb-release` | версия ОС |
| `apt` | `apt` | список обновлений |

**Установка (если что-то отсутствует):**
```bash
sudo apt-get update && sudo apt-get install -y \
  python3 procps coreutils findutils util-linux \
  iproute2 systemd lsb-release apt
```

> На большинстве систем Debian/Ubuntu всё это установлено по умолчанию.
> Если отсутствует `python3` — установите его первым: `sudo apt-get install -y python3`

---

### Опциональные зависимости

Скрипт запустится без них, но часть проверок будет пропущена или заменена на упрощённый аналог.

| Утилита | Пакет | Какая проверка | Что будет без неё |
|---------|-------|---------------|-------------------|
| `mpstat` | `sysstat` | CPU per-core breakdown | заменяется на `top -b -n1` |
| `iostat` | `sysstat` | расширенная disk I/O статистика | пропускается |
| `lsof` | `lsof` | удалённые-но-открытые файлы (du vs df) | пропускается |
| `vgs`, `lvs` | `lvm2` | информация об LVM разделах | пропускается |
| `docker` | `docker.io` / `docker-ce` | все docker-проверки | пропускается |
| `ufw` | `ufw` | firewall | fallback на iptables |
| `iptables` | `iptables` | firewall (fallback) | пропускается |
| `atop` | `atop` | размер atop-логов | пропускается |

**Рекомендуемая установка опциональных пакетов:**
```bash
sudo apt-get install -y sysstat lsof lvm2
```

---

## Что проверяет

### Система
| Категория | Что именно |
|-----------|-----------|
| **ОС / Ядро** | Дистрибутив, версия ядра, аптайм, таймзона |
| **CPU** | Модель, число ядер, load average **vs nproc** (ключевой сигнал перегрузки) |
| **CPU per-core** | Разбивка по ядрам через `mpstat` |
| **Steal%** | Троттлинг на уровне гипервизора (vmstat) |
| **vmstat** | Run queue, context switches, memory pressure |
| **Top процессы** | Топ-15 по CPU |
| **iostat** | Расширенная статистика дисковых операций |
| **RAM / Swap** | Использование памяти и swap |

### Диск — многоуровневый анализ
| Проверка | Зачем |
|----------|-------|
| `df -hT` | Общий обзор, флаг >85% и >95% |
| Inode usage | Диск может быть "полным" без нехватки байт |
| LVM (vgs/lvs) | Можно ли расширить раздел без downtime |
| `/var` breakdown | Первый шаг при заполнении /var |
| `/var/log` breakdown | Типичный источник: journal, atop, docker logs |
| `/var/lib` breakdown | Docker overlay2 часто скрыт здесь |
| `/var/cache` breakdown | apt cache до 1 ГБ+ |
| Файлы >100MB | Быстрый поиск «жирных» файлов |
| Deleted-but-held files | Объясняет расхождение du vs df (требует `lsof`) |

### Docker
| Проверка | Зачем |
|----------|-------|
| `docker ps -a` | Список контейнеров и статус |
| `docker stats` | Живое CPU/RAM/IO по контейнеру |
| `docker system df` | Сколько занимают образы, тома, build cache |
| Container JSON logs | Часто растут без ротации |

### Логи и журналы
- systemd journal disk usage — вакуум при >1ГБ
- atop log size — хранит ежедневные снимки

### Сеть и безопасность
- Сетевые интерфейсы, слушающие порты
- UFW / iptables
- Запущенные и упавшие systemd-сервисы
- Последние входы, auth.log

---

## Рекомендации

После сбора данных `recommendations.py` автоматически анализирует метрики и выдаёт приоритизированные рекомендации:

| Уровень | Когда |
|---------|-------|
| `CRITICAL` | LA15/vCPU ≥ 1.0, диск ≥ 95%, RAM ≥ 95%, steal% > 10 |
| `WARN` | LA15/vCPU 0.8–1.0, диск 85–95%, journal > 2ГБ, failed-сервисы, deleted-held файлы |
| `INFO` | Советы по Docker cleanup и профилактике |

Каждая рекомендация содержит:
- **Problem** — что именно обнаружено
- **Commands** — готовые команды для устранения

---

## Установка и запуск

```bash
# 1. Клонировать репозиторий
git clone https://github.com/MrSavichev/diagnostics_linux_server.git
cd diagnostics_linux_server

# 2. Проверить зависимости
bash check_deps.sh

# 3. Установить недостающее (команда будет выведена check_deps.sh)
sudo apt-get install -y python3 sysstat lsof lvm2

# 4. Запустить диагностику
sudo python3 diagnostics.py
```

### Другие варианты запуска

```bash
# Без sudo (часть проверок будет недоступна)
python3 diagnostics.py

# Только проверить рекомендации на тестовых данных
python3 recommendations.py
```

---

## Вывод

1. Прогресс проверок в консоль
2. Полный отчёт с метриками
3. Блок рекомендаций (CRITICAL → WARN → INFO)
4. Файл `report_YYYYMMDD_HHMMSS.txt` в текущей директории

---

## Лицензия

MIT
