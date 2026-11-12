"""Capture real exit codes for sequential frozen valid/test evaluation."""
import json
from pathlib import Path
import subprocess
import sys

root = Path(__file__).parent
codes = {}
with (root / 'quality_alias_fix.log').open('w') as output:
    for split in ('valid', 'test'):
        result = subprocess.run([sys.executable, '-m', 'docker.quality', '--split', split],
                                stdout=output, stderr=subprocess.STDOUT)
        codes[split] = result.returncode
        (root / 'quality_recheck_exit.json').write_text(json.dumps(codes) + '\n')
        if result.returncode:
            raise SystemExit(result.returncode)
