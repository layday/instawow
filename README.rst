*instawow*
==========

*instawow* is a package manager for World of Warcraft, written
in Python.  It can be used to install, remove and update add-ons from
WoWInterface, CurseForge, Tukui and GitHub.

*instawow* tries to make installing, updating and removing
add-ons quick and painless for those of us who are
(ever so slightly) proficient with the command line
and do not revel in using bloatware which infringe on our privacy
or inhabiting walled gardens.

.. image:: https://asciinema.org/a/NfIonzvUn65jEl9v0D2WQJdLl.svg
   :width: 640
   :alt: Asciicast demonstrating the operation of instawow.
   :target: https://asciinema.org/a/NfIonzvUn65jEl9v0D2WQJdLl?autoplay=1

Installation
------------

I recommend installing *instawow* in an isolated environment.
|pipx|_ makes this easy::

    pipx install instawow

Or using `Nix <https://nixos.org/>`__::

    nix-env -if https://github.com/layday/instawow-nix/tarball/master

Installing with ``pip`` is also supported::

    pip3 install --upgrade instawow

Finally, you can download pre-built binaries from
`GitHub <https://github.com/layday/instawow/releases>`__.
These are available for Linux (compiled on Ubuntu), macOS, and Windows.

.. |pipx| replace:: ``pipx``
.. _pipx: https://github.com/pipxproject/pipx

Getting started
---------------

tl;dr
~~~~~

Begin with running ``instawow reconcile``
(or ``instawow reconcile --auto`` to reconcile add-ons without user input)
to register previously-installed add-ons with *instawow*.
To install add-ons, you can search for them using the ``search`` command::

    instawow search molinari

In addition, *instawow* is able to interpret add-on URLs, slugs and host IDs.
All of the following will install Molinari from CurseForge::

    instawow install https://www.curseforge.com/wow/addons/molinari
    instawow install curse:molinari
    instawow install curse:20338

You can ``update`` add-ons and ``remove`` them just as you'd install them.
If ``update`` is invoked without arguments, it will update all of your
installed add-ons.  You can ``list`` add-ons and view detailed information about
them using ``list --format detailed``.  The argument of ``list`` and similarly
non-destructive commands can be a substring of the add-on name; for instance,
``instawow reveal molinari`` will open the Molinari add-on folder in your
file manager.

*instafying* add-ons
~~~~~~~~~~~~~~~~~~~~

*instawow* does not know about add-ons it did not itself install.
The Twitch and Minion clients each use their own, proprietary
fingerprinting algorithm to reconcile add-ons you have installed with add-ons
their respective hosts keep on their servers.  Though the details of their implementation
elude me, *instawow* tries to accomplish something similar by combining a variety
of cues (e.g. folders and TOC entries).  This is not done automatically;
you will need to run ``instawow reconcile`` to absorb add-ons installed
through other means.  The ``--auto`` flag automates the reconciliation process.

Searching for add-ons
~~~~~~~~~~~~~~~~~~~~~

*instawow* comes with a rudimentary ``search`` command which allows you to
select add-ons to install.
The search does not display add-on details other than the name and source;
pressing ``<o>`` will bring the add-on page up in your browser.
Search uses a collated add-on catalogue internally which is updated
`once daily <https://github.com/layday/instawow-data/tree/data>`__.

Dealing with pesky updates
~~~~~~~~~~~~~~~~~~~~~~~~~~

As of version 1.10.0, *instawow* keeps a log of all versions of an add-on it has
installed in the past.
Add-on updates can be reverted using the ``instawow rollback`` command.
Rollbacked add-ons and versioned add-ons more generally
cannot be updated.
Rollbacks can themselves be undone with ``instawow rollback --undo``,
which will install the latest version of the specified add-on using
the default strategy.

Rollback is currently only supported for CurseForge and GitHub.

GitHub as a source
~~~~~~~~~~~~~~~~~~

*instawow* purports to support WoW add-ons *released* on GitHub; that is to say,
the repository must have a release associated with it and that release *must*
carry a ZIP file as an asset.  *instawow* will not install or build add-ons from
source.

