#!/usr/bin/env python3
"""
Linux Debian Server Diagnostics Tool
Runs a comprehensive check of system health and outputs a report.
"""

import subprocess
import os
import sys
import datetime

# Shared metrics dict — filled during checks, used by recommendations
METRICS = {}


# ─── Helpers ───────────────────────────────────────────────────────────────────

def run(cmd: str, timeout: int = 15) -> str:
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip() or result.stderr.strip()
    except subprocess.TimeoutExpired:
        return "[timeout]"
    except Exception as e:
        return f"[error: {e}]"


def header(title: str) -> str:
    line = "─" * 62
    return f"\n{line}\n  {title}\n{line}"


def section(title: str, content: str) -> str:
    return f"{header(title)}\n{content}\n"


# ─── System ────────────────────────────────────────────────────────────────────

def check_os():
    return run("lsb_release -a 2>/dev/null || cat /etc/os-release")


def check_kernel():
    return run("uname -r") + "\n" + run("uname -a")


def check_uptime():
    return run("uptime -p") + "\n" + run("uptime")


def check_timezone():
    return run("timedatectl status 2>/dev/null || date")


# ─── CPU ───────────────────────────────────────────────────────────────────────

def check_cpu_info():
    return run("lscpu | grep -E 'Model name|CPU\\(s\\)|Thread|Core|Socket|MHz'")


def check_load_vs_cpu():
    """Load Average compared to vCPU count — key signal for CPU saturation."""
    nproc = run("nproc")
    loadavg = run("cat /proc/loadavg")
    try:
        ncpu = int(nproc.strip())
        la1, la5, la15 = [float(x) for x in loadavg.split()[:3]]
        ratio = la15 / ncpu
        if ratio >= 1.0:
            status = "CRITICAL"
        elif ratio >= 0.8:
            status = "WARN"
        else:
            status = "OK"
        METRICS["la15"] = la15
        METRICS["nproc"] = ncpu
        METRICS["la_ratio"] = ratio
        METRICS["la_status"] = status
        return (
            f"vCPU count  : {ncpu}\n"
            f"Load Average: {la1} (1m)  {la5} (5m)  {la15} (15m)\n"
            f"LA15/vCPU   : {ratio:.2f}  [{status}]"
        )
    except Exception:
        METRICS["la_status"] = "unknown"
        return f"vCPU: {nproc}\nLoad Average: {loadavg}"


def check_cpu_per_core():
    """Per-core CPU breakdown. Requires sysstat (apt install sysstat)."""
    out = run("mpstat -P ALL 1 1 2>/dev/null")
    if "mpstat" in out and "not found" in out:
        return "sysstat not installed — run: sudo apt install sysstat\nFallback:\n" + run(
            "top -b -n1 | head -20"
        )
    return out


def check_cpu_steal():
    """Steal% — if high (>5%), CPU is being throttled at hypervisor level."""
    out = run("vmstat 1 3 2>/dev/null")
    try:
        lines = [l for l in out.splitlines() if l.strip() and not l.startswith("procs")]
        if lines:
            last = lines[-1].split()
            # vmstat columns: r b swpd free buff cache si so bi bo in cs us sy id wa st
            steal = float(last[-1])
            METRICS["steal"] = steal
            note = " ← HIGH: hypervisor throttling!" if steal > 5 else ""
            return out + f"\n\nSteal%: {steal}{note}"
    except Exception:
        pass
    METRICS["steal"] = 0
    return out


def check_vmstat():
    """vmstat: run queue (r), context switches (cs), memory pressure."""
    return run("vmstat 1 3 2>/dev/null")


def check_top_processes():
    return run("ps auxww --sort=-%cpu | head -16")


def check_iostat():
    """Extended disk I/O stats. Requires sysstat."""
    out = run("iostat -x 1 1 2>/dev/null")
    if not out or "not found" in out:
        return "sysstat not installed — run: sudo apt install sysstat"
    return out


# ─── Memory ────────────────────────────────────────────────────────────────────

def check_memory():
    out = run("free -h")
    # Track used% for recommendations
    try:
        raw = run("free -m")
        for line in raw.splitlines():
            if line.startswith("Mem:"):
                parts = line.split()
                total, used = int(parts[1]), int(parts[2])
                METRICS["ram_used_pct"] = round(used / total * 100, 1)
                break
    except Exception:
        pass
    return out


def check_swap():
    return run("swapon --show") or "No swap configured"


# ─── Disk ──────────────────────────────────────────────────────────────────────

def check_disk_overview():
    """Disk usage per filesystem. Tracks critical partitions."""
    out = run("df -hT | grep -v tmpfs | grep -v udev")
    # Find partitions >85%
    critical = []
    warn = []
    try:
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 6:
                pct_str = parts[-2].replace("%", "")
                mount = parts[-1]
                pct = int(pct_str)
                if pct >= 95:
                    critical.append((mount, pct))
                elif pct >= 85:
                    warn.append((mount, pct))
        METRICS["disk_critical"] = critical
        METRICS["disk_warn"] = warn
    except Exception:
        pass
    return out


