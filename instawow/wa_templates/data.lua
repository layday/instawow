-- file generated automatically
WeakAurasCompanion = {
  slugs = {
  {% for slug, aura_metadata in weakauras %}
    [ [=[{{ slug }}]=] ] = {
    {% for key, value in aura_metadata.items() %}
      {{ key }} = [=[{{ value }}]=],
    {% endfor %}
    },
  {% endfor %}
  },
  uids = {
  {% for uid, slug in weakaura_uids %}
    [ [=[{{ uid }}]=] ] = [=[{{ slug }}]=],
  {% endfor %}
  },
  ids = {
  {% for id, slug in weakaura_ids %}
    [ [=[{{ id }}]=] ] = [=[{{ slug }}]=],
  {% endfor %}
  },
  stash = {
  },
  Plater = {
    slugs = {
    {% for slug, aura_metadata in plateroos %}
      [ [=[{{ slug }}]=] ] = {
      {% for key, value in aura_metadata.items() %}
        {{ key }} = [=[{{ value }}]=],
      {% endfor %}
      },
    {% endfor %}
    },
    uids = {
    },
    ids = {
    {% for id, slug in plater_ids %}
      [ [=[{{ id }}]=] ] = [=[{{ slug }}]=],
    {% endfor %}
    },
    stash = {
    }
  }
}
