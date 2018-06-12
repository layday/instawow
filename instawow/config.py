
from os import environ
from pathlib import Path
import typing as T

import click
import pydantic


_DEFAULT_CONFIG_DIR = Path(click.get_app_dir('instawow'))


class Config(pydantic.BaseSettings):

    addon_dir: Path
    config_dir: Path = _DEFAULT_CONFIG_DIR
    db_name: str     = 'db.sqlite'

    @pydantic.validator('addon_dir', 'config_dir')
    def _validate_paths(cls, value) -> Path:
        value = value.expanduser().resolve()
        if not value.is_dir():
            raise ValueError
        return value

    def create_dirs(self):  # -> Config
        "Create the necessary folders."
        self.config_dir.mkdir(exist_ok=True)
        return self


class UserConfig(Config):

    @classmethod
    def detect_addon_dir(cls) -> T.Optional[Path]:
        "Attempt to detect the location of the add-on folder."
        paths = [('Public' in environ and
                  Path(environ['Public'],
                       'Games\\World of Warcraft\\Interface\\AddOns')),
                 ('ProgramFiles(x86)' in environ and
                  Path(environ['ProgramFiles(x86)'],
                       'World of Warcraft\\Interface\\AddOns')),
                 ('ProgramFiles' in environ and
                  Path(environ['ProgramFiles'],
                       'World of Warcraft\\Interface\\AddOns')),
                 Path('/Applications/World of Warcraft/Interface/AddOns')]
        return next(filter(Path.is_dir, filter(None, paths)), None)

    @classmethod
    def read(cls):  # -> UserConfig
        "Attempt to read the config from the default path."
        return cls(addon_dir=(_DEFAULT_CONFIG_DIR/'addon_dir.txt')
                             .read_text(encoding='utf-8'))

    def write(self) -> None:
        "Write ``self.addon_dir`` on disk."
        (self.config_dir/'addon_dir.txt').write_text(str(self.addon_dir),
                                                     encoding='utf-8')