def check_disk_var_detail():
    """Breakdown of /var subdirectories — key for diagnosing disk fill."""
    return run("du -xhd1 /var 2>/dev/null | sort -h")


def check_disk_var_log_detail():
    """Breakdown of /var/log — most common source of disk fill."""
    return run("du -xhd1 /var/log 2>/dev/null | sort -h")


def check_disk_var_lib_detail():
    """Breakdown of /var/lib — Docker overlay2 often hides here."""
    return run("du -xhd1 /var/lib 2>/dev/null | sort -h")


def check_disk_var_cache_detail():
    """Breakdown of /var/cache — apt cache can grow to 1GB+."""
    return run("du -xhd1 /var/cache 2>/dev/null | sort -h")


def check_large_files():
    """Files >100MB in /var — catches bloated logs, docker layers, jars."""
    return run(
        "find /var -xdev -type f -size +100M -printf '%s\\t%TY-%Tm-%Td\\t%p\\n' "
        "2>/dev/null | sort -nr | head -20"
    ) or "No files >100MB found in /var"


def check_deleted_held_files():
    """Files deleted but still held open by processes — du vs df gap."""
    out = run("lsof +L1 2>/dev/null | grep -E '/var|/log' | head -20")
    METRICS["deleted_held"] = bool(out and "COMMAND" not in out and len(out) > 10)
    return out or "No deleted-but-held files found"


def check_inode():
    """Inode usage — can reach 100% with many small files even if space is free."""
    out = run("df -i | grep -v tmpfs | grep -v udev")
    try:
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 6:
                pct_str = parts[-2].replace("%", "")
                mount = parts[-1]
                pct = int(pct_str)
                if pct >= 80:
                    METRICS.setdefault("inode_warn", []).append((mount, pct))
    except Exception:
        pass
    return out


def check_lvm():
    """LVM volume group info — shows if lvextend is possible."""
    vgs = run("vgs 2>/dev/null")
    lvs = run("lvs 2>/dev/null")
    if not vgs or "not found" in vgs:
        return "LVM not detected or not accessible"
    return f"--- Volume Groups ---\n{vgs}\n\n--- Logical Volumes ---\n{lvs}"


# ─── Docker ────────────────────────────────────────────────────────────────────

def check_docker_containers():
    if not run("which docker").strip() or "not found" in run("which docker"):
        return "Docker not installed"
    out = run("docker ps -a --format 'table {{.Names}}\\t{{.Status}}\\t{{.Image}}' 2>/dev/null")
    return out or "No containers found"


def check_docker_stats():
    """Real-time CPU/RAM/IO per container — key for CPU incident triage."""
    if not run("which docker").strip() or "not found" in run("which docker"):
        return "Docker not installed"
    return run(
        "docker stats --no-stream "
        "--format 'table {{.Name}}\\t{{.CPUPerc}}\\t{{.MemUsage}}\\t{{.BlockIO}}' 2>/dev/null"
    ) or "No running containers"


def check_docker_disk():
    """Docker disk usage: images, containers, volumes, build cache."""
    if not run("which docker").strip() or "not found" in run("which docker"):
        return "Docker not installed"
    out = run("docker system df 2>/dev/null")
    # Try to parse reclaimable
    METRICS["docker_installed"] = True
    return out or "Could not get docker system df"


def check_docker_log_sizes():
    """Size of JSON log files per container — common /var fill source."""
    out = run(
        "find /var/lib/docker/containers -name '*-json.log' "
        "-printf '%s\\t%p\\n' 2>/dev/null | sort -nr | head -15"
    )
    return out or "No container log files found (or no access)"


# ─── Journals & Logs ───────────────────────────────────────────────────────────

def check_journal_disk():
    """systemd journal disk usage — vacuum if >1GB."""
    out = run("journalctl --disk-usage 2>/dev/null")
    try:
        # Extract size
        import re
        m = re.search(r"([\d.]+)\s*(G|M|K)", out)
        if m:
            val, unit = float(m.group(1)), m.group(2)
            mb = val * 1024 if unit == "G" else (val if unit == "M" else val / 1024)
            METRICS["journal_mb"] = mb
    except Exception:
        pass
    return out or "Could not get journal disk usage (try with sudo)"


def check_atop_logs():
    """atop log retention — can grow to 1GB+ per month."""
    return run("du -sh /var/log/atop 2>/dev/null") or "/var/log/atop not found"


# ─── Network ───────────────────────────────────────────────────────────────────

def check_network():
    interfaces = run("ip -brief addr show")
    connections = run("ss -tulnp")
    return f"--- Interfaces ---\n{interfaces}\n\n--- Listening ports ---\n{connections}"


