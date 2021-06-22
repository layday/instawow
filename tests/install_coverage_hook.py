from pathlib import Path
import sysconfig

(Path(sysconfig.get_path('purelib')) / 'coverage.pth').write_text(
    'import coverage; coverage.process_startup()',
    encoding='utf-8',
)
