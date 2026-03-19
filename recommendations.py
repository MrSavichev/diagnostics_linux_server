#!/usr/bin/env python3
"""
Recommendations engine for diagnostics.py.
Analyzes collected metrics and returns prioritized action items.

Usage:
    Called automatically by diagnostics.py at the end of the report.
    Can also be run standalone to test logic:
        python3 recommendations.py
"""

from typing import Any


def generate_recommendations(metrics: dict[str, Any]) -> list[dict]:
    """
    Accepts the METRICS dict filled by diagnostics.py.
    Returns a list of recommendations sorted by severity: CRITICAL → WARN → INFO.
    Each item: {level, title, problem, commands: [...]}
    """
    recs = []

    # ── CPU: Load Average saturation ─────────────────────────────────────────
    la_status = metrics.get("la_status", "unknown")
    la15 = metrics.get("la15", 0)
    nproc = metrics.get("nproc", 1)
    la_ratio = metrics.get("la_ratio", 0)

    if la_status == "CRITICAL":
        recs.append({
            "level": "CRITICAL",
            "title": "CPU Overload — LA15/vCPU >= 1.0",
            "problem": (
                f"LA15={la15:.2f} on {nproc} vCPU (ratio={la_ratio:.2f}). "
                "System is CPU-saturated. Services may degrade."
            ),
            "commands": [
                "# Identify top CPU consumers:",
                "ps auxww --sort=-%cpu | head -20",
                "# Per-core breakdown:",
                "mpstat -P ALL 1 5",
                "# Per-process CPU+threads:",
                "pidstat -u 1 5",
                "# Temporary: limit a specific service CPU quota:",
                "systemctl set-property <unit>.service CPUQuota=50%",
                "# Temporary: limit a Docker container:",
                "docker update --cpus 2 <container_name>",
            ],
        })
    elif la_status == "WARN":
        recs.append({
            "level": "WARN",
            "title": "CPU Load Elevated — LA15/vCPU between 0.8 and 1.0",
            "problem": (
                f"LA15={la15:.2f} on {nproc} vCPU (ratio={la_ratio:.2f}). "
                "Approaching saturation. Monitor closely."
            ),
            "commands": [
                "# Identify top consumers:",
                "ps auxww --sort=-%cpu | head -20",
                "# Check per-core and run queue:",
                "mpstat -P ALL 1 3 && vmstat 1 3",
            ],
        })

    # ── CPU: Steal% (hypervisor throttling) ──────────────────────────────────
    steal = metrics.get("steal", 0)
    if steal > 10:
        recs.append({
            "level": "CRITICAL",
            "title": "High CPU Steal% — Hypervisor is throttling this VM",
            "problem": (
                f"steal%={steal}. CPU cycles are being taken by the hypervisor. "
                "Escalate to infrastructure/virtualization team."
            ),
            "commands": [
                "# Confirm steal over time:",
                "vmstat 1 10 | awk '{print $16}' | tail -10",
                "# Escalate to the team managing the hypervisor.",
                "# No fix possible at OS level — requires VM or host migration.",
            ],
        })
    elif steal > 5:
        recs.append({
            "level": "WARN",
            "title": "Elevated CPU Steal% — Possible hypervisor contention",
            "problem": f"steal%={steal}. Monitor trend, escalate if persistent.",
            "commands": [
                "vmstat 1 10",
            ],
        })

    # ── RAM: high usage ───────────────────────────────────────────────────────
    ram_pct = metrics.get("ram_used_pct", 0)
    if ram_pct >= 95:
        recs.append({
            "level": "CRITICAL",
            "title": f"RAM Usage Critical — {ram_pct}% used",
            "problem": "System may start using swap aggressively or OOM-kill processes.",
            "commands": [
                "# Top RAM consumers:",
                "ps auxww --sort=-%mem | head -20",
                "# Check for memory growth in a process (replace PID):",
                "grep -E 'VmRSS|VmSize' /proc/<PID>/status",
                "# Check OOM kills:",
                "dmesg | grep -i 'oom\\|killed process' | tail -20",
                "# Drop caches (safe, temporary):",
                "sync && echo 3 > /proc/sys/vm/drop_caches",
            ],
        })
    elif ram_pct >= 85:
        recs.append({
            "level": "WARN",
            "title": f"RAM Usage High — {ram_pct}% used",
            "problem": "System is under memory pressure.",
            "commands": [
                "ps auxww --sort=-%mem | head -20",
                "free -h && vmstat 1 3",
            ],
        })

    # ── Disk: critical partitions ─────────────────────────────────────────────
    for mount, pct in metrics.get("disk_critical", []):
        recs.append({
            "level": "CRITICAL",
            "title": f"Disk Full — {mount} at {pct}%",
            "problem": (
                f"Partition {mount} is {pct}% full. "
                "Writes will fail. Services may crash."
            ),
            "commands": _disk_cleanup_commands(mount),
        })

    for mount, pct in metrics.get("disk_warn", []):
        recs.append({
            "level": "WARN",
            "title": f"Disk High — {mount} at {pct}%",
            "problem": f"Partition {mount} is approaching full ({pct}%).",
            "commands": [
                f"# Find what's growing in {mount}:",
                f"du -xhd2 {mount} | sort -h | tail -20",
            ],
        })

    # ── Inode exhaustion ──────────────────────────────────────────────────────
    for mount, pct in metrics.get("inode_warn", []):
        recs.append({
            "level": "WARN",
            "title": f"Inode Usage High — {mount} at {pct}%",
            "problem": "Too many small files. Disk may report space free but writes will fail.",
            "commands": [
                "# Find directories with most files:",
                f"find {mount} -xdev -printf '%h\\n' | sort | uniq -c | sort -nr | head -20",
                "# Typical cause: many small log files, temp files, or apt cache.",
                "sudo apt-get clean",
                "sudo find /var/log -name '*.gz' -mtime +14 -delete",
            ],
        })

    # ── Deleted files held open ───────────────────────────────────────────────
    if metrics.get("deleted_held"):
        recs.append({
            "level": "WARN",
            "title": "Deleted Files Still Held by Processes",
            "problem": (
                "Files deleted from disk but still open by processes. "
                "Space not released until process restarts. "
                "This causes 'du vs df' discrepancy."
            ),
            "commands": [
                "# See which files and processes:",
                "sudo lsof +L1 | grep -E '/var|/log'",
                "# Option 1 — Truncate file (space freed immediately, no restart):",
                "sudo truncate -s 0 /path/to/file",
                "# Option 2 — Restart the holding process (if safe):",
                "sudo systemctl restart <service-name>",
            ],
        })

    # ── systemd journal ───────────────────────────────────────────────────────
    journal_mb = metrics.get("journal_mb", 0)
    if journal_mb >= 2048:
        recs.append({
            "level": "WARN",
            "title": f"systemd Journal is Large — {journal_mb/1024:.1f} GB",
            "problem": "Journal logs consuming significant disk space in /var/log/journal.",
            "commands": [
                "# Immediate cleanup — keep last 7 days:",
                "sudo journalctl --vacuum-time=7d",
                "# Or keep max 500MB:",
                "sudo journalctl --vacuum-size=500M",
                "# Permanent limit — add to /etc/systemd/journald.conf:",
                "# SystemMaxUse=1G",
                "# MaxFileSec=7day",
                "sudo systemctl restart systemd-journald",
            ],
        })

    # ── Failed systemd services ───────────────────────────────────────────────
    if metrics.get("failed_services"):
        recs.append({
            "level": "WARN",
            "title": "Failed systemd Services Detected",
            "problem": "One or more services are in 'failed' state.",
            "commands": [
                "# List failed services:",
                "systemctl --failed",
                "# Check logs for a specific failed service:",
                "journalctl -u <service-name> --since '1 hour ago'",
                "# Attempt restart:",
                "sudo systemctl restart <service-name>",
            ],
        })

    # ── Docker: disk cleanup ──────────────────────────────────────────────────
    if metrics.get("docker_installed"):
        recs.append({
            "level": "INFO",
            "title": "Docker: Disk Cleanup Available",
            "problem": "Docker can accumulate unused images, volumes, and build cache over time.",
            "commands": [
                "# Check what can be reclaimed:",
                "docker system df",
                "# Remove unused containers, networks, dangling images:",
                "docker system prune -f",
                "# Also remove unused images older than 10 days (careful on prod):",
                "docker image prune -a -f --filter 'until=240h'",
                "# Truncate a specific container log (no restart needed):",
                "sudo truncate -s 0 $(docker inspect --format='{{.LogPath}}' <container>)",
                "# Add log rotation to /etc/docker/daemon.json:",
                '# {"log-driver": "json-file", "log-opts": {"max-size": "100m", "max-file": "3"}}',
                "sudo systemctl reload docker",
            ],
        })

    # ── Sort: CRITICAL first, then WARN, then INFO ────────────────────────────
    order = {"CRITICAL": 0, "WARN": 1, "INFO": 2}
    recs.sort(key=lambda r: order.get(r["level"], 9))

    return recs