I do not recommend using GitHub as a source unless an add-on cannot
be found in a domain-specific source.

WoW Classic
~~~~~~~~~~~

*instawow* supports Classic – it will correctly install Classic versions
of add-ons from sources depending on the value of the
``game_flavour`` configuration setting.
What *instawow* does not have is a switch you can flick to go from managing
your retail add-ons to managing your classic add-ons and vice versa.
This was a conscious design decision, the merits of which – I should admit –
are open to debate.  If you are already using *instawow* for Retail,
you will need to set up a profile for Classic.  To activate an
alternative profile, you must use the ``--profile``/``-p`` option.  Assuming your
default profile is configured for retail,
you can create a pristine profile by running::

    instawow -p classic configure

You must then prefix ``-p classic`` to commands to manage your Classic profile.

Before v1.12, the only way to create a new profile was to
override the default configuration folder in the environment.
This remains an option.  In Bash::

    INSTAWOW_CONFIG_DIR=~/.config/instawow-classic instawow

The ``any_flavour`` strategy can be used to install add-ons from CurseForge
which have not been released for Classic but work just as well.
Taking ColorPickerPlus as an example::

    instawow -p classic install -s any_flavour https://www.curseforge.com/wow/addons/colorpickerplus

Additional functionality
------------------------

WeakAuras aura updater
~~~~~~~~~~~~~~~~~~~~~~

*instawow* contains a WeakAuras updater modelled on
`WeakAuras Companion <https://weakauras.wtf/>`__.  To use the updater
and provided that you have WeakAuras installed::

    instawow weakauras-companion build -a <your account name>
    instawow install instawow:weakauras-companion

You will have to rebuild the companion add-on prior to updating
to receive aura updates.  If you would like to check for updates on
every invocation of ``instawow update``, install the
``instawow:weakauras-companion-autoupdate`` variant, exposing your account
name as an env var::

    WAC_ACCOUNT=<your account name> instawow install instawow:weakauras-companion-autoupdate
    WAC_ACCOUNT=<your account name> instawow update

You may then choose to bypass the companion add-on when updating
simply by ommitting the env var.

Metadata sourcing
-----------------

Originally, *instawow* relied on the official feeds provided by Curse.
Curse retired the feeds in June 2018 and – for a period – *instawow* would
scrape the CurseForge website.  The alternative would have been to use the
old XML-like API.  Because the API was not built for third-party use, it had not been
isolated from user accounts (cf. GitHub integrations).
If users were to log into the API, *instawow* would acquire full
access to their account.  Authentication was also complicated
by the ongoing Curse account migration to Twitch and is (or should be)
unnecessary for the simple use case of installing and updating add-ons.
Thankfully, Twitch migrated to an unauthenticated
API interally in the second quarter of the year of the periodic table,
which we have adopted for our own use.
This is similar to what Minion, the WoWInterface-branded add-on manager, has been
doing for years.  The good people at Tukui provide an API for public use.
*instawow* might break whenever one of our sources introduces
a change to their website or API (though only temporarily).

Remote hosts
------------

When installing, updating or searching for add-ons, *instawow* will retrieve
scraped add-on metadata from https://raw.githubusercontent.com,
CurseForge add-on metadata from https://addons-ecs.forgesvc.net,
WoWInterface add-on metadata from https://api.mmoui.com,
Tukui add-on metadata from https://www.tukui.org,
GitHub add-on metadata from https://api.github.com,
and aura data from https://data.wago.io;
and will follow download URLs contained in metadata.

Every 24 hours, on launch, *instawow* will query PyPI (https://pypi.org) – the
canonical Python package repository – to check for *instawow* updates.

Requests made by *instawow* can be identified by its user agent string.

Related work
------------

The author of *wowman* has been cataloguing similar software
`here <https://ogri-la.github.io/wow-addon-managers/>`__.  If you are unhappy
with *instawow*, you might find one of these other add-on managers more
to your liking.

Contributing
------------

Bug reports and fixes are welcome.  Do open an issue before committing to
making any significant changes.
