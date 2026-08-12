"""Explicit, shell-free Windows process launching."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LaunchedProcess:
    pid: int


class WindowsProcessLauncher:
    def launch(
        self,
        executable: Path,
        arguments: Sequence[str],
        cwd: Path,
        environment: Mapping[str, str],
    ) -> LaunchedProcess:
        process = subprocess.Popen(
            [str(executable), *arguments],
            cwd=str(cwd),
            env=dict(environment),
            shell=False,
            close_fds=True,
        )
        return LaunchedProcess(process.pid)
