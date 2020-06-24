*instawow*
==========

*instawow* is a package manager for World of Warcraft, written
in Python.  It can be used to install, remove and update add-ons from
WoWInterface, CurseForge and Tukui.

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

Begin with running ``instawow reconcile --auto`` to register previously-installed
add-ons with *instawow*.  To install add-ons, you can search for them
using the ``search`` command, like so::

    instawow search molinari

In addition *instawow* is able to interpret add-on URLs, slugs and host IDs.
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

WoW Classic
~~~~~~~~~~~

*instawow* supports Classic – it will correctly install Classic versions
of add-ons from sources depending on the value of the
``game_flavour`` configuration setting.
What *instawow* does not have is a switch you can flick to go from managing
your retail add-ons to managing your classic add-ons and vice versa.
This was a conscious design decision, the merits of which (I should admit)
are open to debate.  If you are already using *instawow* for retail,
you will need to create a separate profile for Classic.  On Linux, this might be::

    INSTAWOW_CONFIG_DIR=~/.config/instawow-classic instawow

For ease of use, you might want to set up an alias.  In your Bash profile, add::

    alias instawow-classic='INSTAWOW_CONFIG_DIR=~/.config/instawow-classic instawow'

You would then be able to invoke *instawow* using ``instawow-classic``.

The ``any_flavour`` strategy can be used to install ostensibly retail-only add-ons
that work in Classic.  For example::

    instawow-classic install -s any_flavour https://www.curseforge.com/wow/addons/colorpickerplus

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

You may then choose to bypass the companion add-on simply by ommitting the env var.

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
API interally in Q2 2019, which we have adopted for our own use.
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
Tukui add-on metadata from https://www.tukui.org, and
aura data from https://data.wago.io;
and will follow file URLs contained in metadata.

Every 24 hours, on launch, *instawow* will query PyPI (https://pypi.org) – the
canonical Python package repository – to suggest updating *instawow* to the
latest version.

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
