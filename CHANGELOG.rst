Changelog
=========

v3.3.0
------

- Added support for alternative archive openers in plug-ins.
- Reworked HTTP cache.

CLI
~~~

- Extended ``--no-cache`` flag to add-on downloads.

v3.2.0
------

- Added support for Python 3.12.

CLI
~~~

- The CLI is now bundled as a single-file self-extracting
  executable using `PyApp <https://github.com/ofek/pyapp>`_
  instead of PyInstaller.

GUI
~~~

- Fixed creating non-standard configuration directories.
- Stopped bundling Mozilla's root certificate store.

v3.1.0
------

- Reconciliation was made to cross-reference add-ons from the GitHub catalogue.
- XDG env vars are now respected on all platforms; if `$XDG_CONFIG_HOME` is set,
  it will be preferred over the platform-native configuration directory.
  This is a behaviour change on macOS and Windows.
- Logs and plug-in data are stored under `$XDG_STATE_HOME` on Linuxes by default.

v3.0.1
------

CLI
~~~

- Restored asyncio event loop policy override on Windows for Python 3.9.

GUI
~~~

- Fixed add-on alias and URL search.

v3.0.0
------

- Dropped support for Tukui add-ons other than the two headline UI suites,
  having switched from the original API at https://www.tukui.org/api.php
  to https://api.tukui.org/v1.
  The new API is hosted by the author of
  `CurseBreaker <https://github.com/AcidWeb/CurseBreaker>`_.
  The original API is unmaintained and the add-on index has fallen into disuse.
- Numeric aliases are no longer valid for Tukui add-ons; use ``tukui:elvui`` for
  ElvUI and ``tukui:tukui`` for Tukui.

CLI
~~~

- Added WoW installation finder (Mac only).  Located installations will be
  offered as suggestions bypassing manual add-on directory and flavour entry
  when configuring *instawow*.
- Added add-on definition mini-DSL replacing the various strategy install options.
  Strategies can now be passed as URL fragments of the add-on ``Defn``,
  e.g. ``foo:bar#any_flavour,version_eq=1``.
- Strategies passed to ``update --retain-strategies`` will be respected *if* they result
  in a change.  This opens up several possibilities, e.g. a bare ``source:alias``
  will unpin an add-on that was previously rolled back.
- Removed ``--version`` option from ``rollback``.  Use ``update --retain-strategies`` to
  roll back to a known version.
- Added ``--dry-run`` option to ``install`` and ``update``.
  Issue ``instawow update --dry-run`` to check for add-on updates.
- Added ``list-sources`` command to display the active source metadata.
- Added ``--prefer-source`` option to ``search``.  If an add-on is found
  from a preferred source, identical add-ons from other sources are omitted
  from the results.
- Installed add-ons are now excluded from ``search`` results.
  This includes identical add-ons from sources other than the one installed.
  Pass ``--no-exclude-installed`` to opt out.
- Changed the Markdown flavour used to convert changelogs
  with pandoc from Markdown.pl to CommonMark to fix an issue
  with list formatting.

API
~~~

- Public enum members are now capitalised.
- Exposed ``plugins.InstawowPlugin`` protocol.  *instawow* plug-ins should
  conform to this protocol.