def check_firewall():
    ufw = run("ufw status 2>/dev/null")
    if "inactive" in ufw or "active" in ufw:
        return f"UFW:\n{ufw}"
    iptables = run("iptables -L -n --line-numbers 2>/dev/null | head -30")
    return f"iptables (UFW not found):\n{iptables}"


# ─── Services ──────────────────────────────────────────────────────────────────

def check_services():
    return run("systemctl list-units --type=service --state=running --no-pager | head -30")


def check_failed_services():
    out = run("systemctl --failed --no-pager")
    METRICS["failed_services"] = "0 loaded" not in out and bool(out)
    return out


# ─── Security ──────────────────────────────────────────────────────────────────

def check_last_logins():
    return run("last -n 10")


def check_auth_log():
    log = run("tail -n 20 /var/log/auth.log 2>/dev/null || tail -n 20 /var/log/secure 2>/dev/null")
    return log or "Auth log not accessible (try with sudo)"


# ─── Updates ───────────────────────────────────────────────────────────────────

def check_updates():
    return run("apt list --upgradable 2>/dev/null | head -20")


# ─── Report ────────────────────────────────────────────────────────────────────

def build_report() -> str:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hostname = run("hostname")

    lines = [
        "=" * 64,
        "  DEBIAN SERVER DIAGNOSTICS REPORT",
        f"  Host : {hostname}",
        f"  Date : {now}",
        "=" * 64,
    ]

    checks = [
        # System
        ("OS / Distribution",               check_os),
        ("Kernel",                           check_kernel),
        ("Uptime",                           check_uptime),
        ("Timezone",                         check_timezone),

        # CPU
        ("CPU Info",                         check_cpu_info),
        ("Load Average vs vCPU",             check_load_vs_cpu),
        ("CPU Per-Core (mpstat)",            check_cpu_per_core),
        ("CPU Steal % (vmstat)",             check_cpu_steal),
        ("vmstat — Run Queue & Memory",      check_vmstat),
        ("Top Processes by CPU",             check_top_processes),
        ("Disk I/O Stats (iostat)",          check_iostat),

        # Memory
        ("Memory (free -h)",                 check_memory),
        ("Swap",                             check_swap),

        # Disk — overview
        ("Disk Usage Overview (df)",         check_disk_overview),
        ("Inode Usage",                      check_inode),
        ("LVM — Volume Groups & LVs",        check_lvm),

        # Disk — /var deep dive
        ("/var Directory Breakdown",         check_disk_var_detail),
        ("/var/log Breakdown",               check_disk_var_log_detail),
        ("/var/lib Breakdown",               check_disk_var_lib_detail),
        ("/var/cache Breakdown",             check_disk_var_cache_detail),
        ("Large Files in /var (>100MB)",     check_large_files),
        ("Deleted Files Held by Processes",  check_deleted_held_files),

        # Docker
        ("Docker Containers",                check_docker_containers),
        ("Docker Resource Usage (live)",     check_docker_stats),
        ("Docker Disk Usage (system df)",    check_docker_disk),
        ("Docker Container Log Sizes",       check_docker_log_sizes),

        # Journals & Logs
        ("systemd Journal Disk Usage",       check_journal_disk),
        ("atop Log Size",                    check_atop_logs),

        # Network & Security
        ("Network Interfaces & Ports",       check_network),
        ("Firewall",                         check_firewall),
        ("Running Services",                 check_services),
        ("Failed Services",                  check_failed_services),
        ("Last Logins",                      check_last_logins),
        ("Auth Log (last 20 lines)",         check_auth_log),

        # Updates
        ("Pending apt Updates",              check_updates),
    ]

    for title, func in checks:
        print(f"  Checking: {title}...", flush=True)
        lines.append(section(title, func()))

    return "\n".join(lines)


def main():
    if sys.platform.startswith("win"):
        print("[!] This script is designed for Linux (Debian). Exiting.")
        sys.exit(1)

    print("\n[*] Starting server diagnostics...\n")
    report = build_report()

    # Generate recommendations based on collected metrics
    try:
        from recommendations import generate_recommendations
        recs = generate_recommendations(METRICS)
        if recs:
            rec_lines = ["\n" + "=" * 64, "  RECOMMENDATIONS", "=" * 64]
            for rec in recs:
                rec_lines.append(f"\n[{rec['level']}] {rec['title']}")
                rec_lines.append(f"  Problem : {rec['problem']}")
                rec_lines.append(f"  Commands: ")
                for cmd in rec["commands"]:
                    rec_lines.append(f"    {cmd}")
            report += "\n" + "\n".join(rec_lines)
    except ImportError:
        pass

    print("\n" + report)

    filename = f"report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\n[✓] Report saved to: {os.path.abspath(filename)}\n")


if __name__ == "__main__":
    main()
