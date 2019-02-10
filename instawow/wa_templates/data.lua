-- file generated automatically
WeakAurasCompanion = {
  slugs = {
  {% for wa in was %}
    ["{{ wa[0] }}"] = {
    {% for key, value in wa[1].items() %}
      {{ key }} = [=[{{ value }}]=],
    {% endfor %}
    },
  {% endfor %}
  },
  uids = {
  {% for uid in uids %}
    ["{{ uid[0] }}"] = [=[{{ uid[1] }}]=],
  {% endfor %}
  },
  ids = {
  {% for id in ids %}
    ["{{ id[0] }}"] = [=[{{ id[1] }}]=],
  {% endfor %}
  },
  stash = {
  {% for wa in stash %}
    ["{{ wa[0] }}"] = {
    {% for key, value in wa[1].items() %}
      {{ key }} = [=[{{ value }}]=],
    {% endfor %}
    },
  {% endfor %}
  }
}
