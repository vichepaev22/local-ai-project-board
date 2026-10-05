"""Resolve an installed Codex runtime without trusting stale PATH order."""
import os
from pathlib import Path
import re
import shutil
import subprocess


class RuntimeSelectionError(RuntimeError):
    pass


def resolve_runtime() -> dict[str, str]:
    override = os.environ.get('PORTFOLIO_CODEX_BIN', '').strip()
    candidates = []
    if override:
        path = Path(override)
        if not path.is_absolute() or not path.is_file():
            raise RuntimeSelectionError('PORTFOLIO_CODEX_BIN должен указывать на существующий исполняемый файл Codex по абсолютному пути.')
        candidates.append(path)
    else:
        cli = shutil.which('codex')
        if cli:
            candidates.append(Path(cli))
        local = os.environ.get('LOCALAPPDATA')
        if local:
            root = Path(local)
            bundled = root / 'OpenAI/Codex/bin'
            candidates.extend(bundled.glob('*/codex.exe'))
            candidates.extend([bundled / 'codex.exe', root / 'Programs/OpenAI/Codex/bin/codex.exe'])
    versions = []
    for path in dict.fromkeys(candidates):
        if not path.is_file():
            continue
        try:
            result = subprocess.run([str(path), '--version'], capture_output=True, text=True,
                                    encoding='utf-8', errors='replace', timeout=5,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            match = re.search(r'\bcodex-cli\s+(\d+)\.(\d+)\.(\d+)([-+][0-9A-Za-z.-]+)?', result.stdout)
            if result.returncode == 0 and match:
                version = '.'.join(match.group(i) for i in range(1, 4)) + (match.group(4) or '')
                rank = tuple(int(match.group(i)) for i in range(1, 4)) + (not bool(match.group(4)),)
                versions.append((rank, {'executable': str(path), 'version': version}))
        except (OSError, subprocess.SubprocessError):
            continue
    if not versions:
        raise RuntimeSelectionError('Не удалось проверить версию установленного Codex. Проверьте установку' + (' и PORTFOLIO_CODEX_BIN.' if override else '.'))
    return max(versions, key=lambda candidate: candidate[0])[1]
