#!/usr/bin/env python3
"""
Linux Debian Server Diagnostics Tool
Runs a comprehensive check of system health and outputs a report.
"""

import subprocess
import os
import sys
import datetime


# ─── Helpers ───────────────────────────────────────────────────────────────────

def run(cmd: str) -> str:
    """Execute a shell command and return stdout. Returns error message on failure."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=15
        )
        return result.stdout.strip() or result.stderr.strip()
    except subprocess.TimeoutExpired:
        return "[timeout]"
    except Exception as e:
        return f"[error: {e}]"


def header(title: str) -> str:
    line = "─" * 60
    return f"\n{line}\n  {title}\n{line}"


def section(title: str, content: str) -> str:
    return f"{header(title)}\n{content}\n"


# ─── Diagnostic checks ─────────────────────────────────────────────────────────

def check_os():
    return run("lsb_release -a 2>/dev/null || cat /etc/os-release")


def check_uptime():
    return run("uptime -p") + "\n" + run("uptime")


def check_cpu():
    return run("lscpu | grep -E 'Model name|CPU\(s\)|Thread|Core|Socket|MHz'")


def check_memory():
    return run("free -h")


def check_disk():
    return run("df -hT | grep -v tmpfs | grep -v udev")


def check_load():
    return run("cat /proc/loadavg")


def check_top_processes():
    return run("ps aux --sort=-%cpu | head -11")


def check_network():
    interfaces = run("ip -brief addr show")
    connections = run("ss -tulnp")
    return f"--- Interfaces ---\n{interfaces}\n\n--- Listening ports ---\n{connections}"


def check_firewall():
    ufw = run("ufw status 2>/dev/null")
    if "inactive" in ufw or "active" in ufw:
        return f"UFW:\n{ufw}"
    iptables = run("iptables -L -n --line-numbers 2>/dev/null | head -30")
    return f"iptables (ufw not found):\n{iptables}"


def check_services():
    return run("systemctl list-units --type=service --state=running --no-pager | head -30")


def check_failed_services():
    return run("systemctl --failed --no-pager")


def check_last_logins():
    return run("last -n 10")


def check_auth_log():
    """Last 20 lines of auth log (failed SSH attempts, sudo, etc.)"""
    log = run("tail -n 20 /var/log/auth.log 2>/dev/null || tail -n 20 /var/log/secure 2>/dev/null")
    return log or "Auth log not accessible (try with sudo)"


def check_syslog():
    return run("tail -n 20 /var/log/syslog 2>/dev/null") or "Not accessible"


def check_updates():
    return run("apt list --upgradable 2>/dev/null | head -20")


def check_docker():
    if run("which docker") and "not found" not in run("which docker"):
        containers = run("docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}' 2>/dev/null")
        return containers or "Docker installed but no containers found"
    return "Docker not installed"


def check_swap():
    return run("swapon --show") or "No swap configured"


def check_timezone():
    return run("timedatectl status 2>/dev/null || date")


def check_kernel():
    return run("uname -r") + "\n" + run("uname -a")


# ─── Report ────────────────────────────────────────────────────────────────────

def build_report() -> str:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hostname = run("hostname")

    lines = [
        "=" * 62,
        f"  DEBIAN SERVER DIAGNOSTICS REPORT",
        f"  Host    : {hostname}",
        f"  Date    : {now}",
        "=" * 62,
    ]

    checks = [
        ("OS / Distribution",         check_os),
        ("Kernel",                     check_kernel),
        ("Uptime",                     check_uptime),
        ("CPU",                        check_cpu),
        ("Memory",                     check_memory),
        ("Swap",                       check_swap),
        ("Disk Usage",                 check_disk),
        ("System Load",                check_load),
        ("Timezone",                   check_timezone),
        ("Top Processes (by CPU)",     check_top_processes),
        ("Network Interfaces & Ports", check_network),
        ("Firewall",                   check_firewall),
        ("Running Services",           check_services),
        ("Failed Services",            check_failed_services),
        ("Last Logins",                check_last_logins),
        ("Auth Log (last 20 lines)",   check_auth_log),
        ("Syslog (last 20 lines)",     check_syslog),
        ("Pending Updates",            check_updates),
        ("Docker Containers",          check_docker),
    ]

    for title, func in checks:
        print(f"  Checking: {title}...", flush=True)
        lines.append(section(title, func()))

    lines.append("\n" + "=" * 62)
    lines.append("  Diagnostics complete.")
    lines.append("=" * 62)

    return "\n".join(lines)


# ─── Entry point ───────────────────────────────────────────────────────────────

def main():
    # Check platform
    if sys.platform.startswith("win"):
        print("[!] This script is designed for Linux (Debian). Exiting.")
        sys.exit(1)

    print("\n[*] Starting server diagnostics...\n")
    report = build_report()

    # Print to console
    print("\n" + report)

    # Save to file
    filename = f"report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\n[✓] Report saved to: {os.path.abspath(filename)}\n")


if __name__ == "__main__":
    main()
