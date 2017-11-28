
from os import environ
from pathlib import Path

import click
import pydantic


_addon_dirs = ([True,
                lambda: Path('/Applications/World of Warcraft/Interface/AddOns')],
               ['Public' in environ,
                lambda: Path(environ['Public'],
                             'Games\\World of Warcraft\\Interface\\AddOns')],
               ['ProgramFiles(x86)' in environ,
                lambda: Path(environ['ProgramFiles(x86)'],
                             'World of Warcraft\\Interface\\AddOns')],
               ['ProgramFiles' in environ,
                lambda: Path(environ['ProgramFiles'],
                             'World of Warcraft\\Interface\\AddOns')],)


class Config(pydantic.BaseSettings):

    addon_dir: Path
    config_dir: Path = click.get_app_dir('instawow')
    db_name: str = 'db.sqlite'

    def _process_values(self, values_dict):
        values = super()._process_values(values_dict)
        for k, v in values.items():
            if isinstance(v, Path):
                values[k] = v.expanduser().resolve()
        if not values['addon_dir'] or not values['addon_dir'].is_dir():
            raise ValueError
        return values

    def create_dirs(self):
        """Create the requisite application directories."""
        self.config_dir.mkdir(exist_ok=True)
        return self


class _UserConfigMeta(Config.__class__):

    @property
    def default_addon_dir(cls):
        return next((v() for k, v in _addon_dirs if k and v().is_dir()),
                    None)


class UserConfig(Config, metaclass=_UserConfigMeta):

    @classmethod
    def read(cls):
        """Attempt to load the config from the default path, returning a new
        instance of the class.
        """
        return cls(addon_dir=Path(cls.__fields__['config_dir'].default,
                                  'addon_dir.txt').read_text(encoding='utf-8'))

    def write(self):
        """Write the active config to the default path."""
        (self.config_dir/'addon_dir.txt').write_text(str(self.addon_dir),
                                                     encoding='utf-8')
