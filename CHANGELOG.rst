v3.0.0
~~~~~~

- Dropped support for Tukui add-ons other than ElvUI and the Tukui suite.
  The Tukui add-on index has fallen into disuse and will be retired.

CLI
---

- Added add-on definition mini-DSL replacing the various strategy install options.
  Strategies can now be passed as URL fragments of the add-on ``Defn``,
  e.g. ``foo:bar#any_flavour;version_eq=1``.
- Strategies passed to the ``update`` command will be respected *if* they result
  in a change.  This opens up several possibilities, e.g. a bare ``source:alias``
  will unpin an add-on that was previously rolled back.
- Removed ``--version`` option from ``rollback``.  Use the ``update`` command to
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
---

- Public enum members are now capitalised.
- Exposed ``plugins.InstawowPlugin`` protocol.  *instawow* plug-ins shouldd
  conform to this protocol.
