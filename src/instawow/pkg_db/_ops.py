from __future__ import annotations

from . import Connection
from .models import Pkg, make_db_converter


def insert_pkg(pkg: Pkg, transaction: Connection) -> None:
    pkg_values = make_db_converter().unstructure(pkg)

    transaction.execute(
        """
        INSERT INTO pkg (
            source,
            id,
            slug,
            name,
            description,
            url,
            download_url,
            date_published,
            version,
            changelog_url
        )
        VALUES (
            :source,
            :id,
            :slug,
            :name,
            :description,
            :url,
            :download_url,
            :date_published,
            :version,
            :changelog_url
        )
        """,
        pkg_values,
    )
    transaction.execute(
        """
        INSERT INTO pkg_options (
            any_flavour,
            any_release_type,
            version_eq,
            pkg_source,
            pkg_id
        )
        VALUES (
            :any_flavour,
            :any_release_type,
            :version_eq,
            :pkg_source,
            :pkg_id
        )
        """,
        pkg_values['options'] | {'pkg_source': pkg_values['source'], 'pkg_id': pkg_values['id']},
    )
    transaction.executemany(
        """
        INSERT INTO pkg_folder (
            name,
            pkg_source,
            pkg_id
        )
        VALUES (
            :name,
            :pkg_source,
            :pkg_id
        )
        """,
        [
            f | {'pkg_source': pkg_values['source'], 'pkg_id': pkg_values['id']}
            for f in pkg_values['folders']
        ],
    )
    if pkg_values['deps']:
        transaction.executemany(
            """
            INSERT INTO pkg_dep (
                id,
                pkg_source,
                pkg_id
            )
            VALUES (
                :id,
                :pkg_source,
                :pkg_id
            )
            """,
            [
                f | {'pkg_source': pkg_values['source'], 'pkg_id': pkg_values['id']}
                for f in pkg_values['deps']
            ],
        )
    transaction.execute(
        """
        INSERT OR IGNORE INTO pkg_version_log (
            version,
            pkg_source,
            pkg_id
        )
        VALUES (
            :version,
            :pkg_source,
            :pkg_id
        )
        """,
        {
            'version': pkg_values['version'],
            'pkg_source': pkg_values['source'],
            'pkg_id': pkg_values['id'],
        },
    )


def delete_pkg(pkg: Pkg, transaction: Connection) -> None:
    transaction.execute(
        'DELETE FROM pkg WHERE source = :source AND id = :id',
        make_db_converter().unstructure(pkg),
    )
