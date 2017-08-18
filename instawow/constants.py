
import click


_SUCCESS = click.style('✓', fg='green')
_FAILURE = click.style('✗', fg='red')

MESSAGES = {k: v.format for k, v in {
    'any_failure__non_existent':
        f'{_FAILURE} {{id}}: no such project id or slug',
    'any_failure__not_installed':
        f'{_FAILURE} {{id}}: not installed',
    'any_failure__preexisting_folder_conflict':
        f'{_FAILURE} {{id}}: conflicts with an add-on not installed by instawow\n'
        f'pass `-o` to `install` if you do actually wish to overwrite this add-on',
    'any_failure__installed_folder_conflict':
        f'{_FAILURE} {{id}}: conflicts with {{other}}',
    'install_success':
        f'{_SUCCESS} {{id}}: installed {{version}}',
    'install_failure__installed':
        f'{_FAILURE} {{id}}: already installed',
    'install_failure__invalid_origin':
        f'{_FAILURE} {{id}}: invalid origin',
    'update_success':
        f'{_SUCCESS} {{id}}: updated from {{old_version}} to {{new_version}}',
    'remove_success':
        f'{_SUCCESS} {{id}}: removed',
    'set_success':
        f'{_SUCCESS} {{id}}: {{var!r}} set to {{new_strategy!r}}'}.items()}
