
_instawow_ is a fledgling package manager for World of Warcraft written
in Python.  It can be used to install, remove and update add-ons
from Curse and WoWInterface.

## Installation

Assuming you have Python 3.6 or higher:

```
pip3 install --process-dependency-links git+https://github.com/layday/instawow
```

## Basic operation

### Installing add-ons

You can install add-ons by their Curse project&nbsp;ID or slug, or their
WoWInterface&nbsp;ID, or even by their URL.  All of the following will install
Molinari:

```
instawow install curse:20338
instawow install curse:molinari
instawow install https://mods.curse.com/addons/wow/molinari
instawow install https://wow.curseforge.com/projects/molinari
instawow install wowi:13188
instawow install https://www.wowinterface.com/downloads/info13188-Molinari.html
```

By default _instawow_ will install the latest file to have been published on
Curse.  You may also install the latest file to have been uploaded
on the CurseForge or WowAce, be it stable, or beta or alpha quality,
by passing `--strategy==latest`.

You can opt into alpha updates anytime with
`instawow set --strategy=latest <add-on>` and revert to receiving stable updates
with `instawow set --strategy=canonical <add-on>`.
This setting only affects Curse packages.

### Updating

You can update all of your add-ons in one go with `instawow update` or any
individual add-on the same way you'd install or remove it:
`instawow update <add-on>`.

### Uninstalling

Uninstalling an add-on is as simple as `instawow remove <add-on>`.

### Other operations

You may list installed add-ons with `instawow list installed`; outdated add-ons
with `instawow list outdated`; and pre-existing add-ons with
`instawow list preexisting`.  The latter command will attempt to reconcile
add-on folders with their corresponding Curse IDs, where available.

To see information about an installed add-on, execute `instawow info <add-on>`.
To visit its homepage, execute `instawow hearth <add-on>`.  And to open its
main folder in your file manager, run `instawow reveal <add-on>`.

## Caveats

### Auto-detection

_instawow_ will only manage add-ons it itself installed.  The Twitch (née Curse)
client uses a proprietary fingerprinting algo that nobody (that I know) has
been able to figure out how is calculated.  Even if the fingerprint had been
reverse-engineered, I'd be loath to adopt it.  The fingerprint was born of a
desire to monopolise the add-on distribution market – or it would've
been made a community standard.

### Data completeness

There are sometimes gaps in the Curse data dump and _instawow_ might report
that existing add-ons do not exist.  This could be mitigated by using the
Curse SOAP&nbsp;API.  However the API does require users log into
Curse: an unnecessary burden complicated by the ongoing account migration to
Twitch.

### Discovery

_instawow_ aims to facilitate add-on management and not discovery.
It does not seek to drive users away from add-on portals; but to make
installing, updating and removing add-ons found on portals hassle-free
for those of us who are (ever so slightly) proficient with the command line
and do not particularly relish in using bloatware or inhabiting
walled gardens.

## Development

Fork and clone the repo, `cd` and:

```
python3 -m venv venv
source venv/bin/active
python3 -m pip install --process-dependency-links -e .[dev,test]
```

Happy hacking.

## Contributing

Bug reports and fixes are welcome.  Do open an issue before committing to making
any significant changes.
