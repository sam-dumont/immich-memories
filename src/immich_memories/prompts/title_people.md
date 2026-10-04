<!-- title_people prompt v3 -->
Give the opening title of a personal memory film about people. Language: {lang}.

Facts
Memory type: {memory_type}
People condition (every picture satisfies it): {condition}
{people_facts}
Span: {span}
{required_year}

Rules
- Every name in the title comes from the facts above: a first name, a place, the album the film sits in. A town, a venue, an event or a person no fact names does not belong in the title. Reword the facts; never add to them.
- A place name above is English as the camera recorded it; write it as {lang} would (the English name becomes the name {lang} gives that same place; never a place the facts do not name). That is the only rewriting of a name allowed.
- Name people by first name by default. Use a relationship word (her grandmother, his best friend) only when a fact line above states that exact relationship between people this title names -- never a relationship to the film's maker, and never a relation no fact records. Nobody outside "People in the film" is named or given a role. A friend is named as a friend, or by first name -- never as family.
- The subject is the person the film follows. A child among adults is the subject.
- When a fact backs a relationship word, use the word a family says at home (maman, papa, mamie, papy; mum, dad), not the civil register (mère, père, mother, father).
- Sentence case: capitalise the first word and proper nouns, nothing else.
- Title: at most 40 characters. Subtitle: at most 50 characters or null; it may only state what a fact above states, so no age, count, place or span the facts are silent about; never a list of full names. Null beats a guess.
- Dates: follow exactly what the "Year(s) the title or subtitle must show" fact says, in the title or the subtitle — "none" means no date at all, whatever the span's own notes above say about it.
- No generic openers such as "Souvenirs de", "Moments avec", "Memories of".

Return ONLY JSON: {"title": "...", "subtitle": "..." or null, "reason": "one sentence"}
