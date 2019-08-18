*instawow*
==========

*instawow* is a package manager for World of Warcraft written
in Python.  It can be used to install, remove and update add-ons from
Curse, WoWInterface and Tukui.

Installation
------------

It is recommended to install *instawow* in an isolated environment.
One option is `pipx <https://github.com/pipxproject/pipx>`__::

    pipx install instawow

Installing with `pip` is also supported::

    pip3 install instawow

Usage
-----

You can install add-ons by their Curse project ID or slug, or their
WoWInterface ID, or even by their URL. All of the following will install
Molinari::

    instawow install curse:20338
    instawow install curse:molinari
    instawow install https://www.curseforge.com/wow/addons/molinari
    instawow install https://wow.curseforge.com/projects/molinari
    instawow install wowi:13188
    instawow install https://www.wowinterface.com/downloads/info13188-Molinari.html

By default, *instawow* will install the latest file that was *released*.
You can choose to install the latest file that has been
uploaded (be it stable, or beta or alpha quality) by
passing ``--strategy=latest``.  This option only works with CurseForge packages.

You can uninstall add-ons with::

    instawow remove <add-on>

You can update all of your add-ons in one go with::

    instawow update

... or any individual add-on the same way you'd install or remove it::

    instawow update <add-on>

You can list installed add-ons with ``instawow list`` and add-ons that
predate the venerable *instawow* with ``instawow list-uncontrolled``.
``list-uncontrolled`` will attempt to extract Curse and WoWI IDs from TOC files
to put you on a path towards instalightment.

Non-destructive operations can be invoked with partial package slugs,
e.g. ``instawow info moli`` will attempt to match 'moli' with ``curse:molinari``.

Extras
------

WeakAuras aura updater
~~~~~~~~~~~~~~~~~~~~~~

*instawow* contains a WeakAuras updater modelled after
`WeakAuras Companion <https://weakauras.wtf/>`__.  To use the updater
and provided that you have WeakAuras installed::

    instawow extras weakauras build-companion -a <your account name>
    instawow install instawow:weakauras-companion

Parsing the the WeakAuras saved variables file can take quite a bit of time
which is why the operation is not baked into the normal workflow;
you will have to run ``instawow extras weakauras build-companion`` prior to
``instawow update`` to receive aura updates.

WebSocket server
~~~~~~~~~~~~~~~~

Of interest only to developers: a WebSocket client can be used to
operate *instawow* in lieu of the command line
through a JSON-RPC API. To start the WebSocket server, run ``instawow serve``.
The API does not implement JSON-RPC batch calls; request grouping must be
done client-side.

Caveats
-------

Detecting existing add-ons
~~~~~~~~~~~~~~~~~~~~~~~~~~

The Twitch and Minion clients each use their own, proprietary
fingerprinting algorithm to reconcile add-ons you have installed with add-ons
they keep on their servers.  Though the details of their implementation
elude me, *instawow* could accomplish something similar by combining a variety
of cues (e.g. folders, TOC entries).  However, *instawow* tries very hard to be
source-agnostic and will not default to installing an add-on from one host
over another.  The alternative would require some degree of interactivity
which I feel is better suited to a desktop client.

Searching for add-ons
~~~~~~~~~~~~~~~~~~~~~

*instawow* tries to make installing, updating and removing
add-ons quick and painless for those of us who are
(ever so slightly) proficient with the command line
and do not revel in using bloatware which infringe on our privacy
or inhabiting walled gardens.
It does not try to circumvent add-on portals entirely.

Metadata sourcing
~~~~~~~~~~~~~~~~~

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

World of Warcraft Classic
-------------------------

*instawow* does not have tailored support for Classic.
The easiest way to manage your classic add-ons is to create a separate
*instawow* profile.  For instance::

    env INSTAWOW_CONFIG_DIR=~/.config/instawow-classic instawow

For ease of use, you might want to set up an alias.  In your Bash profile,
add::

    alias instawow-classic='INSTAWOW_CONFIG_DIR=~/.config/instawow-classic instawow'

You would then invoke *instawow* for Classic using ``instawow-classic``.
To install classic add-ons from CurseForge, use the ``curse+classic`` specifier, e.g.
``instawow-classic install curse+classic:details``.

Related work
------------

The author of *wowman* maintains a list of similar software in their
`comrades.csv <https://github.com/ogri-la/wowman/blob/develop/comrades.csv>`__.

Migrating from lcurse
~~~~~~~~~~~~~~~~~~~~~

`lcurse <https://github.com/ephraim/lcurse>`__ has not seen updates in a while.
If you wish, you can migrate your add-ons from *lcurse* to *instawow*
by running the following command::

    cat ~/.lcurse/addons.json | jq --raw-output '.addons[].uri' |
        tr 'A-Z' 'a-z' | xargs instawow install -o

Do note that this will overwrite your add-ons.

Development
-----------

Fork and clone the `repo <https://github.com/layday/instawow>`__, ``cd``
and::

    python3 -m venv venv
    source venv/bin/activate
    python3 -m pip install -e .

Happy hacking.

Contributing
------------

Bug reports and fixes are welcome. Do open an issue before committing to
making any significant changes.