def _disk_cleanup_commands(mount: str) -> list[str]:
    """Returns targeted cleanup commands depending on the mount point."""
    base = [
        f"# Step 1 — find what's large in {mount}:",
        f"sudo du -xhd2 {mount} | sort -h | tail -30",
        f"# Step 2 — find files >100MB:",
        f"sudo find {mount} -xdev -type f -size +100M -printf '%s\\t%TY-%Tm-%Td\\t%p\\n' | sort -nr | head -20",
        "# Step 3 — check for deleted-but-held files (du vs df gap):",
        "sudo lsof +L1",
    ]

    if mount == "/var" or mount.startswith("/var"):
        base += [
            "",
            "# /var-specific cleanup:",
            "# -- APT cache (safe to clear anytime):",
            "sudo apt-get clean",
            "# -- systemd journal (keep last 7 days):",
            "sudo journalctl --vacuum-time=7d",
            "# -- Docker logs (truncate without restarting containers):",
            "sudo find /var/log/docker -type f -size +200M -exec truncate -s 0 {} \\;",
            "# -- Docker container JSON logs:",
            "sudo find /var/lib/docker/containers -name '*-json.log' -size +200M -exec truncate -s 0 {} \\;",
            "# -- atop logs older than 14 days:",
            "sudo find /var/log/atop -type f -mtime +14 -delete",
            "# -- Old compressed logs (>30 days):",
            "sudo find /var/log -type f -name '*.gz' -mtime +30 -delete",
            "",
            "# If LVM — check if you can extend the volume:",
            "sudo vgs && sudo lvs",
            "# Extend if free space exists in VG:",
            "sudo lvextend -r -L +10G /dev/mapper/data-var",
            "# -r flag resizes filesystem automatically (ext4 and xfs).",
        ]

    return base


# ─── Standalone test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Example: simulate a server with CPU and disk issues
    test_metrics = {
        "la15": 14.5,
        "nproc": 8,
        "la_ratio": 1.81,
        "la_status": "CRITICAL",
        "steal": 8.2,
        "ram_used_pct": 95.0,
        "disk_critical": [("/var", 100)],
        "disk_warn": [],
        "inode_warn": [],
        "deleted_held": True,
        "journal_mb": 3000,
        "failed_services": True,
        "docker_installed": True,
    }

    recs = generate_recommendations(test_metrics)
    print(f"\nGenerated {len(recs)} recommendations:\n")
    for r in recs:
        print(f"[{r['level']}] {r['title']}")
        print(f"  Problem: {r['problem']}")
        print(f"  Commands:")
        for cmd in r["commands"]:
            print(f"    {cmd}")
        print()
