#!/bin/bash
# check_deps.sh — проверяет наличие всех зависимостей для diagnostics.py
# Использование: bash check_deps.sh

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

MISSING_REQUIRED=()
MISSING_OPTIONAL=()

check() {
    local bin="$1"
    local pkg="$2"
    local required="$3"  # "required" or "optional"

    if command -v "$bin" &>/dev/null; then
        echo -e "  ${GREEN}[OK]${NC}  $bin"
    else
        if [ "$required" = "required" ]; then
            echo -e "  ${RED}[MISS]${NC} $bin  (пакет: $pkg)"
            MISSING_REQUIRED+=("$pkg")
        else
            echo -e "  ${YELLOW}[OPT]${NC}  $bin  (пакет: $pkg) — часть проверок будет пропущена"
            MISSING_OPTIONAL+=("$pkg")
        fi
    fi
}

echo ""
echo "================================================="
echo "  Проверка зависимостей для diagnostics.py"
echo "================================================="

echo ""
echo "── Обязательные зависимости ─────────────────────"

check python3      python3          required
check uname        coreutils        required
check uptime       procps           required
check lscpu        util-linux       required
check nproc        coreutils        required
check free         procps           required
check swapon       util-linux       required
check df           coreutils        required
check du           coreutils        required
check find         findutils        required
check ps           procps           required
check vmstat       procps           required
check ip           iproute2         required
check ss           iproute2         required
check hostname     hostname         required
check systemctl    systemd          required
check journalctl   systemd          required
check last         util-linux       required
check lsb_release  lsb-release      required
check apt          apt              required

echo ""
echo "── Опциональные зависимости ─────────────────────"
echo "   (скрипт запустится без них, но часть проверок"
echo "    будет пропущена или заменена на аналог)"
echo ""

check mpstat    sysstat   optional   # CPU per-core, нужен для check_cpu_per_core
check iostat    sysstat   optional   # disk I/O stats, нужен для check_iostat
check lsof      lsof      optional   # удалённые-но-открытые файлы
check vgs       lvm2      optional   # LVM volume groups
check lvs       lvm2      optional   # LVM logical volumes
check docker    docker.io optional   # все docker-проверки
check ufw       ufw       optional   # firewall (fallback на iptables)
check iptables  iptables  optional   # firewall fallback
check atop      atop      optional   # проверка размера atop-логов

echo ""
echo "================================================="

# ─── Итог ──────────────────────────────────────────

if [ ${#MISSING_REQUIRED[@]} -eq 0 ] && [ ${#MISSING_OPTIONAL[@]} -eq 0 ]; then
    echo -e "  ${GREEN}Все зависимости установлены. Можно запускать!${NC}"
    echo ""
    exit 0
fi

if [ ${#MISSING_REQUIRED[@]} -gt 0 ]; then
    echo ""
    echo -e "  ${RED}Не установлены обязательные пакеты:${NC}"
    echo ""
    # Убираем дубли
    UNIQUE_REQUIRED=($(echo "${MISSING_REQUIRED[@]}" | tr ' ' '\n' | sort -u))
    echo "  sudo apt-get update && sudo apt-get install -y ${UNIQUE_REQUIRED[*]}"
    echo ""
fi

if [ ${#MISSING_OPTIONAL[@]} -gt 0 ]; then
    echo -e "  ${YELLOW}Рекомендуется установить опциональные пакеты:${NC}"
    echo ""
    UNIQUE_OPTIONAL=($(echo "${MISSING_OPTIONAL[@]}" | tr ' ' '\n' | sort -u))
    echo "  sudo apt-get install -y ${UNIQUE_OPTIONAL[*]}"
    echo ""
fi

echo "  После установки запустите скрипт повторно:"
echo "  sudo python3 diagnostics.py"
echo ""

# Выход с ошибкой только если есть обязательные
[ ${#MISSING_REQUIRED[@]} -gt 0 ] && exit 1 || exit 0
