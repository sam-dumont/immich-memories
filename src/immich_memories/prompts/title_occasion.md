<!-- title_occasion prompt v3 -->
Give the opening title of a personal memory film. Language: {lang}.

Facts
Memory type: {memory_type}
Span: {span}
{occasion_facts}
{required_year}

Rules
- Every name in the title comes from the facts above: an album's name, what the catalogue called the occasion, a place, a first name. A festival, a race, a venue, a town or an event no fact names did not happen. Reword the facts; never add to them.
- Place names above are English as the camera recorded them; write them as {lang} would (the English name becomes the name {lang} gives that same place; never a place the facts do not name). That is the only rewriting of a name allowed.
- An album the pictures sit in is what somebody already called this day: use that name rather than describing the day around it. Where an album name and the catalogue disagree, the album name wins.
- A special day is named by what happened that day; an album by its name, reworded only when the name is a date or a code; a holiday by the holiday and the family; a month, a season or a year by what ran through it.
- People: name people, only when they are the point of the film, by first name by default. Use a relationship word only when a fact line states that exact relationship between people this title names -- never a relationship to the film's maker. Nobody outside the people facts is named or given a role. A friend is named as a friend, or by first name -- never as family. When a fact backs a relationship word, use the word a family says at home (maman, papa, mamie, papy; mum, dad), not the civil register (mère, père).
- Sentence case: capitalise the first word and proper nouns, nothing else.
- Title: at most 40 characters. Subtitle: at most 50 characters or null; it may only state what a fact above states, so no distance, count, weather, time of day or feeling the facts are silent about; never a list of names. Null beats a guess.
- Dates: follow exactly what the "Year(s) the title or subtitle must show" fact says, in the title or the subtitle — "none" means no date at all.
- No generic openers such as "Souvenirs de", "Moments avec", "Voyage en", "Échos de", "Memories of".

Return ONLY JSON: {"title": "...", "subtitle": "..." or null, "reason": "one sentence"}
