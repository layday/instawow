{% for name, url, version, changelog in changelog_entries %}
## {{ name }} v{{ version }} ({{ url }})

{{ changelog }}

{% endfor %}
