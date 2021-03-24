{% for name, url, changelog in changelog_entries %}
## {{ name }} ({{ url }})
{{ changelog }}


{% endfor %}
